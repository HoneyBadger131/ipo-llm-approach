"""ETF 수량변경 일괄공시 날짜 스캔 — 대표 ETF 무변동일·타 운용사 공시까지 빠짐없이(커버리지 보강).

  .venv/bin/python kind/etf_scan.py --from 2026-07-09 --to 2026-10-08
하루치 전체 ETF 목록(`list_etf_day`, 하루 2~3쪽)에서 접수번호로 묶어 DB 에 없는 공시만 넣고 본문을 받는다. 파싱은 etf_parser.py.
제출인(운용사)은 meta 'etf_mgr:<filing_id>' 에 보관(etf_parser 가 신규 ETF 의 운용사로 사용).
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import kind_client as kc
import collector


def scan_day(con, day):
    rows = kc.list_etf_day(day)
    by = {}
    for r in rows:
        if "상장신청서" in r["title"]:
            by.setdefault(r["acpt_no"], r)
    new = 0
    for acpt, r in by.items():
        fid, is_new = collector.insert(con, r, None, None, "ETF", None)
        if r.get("submitter"):
            con.execute("INSERT OR IGNORE INTO meta(key,value) VALUES(?,?)", ("etf_mgr:" + fid, r["submitter"]))
        if is_new:
            new += 1
            collector.fetch_body(con, fid, acpt)
        elif con.execute("SELECT body_path FROM filing WHERE filing_id=?", (fid,)).fetchone()[0] is None:
            collector.fetch_body(con, fid, acpt)
        con.commit()
    return len(by), new


def main():
    a = sys.argv[1:]
    frm, to = a[a.index("--from") + 1], a[a.index("--to") + 1]
    con = db.connect()
    days = [r[0] for r in con.execute("SELECT cal_date FROM calendar_day WHERE is_trading=1 AND cal_date BETWEEN ? AND ? ORDER BY cal_date", (frm, to))]
    tot = 0
    for d in days:
        n, new = scan_day(con, d)
        tot += new
        print(d, f"일괄공시 {n}건 신규 {new}", flush=True)
    print("신규 총", tot)


if __name__ == "__main__":
    main()
