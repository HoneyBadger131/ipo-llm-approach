"""종목 확장 — 시총 상위 300 유니버스 등록 + 날짜 범위 스캔 적재.

  .venv/bin/python kind/scan_range.py --register                       # 유니버스(prices_*.csv ∪ kospi_list_clean.md) 종목 등록(watchlist 'universe')
  .venv/bin/python kind/scan_range.py --from 2026-01-01 --to 2026-10-08   # 거래일마다 이벤트 공시 스캔 → 유니버스 종목 공시 적재 + 본문 수신
멱등(이미 있는 filing 은 건너뜀)·중단 후 재실행 가능. 유니버스 밖 회사의 공시는 적재하지 않는다(상대방 법인은 결정 공시에서 register/register_extinct 가 별도로 등록·수집).
"""
import argparse
import csv
import glob
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collector
import db
import kind_client as kc
import scan_day
from seed_master import NOW, sec_by_code, upsert_issuer, upsert_security

UNI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "universe")
WATCH = "universe"


def universe_codes():
    codes = []
    fs = sorted(glob.glob(os.path.join(UNI, "prices_*.csv")))
    if fs:
        codes += [r["code"] for r in csv.DictReader(open(fs[-1], encoding="utf-8"))]
    codes += list(scan_day.load_universe(os.path.join(UNI, "kospi_list_clean.md")).values())
    return [c for c in dict.fromkeys(codes) if c not in excluded_codes()]


def excluded_codes():
    """kind/universe/exclude.txt — 제외 종목(단축코드가 줄 첫 토큰, '#' 주석)"""
    p = os.path.join(UNI, "exclude.txt")
    if not os.path.exists(p):
        return set()
    return {ln.split()[0] for ln in open(p, encoding="utf-8") if ln.strip() and not ln.startswith("#")}


def register(con):
    n_new, miss = 0, []
    for code in universe_codes():
        sid = sec_by_code(con, "SHORT", code)
        if sid is None:
            res = next((x for x in kc.resolve_name(code) if x.get("repisusrtcd") == "A" + code and x.get("secugrpId") == "ST"), None)
            time.sleep(0.4)
            if not res:
                miss.append(code)
                continue
            iss = upsert_issuer(con, res["comabbrv"], res["isurcd"])
            sid = upsert_security(con, iss, "COMMON", res["comabbrv"], code, res["repisucd"], None, "KOSPI")
            n_new += 1
        con.execute("INSERT OR IGNORE INTO watchlist VALUES (?,?,?)", (WATCH, sid, NOW))
    con.commit()
    return n_new, miss


def trading_days(con, frm, to):
    return [r[0] for r in con.execute("SELECT cal_date FROM calendar_day WHERE is_trading=1 AND cal_date BETWEEN ? AND ? ORDER BY cal_date", (frm, to))]


def run(con, frm, to, market="1"):
    uni = {r[0]: r[1] for r in con.execute("""SELECT sc.code, s.security_id FROM watchlist w JOIN security s USING(security_id)
                                              JOIN security_code sc ON sc.security_id=s.security_id AND sc.code_type='SHORT' WHERE w.watch_name=?""", (WATCH,))}
    for c in excluded_codes():
        uni.pop(c, None)
    st = {"days": 0, "rows": 0, "event": 0, "universe": 0, "new": 0, "bodies": 0, "unresolved": set()}
    mj_names = {"01": "수시공시", "02": "시장조치"}
    for i, day in enumerate(trading_days(con, frm, to), 1):
        rows = scan_day.scan(day, market)
        st["days"] += 1
        st["rows"] += len(rows)
        for r in rows:
            if not scan_day.EVENT_RE.search(r["title"]) or scan_day.SKIP_RE.search(r["title"]) or scan_day.ETF_RE.search(r["title"]):
                continue
            st["event"] += 1
            code = scan_day.code_of(r["company"])
            if code is None:
                st["unresolved"].add(r["company"])
                continue
            sid = uni.get(code)
            if sid is None:
                continue
            st["universe"] += 1
            iss = con.execute("SELECT issuer_id FROM security WHERE security_id=?", (sid,)).fetchone()[0]
            fid, is_new = collector.insert(con, r, iss, sid, mj_names[r["major"]], collector.skip_reason(r["title"]))
            if is_new:
                st["new"] += 1
                if not collector.skip_reason(r["title"]):
                    collector.fetch_body(con, fid, r["acpt_no"])
                    st["bodies"] += 1
            con.commit()
        if i % 20 == 0:
            print(f"  {day}: 일수 {st['days']} · 이벤트 {st['event']} · 유니버스 {st['universe']} · 신규 {st['new']} · 본문 {st['bodies']}", flush=True)
    return st


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", action="store_true")
    ap.add_argument("--from", dest="frm")
    ap.add_argument("--to")
    ap.add_argument("--market", default="1")
    a = ap.parse_args()
    con = db.connect()
    if a.register:
        n, miss = register(con)
        print(f"등록 신규 {n}종목, 해석 실패 {len(miss)}: {miss}")
    if a.frm and a.to:
        st = run(con, a.frm, a.to, a.market)
        print({k: (v if k != "unresolved" else f"{len(v)}곳") for k, v in st.items()})
        if st["unresolved"]:
            print("미해석 회사(일부):", sorted(st["unresolved"])[:15])
