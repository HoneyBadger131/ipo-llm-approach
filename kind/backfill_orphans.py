"""누락된 '최초 결정 공시'를 종목 단위로 보충한다(고려아연 유형).

정정 공시 본문에는 '정정대상 공시서류의 최초제출일'이 적혀 있다. 그 날짜에 같은 종목·같은 제목의 원본이 DB 에 없으면(스캔 시작일보다 앞서 제출된 경우 등)
그 종목에 대해서만 '최초제출일 하루'를 조회해 원본을 받는다(전체 스캔 구간을 넓히지 않는다). 멱등. 보충한 건수를 출력하므로,
보충이 있었다면 호출 측이 m1_parser → m2_* 를 다시 돌린다.

  .venv/bin/python kind/backfill_orphans.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collector
import db
import scan_day
from common import kdate, text_of

DECISION_TITLES = ("유상증자결정", "주식 소각 결정", "회사합병 결정", "무상증자결정", "주식배당결정", "주식분할 결정", "회사분할 결정", "자기주식 취득 결정")


def missing_originals(con):
    out = {}
    for f in con.execute("""SELECT f.* FROM filing f WHERE f.src='KIND' AND f.title IN (%s) AND f.body_path IS NOT NULL""" % ",".join("?" * len(DECISION_TITLES)), DECISION_TITLES).fetchall():
        head = re.sub(r"\s+", " ", text_of(f))[:400]
        m = re.search(r"정정대상 공시서류의 최초제출일\s*:?\s*\|?\s*([^|]{6,24})", head)
        d = kdate(m.group(1)) if m else None
        if not d:
            continue
        has = con.execute("SELECT 1 FROM filing WHERE security_id=? AND title=? AND acpt_no LIKE ?", (f["security_id"], f["title"], d.replace("-", "") + "%")).fetchone()
        if not has:
            out[(f["security_id"], d)] = f["title"]
    return out


def run(con):
    miss = missing_originals(con)
    n = 0
    for (sid, d), title in sorted(miss.items(), key=lambda kv: kv[0][1]):
        sec = con.execute("SELECT * FROM security WHERE security_id=?", (sid,)).fetchone()
        got = collector.collect_stock(con, sec, d, d, True, scan_day.EVENT_RE.pattern)
        print(f"  보충 {sec['name']} {d} {title}: 신규 {got}건")
        n += got
    return len(miss), n


if __name__ == "__main__":
    con = db.connect()
    m, n = run(con)
    print(f"누락 원본 후보 {m}건 → 신규 적재 {n}건")
