"""종목 상태 표지 — 관리종목(KIND 시장조치 0350 관리종목: 지정/지정사유변경/지정해제)의 최신 상태를 status_flag 에 기록.

  .venv/bin/python kind/status_flags.py [--to YYYY-MM-DD] [--from 2023-01-01]
판정: 종목(회사)별 가장 최근 공시가 '지정' 또는 '지정사유변경'이면 관리종목, '해제'면 아님. 유니버스(DB 의 security)에 있는 회사만 기록. ETF 관리종목은 제외.
KIND 공시조회 화면의 기업정보 옆 '관리종목' 표시와 같은 정보다. 조회 구간은 1년을 넘으면 서버가 0건을 주므로 330일 단위로 나눈다.
"""
import argparse
import datetime as dt
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collector
import db
import kind_client as kc
import scan_day


def run(con, frm, to):
    rows = []
    for a, b in collector.windows(frm, to):
        rows += kc.list_filings(frm=a, to=b, marketType="1", disclosureType02="0350|", pDisclosureType02="0350|")
    # 우선주 지정(제목 괄호에 '…우선주'/'…우')은 보통주가 관리종목인 것이 아니므로 제외(우선주는 다루지 않는다)
    rows = [r for r in rows if "관리종목" in r["title"] and not r["title"].startswith("ETF") and not re.search(r"\([^)]*우(선주)?[^)]*\)", r["title"])]
    rows.sort(key=lambda r: r["datetime"])
    state = {}
    for r in rows:
        st = state.setdefault(r["company"], {"flag": False, "since": None})
        if "해제" in r["title"]:
            st["flag"], st["since"] = False, None
        else:
            if not st["flag"]:
                st["since"] = r["datetime"][:10]
            st["flag"] = True
        st.update(last=r["datetime"][:10], title=re.sub(r"\(.*", "", r["title"]), acpt=r["acpt_no"])
    con.execute("DELETE FROM status_flag WHERE flag='관리종목'")
    n = 0
    for name, st in state.items():
        if not st["flag"]:
            continue
        code = scan_day.code_of(name)
        time.sleep(0.3)
        sid = con.execute("SELECT security_id FROM security_code WHERE code_type='SHORT' AND code=?", (code,)).fetchone() if code else None
        if sid:
            con.execute("INSERT OR REPLACE INTO status_flag VALUES (?,?,?,?,?,?)", (sid[0], "관리종목", st["since"], st["last"], st["title"], st["acpt"]))
            n += 1
    con.commit()
    return n, len([1 for s in state.values() if s["flag"]])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", default="2023-01-01")
    ap.add_argument("--to", default=dt.date.today().isoformat())
    a = ap.parse_args()
    con = db.connect()
    db.apply_schema(con)
    n, total = run(con, a.frm, a.to)
    print(f"관리종목 지정 중 {total}곳 중 유니버스 {n}곳 기록")
    for r in con.execute("SELECT s.name, f.since, f.last_date, f.note FROM status_flag f JOIN security s USING(security_id) ORDER BY s.name"):
        print(f"  {r['name']}: 지정 {r['since']} · 최근 {r['last_date']} {r['note']}")
