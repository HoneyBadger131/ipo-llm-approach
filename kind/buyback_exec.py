"""자기주식 매매 체결내역(유가증권시장) 수집·파싱 — 자기주식 취득의 *실제* 진행(누적 체결량·금액)을 얻는다.

  .venv/bin/python kind/buyback_exec.py --from 2026-06-01 --to 2026-10-09      # 체결내역 적재(멱등, 본문 캐시)
  .venv/bin/python kind/buyback_exec.py --show 000660 [--from 2026-08-20]        # 종목별 일별 체결
KIND 시장조치 0326(자기주식매매 신청/체결내역): 거래일마다 '신청내역'·'체결내역' 각 1건(전 종목 한 문서). 체결내역 표 두 개:
  <<직접>> 번호·구분·종목·종목코드·신고서구분·신청수량·체결수량·체결금액(천원)·누적체결량·신고수량·비고  → 누적체결량/신고수량으로 진행률
  <<신탁>> 번호·구분·종목·종목코드·신고서구분·신청수량·체결수량·체결금액(천원)·평균체결가(원)·비고       → 일별 체결을 계약 시작일부터 합산
조회 구간은 330일 단위(1년 초과 시 서버가 0건).
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collector
import db
import kind_client as kc
from m2_decision import num, toks

TITLE_RE = re.compile(r"자기주식매매 체결내역\(유가증권시장\)")


def parse(text):
    """→ (체결일자, [dict]) — 매수만(구분 '매수'). 표 구조는 헤더 토큰 수로 행 폭을 정한다(직접 11, 신탁 10)."""
    tk = toks(text)
    m = re.search(r"체결일자[^\d]*(\d{4}-\d{2}-\d{2})", " ".join(tk))
    day = m.group(1) if m else None
    rows = []
    i = 0
    while i < len(tk):
        if tk[i] in ("<<직접>>", "<<신탁>>"):
            kind = tk[i][2:4]
            width = 11 if kind == "직접" else 10
            j = tk.index("비고", i) + 1 if "비고" in tk[i:] else None
            if j is None:
                break
            while j + width <= len(tk) and re.fullmatch(r"\d+", tk[j]):
                r = tk[j:j + width]
                if r[1] == "매수" and re.fullmatch(r"A\w{6}", r[3]):
                    d = {"kind": kind, "code": r[3][1:], "req": num(r[5]), "exec": num(r[6]), "amount": (num(r[7]) or 0) * 1000}
                    if kind == "직접":
                        d.update(cum=num(r[8]), plan=num(r[9]), avg=None)
                    else:
                        d.update(cum=None, plan=None, avg=num(r[8]))
                    rows.append(d)
                j += width
            i = j
        else:
            i += 1
    return day, rows


def scan(con, frm, to):
    n_new = n_rows = 0
    rows = []
    for a, b in collector.windows(frm, to):
        rows += kc.list_filings(frm=a, to=b, marketType="1", disclosureType02="0326|", pDisclosureType02="0326|")
    seen = {r[0] for r in con.execute("SELECT DISTINCT acpt_no FROM buyback_exec")}
    for r in sorted(rows, key=lambda r: r["datetime"]):
        if not TITLE_RE.search(r["title"]) or r["acpt_no"] in seen:
            continue
        day, items = parse(kc.body_text(r["acpt_no"]))
        if not day:
            continue
        for d in items:
            con.execute("INSERT OR REPLACE INTO buyback_exec VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (day, d["code"], d["kind"], d["req"], d["exec"], d["amount"], d["cum"], d["plan"], d["avg"], r["acpt_no"]))
        n_new += 1
        n_rows += len(items)
        con.commit()
    return n_new, n_rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", default="2026-06-01")
    ap.add_argument("--to")
    ap.add_argument("--show")
    a = ap.parse_args()
    con = db.connect()
    db.apply_schema(con)
    if a.to:
        n, r = scan(con, a.frm, a.to)
        print(f"체결내역 신규 {n}일 · {r}행")
    if a.show:
        for r in con.execute("SELECT * FROM buyback_exec WHERE code=? AND day>=? ORDER BY day", (a.show, a.frm)):
            print(r["day"], r["kind"], r["exec_shares"], f"{(r['exec_amount'] or 0) / 1e8:,.1f}억", "누적", r["cum_shares"], "신고", r["plan_shares"])
