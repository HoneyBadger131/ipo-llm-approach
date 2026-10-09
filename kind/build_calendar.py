"""메인 캘린더(calendar_day) 빌드.

원천 우선순위: calendar_override(수동 보정) > exchange_calendars XKRX > (라이브러리 범위 밖) 평일=영업일 가정(unverified).
교차검증: 기존 DART 축 dart_calendar.HOLIDAYS 와 비교해 불일치를 출력한다.

  .venv/bin/python kind/build_calendar.py [--start 2015-01-01] [--end 2030-12-31]
재실행 안전(멱등): calendar_day 는 매번 전체 재생성, calendar_override 는 보존.
"""
import argparse
import datetime as dt
import os
import sys

import exchange_calendars as xc
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402

try:
    import holidays as _hol
except ImportError:  # 이름은 선택 사항
    _hol = None

# 라이브러리가 틀린/빠뜨린 날. evidence 필수. 새로 발견되면 여기에 추가(또는 DB에 직접 INSERT).
OVERRIDES = [
    ("2026-07-17", 0, "제헌절(2026년부터 공휴일 재지정)",
     "XKRX 라이브러리는 영업일로 표기. 근거: ① KIND ETF 일괄공시 7개에서 설정일 2026-07-16 → 상장예정일 2026-07-20(7/17 건너뜀), ② 해당일 ETF 설정/환매 0건, ③ DART 전체 공시 0건(전일 1,228건)."),
    ("2026-06-03", 0, "제9회 전국동시지방선거일",
     "XKRX 라이브러리는 영업일로 표기. 기존 dart_calendar.HOLIDAYS 에 휴장으로 기록(해당일 DART 공시 0건 확인). 선거일은 KRX 휴장."),
]


def kst(ts):
    return None if pd.isna(ts) else ts.tz_convert("Asia/Seoul").strftime("%H:%M")


def build(start, end):
    cal = xc.get_calendar("XKRX")
    lib_last = cal.last_session.date()
    lib_first = cal.first_session.date()
    sched = cal.schedule  # index: session date; open/close in UTC
    con = db.connect()
    db.apply_schema(con)
    cur = con.cursor()
    con.execute("PRAGMA foreign_keys = OFF")  # 재빌드 중에는 자식 테이블 FK 검사를 끄고, 끝에서 foreign_key_check 로 검증
    cur.execute("DELETE FROM calendar_day")
    for d, t, why, ev in OVERRIDES:
        cur.execute("INSERT OR IGNORE INTO calendar_override VALUES (?,?,?,?,?)",
                    (d, t, why, ev, dt.datetime.now().isoformat(timespec="seconds")))
    over = {r[0]: (r[1], r[2]) for r in cur.execute("SELECT cal_date,is_trading,reason FROM calendar_override")}
    kr = _hol.KR(years=range(start.year, end.year + 1), language="ko") if _hol else {}

    days, d = [], start
    while d <= end:
        days.append(d)
        d += dt.timedelta(days=1)

    rows, tseq, prev_t = [], 0, None
    is_t_list = []
    for d in days:
        iso = d.isoformat()
        wk = d.weekday() >= 5
        if iso in over:
            is_t, src, conf, nm = over[iso][0], "override", "verified", over[iso][1]
        elif lib_first <= d <= lib_last:
            ts = pd.Timestamp(d)
            is_t = 1 if ts in sched.index else 0
            src, conf, nm = "xkrx", "verified", None
        else:
            is_t, src, conf, nm = (0 if wk else 1), "weekday_only", "unverified", None
        if not is_t and not wk and nm is None:
            nm = kr.get(d) if kr else None
        if wk and not is_t:
            nm = None
        is_t_list.append(is_t)
        if is_t:
            tseq += 1
        o = c = None
        if is_t and src == "xkrx":
            r = sched.loc[pd.Timestamp(d)]
            o, c = kst(r["open"]), kst(r["close"])
        rows.append([iso, d.year, d.month, d.isoweekday(), int(wk), int(is_t),
                     "trading" if is_t else ("weekend" if wk else "holiday"), nm, src, conf, o, c, tseq, None, None,
                     (d - dt.timedelta(days=d.weekday())).isoformat(), f"{d.year}-{d.month:02d}"])
    # prev/next trading (엄격)
    n = len(rows)
    last = None
    for i in range(n):
        rows[i][13] = last
        if is_t_list[i]:
            last = rows[i][0]
    nxt = None
    for i in range(n - 1, -1, -1):
        rows[i][14] = nxt
        if is_t_list[i]:
            nxt = rows[i][0]
    cur.executemany("INSERT INTO calendar_day VALUES (" + ",".join("?" * 17) + ")", rows)
    for k, v in (("calendar_built_at", dt.datetime.now().isoformat(timespec="seconds")),
                 ("calendar_lib", f"exchange_calendars {xc.__version__} XKRX"),
                 ("calendar_verified_through", lib_last.isoformat()),
                 ("calendar_range", f"{start}..{end}")):
        cur.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
    con.commit()
    bad = con.execute("PRAGMA foreign_key_check").fetchall()
    con.execute("PRAGMA foreign_keys = ON")
    if bad:
        sys.exit(f"FK 위반 {len(bad)}건: {[tuple(b) for b in bad[:5]]}")
    return con, cal


def cross_check(con, cal):
    """dart_calendar.HOLIDAYS(2026) vs DB."""
    import dart_calendar as dc
    bad = []
    for h in sorted(dc.HOLIDAYS):
        r = con.execute("SELECT is_trading, day_type FROM calendar_day WHERE cal_date=?", (h.isoformat(),)).fetchone()
        if r and r["is_trading"] == 1:
            bad.append(h.isoformat())
    # DB 영업일 중 dart 가 휴장이라 한 날 / 반대로 dart 가 영업일이라 한 날
    mism = []
    for r in con.execute("SELECT cal_date FROM calendar_day WHERE cal_date BETWEEN '2026-01-01' AND '2026-12-31' AND is_trading=0 AND is_weekend=0"):
        if not dc.is_business(dt.date.fromisoformat(r[0])) is True:
            continue
        mism.append(r[0])
    return bad, mism


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default="2030-12-31")
    a = ap.parse_args()
    con, cal = build(dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end))
    q = lambda s: con.execute(s).fetchone()[0]
    print("rows", q("select count(*) from calendar_day"), "| trading", q("select count(*) from calendar_day where is_trading=1"),
          "| unverified", q("select count(*) from calendar_day where confidence='unverified'"))
    bad, mism = cross_check(con, cal)
    print("dart_calendar 휴장인데 DB 영업일:", bad or "없음")
    print("DB 휴장(평일)인데 dart_calendar 영업일:", mism or "없음")
