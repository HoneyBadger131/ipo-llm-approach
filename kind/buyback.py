"""자기주식 취득 진행 현황 — '자기주식 취득 결정'·'자기주식취득 신탁계약 체결 결정' 공시에서 기준일 현재 취득 중인 건을 뽑는다(소각 목적이든 아니든).

  .venv/bin/python kind/buyback.py [YYYY-MM-DD]
같은 법인·같은 시작일의 후속(정정) 공시는 최신 공시가 앞 값을 덮어쓴다. 기간(시작~종료)이 기준일을 포함하고, 이후 '신탁계약 해지 결정'이 없으면 진행 중.
소각 목적 여부: 취득목적에 '소각'이 있거나, 같은 취득 시작일의 소각 스레드(CXL:…:A<시작일>)가 있으면 소각 목적.
"""
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
from m1_parser import kdate, text_of
from m2_decision import num, split_items, toks

TITLES = ("자기주식 취득 결정", "자기주식취득 신탁계약 체결 결정")


def _items(text, anchor):
    ms = [m.start() for m in re.finditer(anchor, text)]
    best = {}
    for i in ms:
        its = split_items(toks(text[i:]))
        if len(its) >= len(best):
            best = its
    return {re.sub(r"\s+", "", l.split("(")[0]): v for l, v in best.values()}


def _after(vals, label, n=1):
    for i, v in enumerate(vals):
        if v.startswith(label):
            return vals[i + n] if i + n < len(vals) else None
    return None


def parse(title, text):
    if title.startswith("자기주식 취득 결정"):
        it = _items(text, r"1\.\s*취득예정주식")
        g = lambda k: next((v for kk, v in it.items() if re.sub(r"\s+", "", k) in kk), [])
        p = g("취득예상기간")
        return {"kind": "직접 취득", "shares": num(_after(g("취득예정주식"), "보통주식")), "amount": num(_after(g("취득예정금액"), "보통주식")),
                "start": kdate(_after(p, "시작일")) if _after(p, "시작일") not in (None, "-") else None, "end": kdate(_after(p, "종료일")) if _after(p, "종료일") not in (None, "-") else None,
                "purpose": (g("취득목적") or [None])[0], "method": (g("취득방법") or [None])[0]}
    it = _items(text, r"1\.\s*계약금액")
    g = lambda k: next((v for kk, v in it.items() if re.sub(r"\s+", "", k) in kk), [])
    p = g("계약기간")
    return {"kind": "신탁 취득", "shares": num(_after(g("취득예정주식"), "보통주식")), "amount": num((g("계약금액") or [None])[0]),
            "start": kdate(_after(p, "시작일")) if _after(p, "시작일") not in (None, "-") else None, "end": kdate(_after(p, "종료일")) if _after(p, "종료일") not in (None, "-") else None,
            "purpose": (g("계약목적") or [None])[0], "method": "신탁계약"}


def active(con, asof, window_days=0):
    """기준일 현재 진행 중인 자기주식 취득 목록(금액 큰 순)."""
    progs = {}
    for f in con.execute("""SELECT f.*, s.issuer_id AS iss FROM filing f JOIN security s USING(security_id)
                            WHERE f.src='KIND' AND f.title IN (?,?) AND f.body_path IS NOT NULL ORDER BY f.filed_at""", TITLES).fetchall():
        d = parse(f["title"], re.sub(r"[ \t]+", " ", text_of(f)))
        if not d["start"] or not d["end"]:
            continue
        d.update(filing_id=f["filing_id"], acpt_no=f["acpt_no"], title=f["title"], issuer_id=f["iss"], security_id=f["security_id"], filed_date=f["filed_date"])
        progs[(f["iss"], d["kind"], d["start"])] = d  # 같은 프로그램의 후속(정정) 공시는 최신이 덮어씀
    out = []
    for (iss, kind, start), d in progs.items():
        if not (d["start"] <= asof <= d["end"]):
            continue
        cancelled = con.execute("""SELECT 1 FROM filing f JOIN security s USING(security_id) WHERE s.issuer_id=? AND f.title LIKE '%신탁계약 해지 결정%' AND f.filed_date>=? AND f.filed_date<=?""",
                                (iss, d["filed_date"], asof)).fetchone()
        if cancelled and kind == "신탁 취득":
            continue
        cxl = con.execute("SELECT 1 FROM event WHERE event_type='TREASURY_CANCELLATION' AND thread_key=?", (f"CXL:{iss}:A{start}",)).fetchone()
        d["burn"] = bool(cxl) or "소각" in (d["purpose"] or "")
        d["name"] = con.execute("SELECT name FROM issuer WHERE issuer_id=?", (iss,)).fetchone()[0]
        out.append(d)
    out.sort(key=lambda x: -(x["amount"] or 0))
    return out


if __name__ == "__main__":
    con = db.connect()
    asof = sys.argv[1] if len(sys.argv) > 1 else dt.date.today().isoformat()
    for d in active(con, asof):
        print(f"{d['name']:<10} {d['kind']:<6} {(d['amount'] or 0) / 1e8:>9,.0f}억원 {d['start']}~{d['end']} {'소각' if d['burn'] else '    '} {d['purpose']}")
