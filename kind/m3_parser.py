"""M3 파서: 시장경보(투자주의/경고/위험)·공매도과열·거래정지 → designation (지정 기간 추적).

종료일 규약: designation.end_date = '지정된 마지막 날(포함)'. 해제 공시의 '지정해제일'은 첫 비지정일이므로 직전 영업일로 환산해 저장한다.
상태 머신(종목별):
  [특정계좌 매매관여 등 투자주의(1일간)]                 → CAUTION   start=end
  [투자주의]투자경고종목 지정예고(1일 투자주의 + 판단기간) → WARNING_NOTICE  start=예고일, end=판단 마지막일(순연 한도)
  투자경고종목 지정(지정일)                              → WARNING   start=지정일, end=최초 해제판단일(가능 최단, estimated)
  투자경고종목 지정해제(해제일)                          → 해당 WARNING 종료 확정(end=해제일 직전 영업일)
  공매도 과열종목 지정                                   → SHORT_BAN start=지정일, 지정일 1일간
  (M1의 HALT 이벤트)                                     → HALT      start=정지일, end=해제일 직전 영업일(조건부면 미정)
미구현 서식(투자위험·단기과열·공매도 연장·해제 예고 등)은 review 로 남겨 사용자 확인 대상으로 한다.

  .venv/bin/python kind/m3_parser.py [--all] [--asof YYYY-MM-DD]
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import kind_client as kc
from common import kdate, text_of
from m1_parser import sibling


def flat(text):
    t = re.sub(r"[+\-]{8,}\+?", " ", text)
    return re.sub(r"\s+", " ", t)


def row(t, label):
    """박스 표의 '| N. 라벨 | 값 |' 값 셀"""
    m = re.search(r"\|\s*\d\.\s*" + label + r"\s*\|\s*([^|]*?)\s*\|(?:\s*([^|]*?)\s*\|)?", t)
    return (m.group(1), m.group(2)) if m else (None, None)


def tidy(s):
    return re.sub(r"\s*\|\s*", " ", s or "").strip(" -")[:240]


def prev_trading(con, d):
    return con.execute("SELECT prev_trading_date FROM calendar_day WHERE cal_date=?", (d,)).fetchone()[0]


def next_trading(con, d):
    return con.execute("SELECT next_trading_date FROM calendar_day WHERE cal_date=?", (d,)).fetchone()[0]


def target_security(con, f, cls_cell):
    sid = f["security_id"]
    if cls_cell and "우" in cls_cell:
        iss = con.execute("SELECT issuer_id FROM security WHERE security_id=?", (sid,)).fetchone()[0]
        sid = sibling(con, iss, "PREFERRED") or sid
    return sid


def upsert(con, sid, kind, start, end, est, state, src, note):
    r = con.execute("SELECT designation_id FROM designation WHERE security_id=? AND kind=? AND start_date=?", (sid, kind, start)).fetchone()
    if r:
        return r[0]
    return con.execute("""INSERT INTO designation(security_id,kind,start_date,end_date,end_is_estimated,state,open_source_filing_id,note)
                          VALUES (?,?,?,?,?,?,?,?)""", (sid, kind, start, end, est, state, src, json.dumps(note, ensure_ascii=False))).lastrowid


# ───────────── 서식별 핸들러 ─────────────
def p_caution(con, f, text):
    m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})일\((\d+)일간\)\s*투자주의종목으로 지정", flat(text))
    if not m:
        return "review", "caution_date"
    start = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    n = int(m.group(4))
    end = start
    for _ in range(n - 1):
        end = next_trading(con, end)
    reason = re.sub(r"^\[투자주의\]\s*", "", f["title"])
    upsert(con, f["security_id"], "CAUTION", start, end, 0, "ended", f["filing_id"], {"reason": reason, "days": n})
    return "parsed", None


def p_warning_notice(con, f, text):
    t = flat(text)
    tgt, cls = row(t, "대상종목")
    d0, _ = row(t, "지정예고일")
    notice = kdate(d0)
    m = re.search(r"\(\s*(\d{4}년\s*\d{1,2}월\s*\d{1,2}일)까지\)", t)
    last = kdate(m.group(1)) if m else None
    first = re.search(r"최초 판단일은\s*(\d{1,2})월\s*(\d{1,2})일", t)
    if not (notice and last):
        return "review", f"warning_notice notice={notice} last={last}"
    why = tidy(row(t, "지정예고사유")[0])
    sid = target_security(con, f, t[t.find("대상종목"):][:80])
    upsert(con, sid, "WARNING_NOTICE", notice, last, 1, "ended", f["filing_id"],
           {"reason": why, "first_judgement": f"{notice[:4]}-{int(first.group(1)):02d}-{int(first.group(2)):02d}" if first else None,
            "note": "예고일 1일 투자주의 + 판단기간(순연 한도)까지. 지정되지 않으면 그대로 종료"})
    return "parsed", None


def p_warning_designate(con, f, text):
    t = flat(text)
    d, _ = row(t, "지정일")
    start = kdate(d)
    j = re.search(r"최초 판단일은\s*(\d{1,2})월\s*(\d{1,2})일", t)
    if not start:
        return "review", "warning_start"
    judge = None
    if j:
        y = int(start[:4]) + (1 if int(j.group(1)) < int(start[5:7]) else 0)  # 연말 걸침 대응
        judge = f"{y}-{int(j.group(1)):02d}-{int(j.group(2)):02d}"
    why = re.search(r"지정사유\s*\|\s*(.*?)\s*\|?\s*4\.", t)
    sid = target_security(con, f, t[t.find("대상종목"):][:80])
    upsert(con, sid, "WARNING", start, judge, 1, "active", f["filing_id"],
           {"reason": tidy(why.group(1)) if why else None, "first_release_judgement": judge,
            "note": "end_date = 최초 해제판단일(가능 최단). 해제요건 불충족 시 하루씩 순연"})
    # 지정예고 → 지정 연결: 예고 창 안에 시작한 WARNING 이면 예고 상태를 '전환됨'으로 표기
    con.execute("""UPDATE designation SET note=json_set(coalesce(note,'{}'),'$.converted_to',?) WHERE security_id=? AND kind='WARNING_NOTICE'
                   AND start_date<=? AND end_date>=?""", (start, sid, start, start))
    return "parsed", None


def p_warning_release(con, f, text):
    t = flat(text)
    d, _ = row(t, "지정해제일")
    rel = kdate(d)
    why = tidy(row(t, "해제사유")[0])
    if not rel:
        return "review", "release_date"
    sid = target_security(con, f, t[t.find("대상종목"):][:80])
    last = prev_trading(con, rel)
    if con.execute("SELECT 1 FROM designation WHERE close_source_filing_id=?", (f["filing_id"],)).fetchone():
        return "parsed", None  # 재실행: 이미 이 공시로 종료 처리됨
    r = con.execute("""SELECT designation_id FROM designation WHERE security_id=? AND kind='WARNING' AND start_date<=? AND state='active'
                       ORDER BY start_date DESC LIMIT 1""", (sid, rel)).fetchone()
    if not r:
        return "review", "release_without_open_warning"
    con.execute("""UPDATE designation SET end_date=?, end_is_estimated=0, state='ended', close_source_filing_id=?,
                   note=json_set(coalesce(note,'{}'),'$.release_date',?,'$.release_reason',?) WHERE designation_id=?""",
                (last, f["filing_id"], rel, why, r[0]))
    return "parsed", None


def p_short_ban(con, f, text):
    t = flat(text)
    m = re.search(r"지정일\s*\|?\s*(\d{4}-\d{2}-\d{2})", t)
    n = re.search(r"지정일\s*(\d+)일\s*간", t)
    if not m:
        return "review", "shortban_date"
    start = m.group(1)
    end = start
    for _ in range(int(n.group(1)) - 1 if n else 0):
        end = next_trading(con, end)
    upsert(con, f["security_id"], "SHORT_BAN", start, end, 0, "ended", f["filing_id"],
           {"reason": "공매도 과열종목 지정", "note": "지정일 -5% 이상 하락 시 금지 연장(연장 공시 별도)"})
    return "parsed", None


HANDLERS = [
    (re.compile(r"^\[투자주의\].*투자경고종목 지정예고"), p_warning_notice),
    (re.compile(r"^\[투자주의\]"), p_caution),
    (re.compile(r"^투자경고종목 ?지정해제"), p_warning_release),
    (re.compile(r"^투자경고종목 ?지정$"), p_warning_designate),
    (re.compile(r"^공매도 과열종목 지정"), p_short_ban),
]


def derive_halts(con):
    """M1 의 HALT 이벤트 → designation(HALT). 조건부 해제는 미정(active)."""
    n = 0
    for e in con.execute("SELECT * FROM event WHERE event_type='HALT'").fetchall():
        s = con.execute("SELECT the_date, source_filing_id FROM event_date WHERE event_id=? AND role='HALT_START' AND superseded_by IS NULL", (e["event_id"],)).fetchone()
        en = con.execute("SELECT the_date, condition_note FROM event_date WHERE event_id=? AND role='HALT_END' AND superseded_by IS NULL", (e["event_id"],)).fetchone()
        if not s:
            continue
        end, est, state = None, 1, "active"
        det = json.loads(e["detail_json"] or "{}")
        if det.get("intraday"):  # 장중 정지: 그날 하루
            end, est, state = s["the_date"], 0, "ended"
        elif en and not en["condition_note"]:  # HALT_END = 거래 재개일 → 마지막 정지일은 그 직전 영업일
            end, est, state = prev_trading(con, en["the_date"]), 0, "ended"
        note = {"reason": json.loads(e["detail_json"] or "{}").get("reason"), "resume_date": en["the_date"] if en and not en["condition_note"] else None,
                "pending_condition": en["condition_note"] if en else None, "event_id": e["event_id"], "intraday": det.get("intraday")}
        con.execute("DELETE FROM designation WHERE security_id=? AND kind='HALT' AND start_date=?", (e["security_id"], s["the_date"]))
        upsert(con, e["security_id"], "HALT", s["the_date"], end, est, state, s["source_filing_id"], note)
        n += 1
    return n


def reconcile(con, asof):
    """as-of 기준 상태 갱신: 확정 종료일이 asof 이전이면 ended, 추정 종료일이 지났어도 해제 공시가 없으면 active 유지(경고)."""
    for d in con.execute("SELECT * FROM designation WHERE state<>'cancelled'").fetchall():
        if d["end_date"] and d["end_is_estimated"] == 0:
            st = "ended" if d["end_date"] < asof else "active"
        elif d["kind"] in ("WARNING_NOTICE", "CAUTION", "SHORT_BAN"):
            st = "ended" if (d["end_date"] or d["start_date"]) < asof else "active"
        else:
            st = "active"  # WARNING/HALT/RISK: 해제 공시 전까지는 active (추정 종료일은 참고)
        if st != d["state"]:
            con.execute("UPDATE designation SET state=? WHERE designation_id=?", (st, d["designation_id"]))


def run(con, only_new=True, asof=None):
    asof = asof or dt.date.today().isoformat()
    q = "SELECT * FROM filing WHERE src='KIND' AND cat_major='시장조치' AND body_path IS NOT NULL AND parse_status IN ('new','failed','review')" if only_new else \
        "SELECT * FROM filing WHERE src='KIND' AND cat_major='시장조치' AND body_path IS NOT NULL"
    st = {"parsed": 0, "review": 0, "failed": 0, "other": []}
    for f in con.execute(q + " ORDER BY filed_at").fetchall():
        h = next((fn for rx, fn in HANDLERS if rx.search(f["title"])), None)
        if h is None:
            if f["parse_status"] == "new":
                st["other"].append((f["filed_date"], f["title"]))
            continue
        try:
            s, why = h(con, f, text_of(f))
        except Exception as e:
            s, why = "failed", f"{type(e).__name__}: {e}"
        con.execute("UPDATE filing SET parse_status=?, skip_reason=? WHERE filing_id=?", (s, why, f["filing_id"]))
        st[s] += 1
        con.commit()
    st["halts"] = derive_halts(con)
    reconcile(con, asof)
    con.commit()
    return st


if __name__ == "__main__":
    con = db.connect()
    asof = sys.argv[sys.argv.index("--asof") + 1] if "--asof" in sys.argv else None
    s = run(con, only_new="--all" not in sys.argv, asof=asof)
    print({k: (v if k != "other" else f"{len(v)}건") for k, v in s.items()})
    for o in s["other"]:
        print("  미처리:", o)
