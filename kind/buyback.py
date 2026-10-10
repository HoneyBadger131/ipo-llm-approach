"""자기주식 취득 진행 현황 — '자기주식 취득 결정'·'자기주식취득 신탁계약 체결 결정' 공시에서 기준일 현재 취득 중인 건을 뽑는다(소각 목적이든 아니든).

  .venv/bin/python kind/buyback.py [YYYY-MM-DD]
같은 법인·같은 시작일의 후속(정정) 공시는 최신 공시가 앞 값을 덮어쓴다. 기간(시작~종료)이 기준일을 포함하고, 이후 '신탁계약 해지 결정'이 없으면 진행 중.
소각 목적 여부: 취득목적에 '소각'이 있거나, 같은 취득 시작일의 소각 스레드(CXL:…:A<시작일>)가 있으면 소각 목적.
"""
import datetime as dt
import json
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


def _quotes():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "universe", "bb_quotes.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def market_context(con, code, d, prog):
    """삼성전자·SK하이닉스 등 시세 파일(universe/bb_quotes.json)이 있는 종목: 시총·거래대금 대비 취득 규모(수급 영향도).
    최근 10거래일 일평균 거래대금 대비 같은 날짜의 매입 금액·수량 비중, 남은 금액이 일 거래대금의 며칠치인지."""
    q = _quotes().get(code)
    if not q or not q.get("days"):
        return None
    days = sorted(q["days"])[-10:]
    kind = "직접" if d["kind"].startswith("직접") else "신탁"
    ex = {r["day"]: r for r in con.execute("SELECT day, exec_shares, exec_amount FROM buyback_exec WHERE code=? AND kind=? AND day BETWEEN ? AND ?", (code, kind, days[0], days[-1]))}
    val = sum(q["days"][x]["value"] for x in days)
    vol = sum(q["days"][x]["volume"] for x in days)
    buy_amt = sum((ex[x]["exec_amount"] or 0) for x in days if x in ex)
    buy_sh = sum((ex[x]["exec_shares"] or 0) for x in days if x in ex)
    mc = q["days"][days[-1]]["mktcap"]
    plan = d["amount"] or 0
    return {"through": days[-1], "n": len(days), "mktcap": mc, "plan_pct": plan / mc * 100, "remain_pct": prog["remaining"] / mc * 100,
            "avg_value": val / len(days), "buy_value_share": buy_amt / val * 100 if val else None, "buy_volume_share": buy_sh / vol * 100 if vol else None,
            "remain_days_of_value": prog["remaining"] / (val / len(days)) if val else None, "avg_buy": buy_amt / len(days)}


def progress(con, d, asof):
    """프로그램 d(취득 시작·종료·예정금액)의 *실적* 진행 — buyback_exec(자기주식매매 체결내역)가 있으면 누적 체결금액·수량, 최근 10거래일 속도, 현 속도의 예상 소진일.
    없으면 기간 경과 비례 추정(basis='time')."""
    code = (con.execute("SELECT code FROM security_code WHERE security_id=? AND code_type='SHORT'", (d["security_id"],)).fetchone() or [None])[0]
    kind = "직접" if d["kind"].startswith("직접") else "신탁"
    rows = con.execute("SELECT day, exec_shares, exec_amount, cum_shares, plan_shares FROM buyback_exec WHERE code=? AND kind=? AND day BETWEEN ? AND ? ORDER BY day",
                       (code, kind, d["start"], min(d["end"], asof))).fetchall() if code else []
    plan_amt = d["amount"] or 0
    out = {"basis": "time", "data_through": None}
    if not rows or not plan_amt:
        tot = max(1, (dt.date.fromisoformat(d["end"]) - dt.date.fromisoformat(d["start"])).days + 1)
        el = min(tot, max(0, (dt.date.fromisoformat(asof) - dt.date.fromisoformat(d["start"])).days + 1))
        out.update(frac=el / tot, acquired=round(plan_amt * el / tot), remaining=round(plan_amt * (1 - el / tot)), proj_end=None)
        return out
    acq_amt = sum(r["exec_amount"] or 0 for r in rows)
    acq_sh = sum(r["exec_shares"] or 0 for r in rows)
    last = rows[-1]["day"]
    t_last = con.execute("SELECT tseq FROM calendar_day WHERE cal_date=?", (last,)).fetchone()[0]
    t_start = con.execute("SELECT min(tseq) FROM calendar_day WHERE is_trading=1 AND cal_date>=?", (d["start"],)).fetchone()[0]
    span = max(1, min(10, t_last - t_start + 1))
    recent = [r for r in rows if con.execute("SELECT tseq FROM calendar_day WHERE cal_date=?", (r["day"],)).fetchone()[0] > t_last - span]
    pace_amt = sum(r["exec_amount"] or 0 for r in recent) / span
    pace_sh = sum(r["exec_shares"] or 0 for r in recent) / span
    remaining = max(0, plan_amt - acq_amt)
    exhausted = remaining <= max(0.002 * plan_amt, 1_000_000)  # 금액 한도 소진(삼성전자: 누적 체결금액이 계획 15조원과 정확히 일치). 신고수량(주식수)은 초과해도 계속 산다 → 한도는 금액
    if exhausted:
        remaining = 0
    proj = None
    if exhausted:
        proj = last
    elif pace_amt > 0:
        n = int(-(-remaining // pace_amt))
        r2 = con.execute("SELECT cal_date FROM calendar_day WHERE is_trading=1 AND tseq=?", (t_last + n,)).fetchone()
        proj = min(r2[0], d["end"]) if r2 else d["end"]
    stalled = bool(proj and not exhausted and proj < asof)  # 마지막 체결이 오래돼 '예상 소진일'이 과거로 나옴 = 최근 체결 없음(중단·종료 가능)
    if stalled:
        proj = None
    out.update(stalled=stalled, basis="actual", data_through=last, frac=min(1.0, acq_amt / plan_amt), acquired=acq_amt, acq_shares=acq_sh, remaining=remaining, pace_shares=round(pace_sh), pace_amount=round(pace_amt),
               proj_end=proj, cum_shares=rows[-1]["cum_shares"], plan_shares=rows[-1]["plan_shares"], exhausted=exhausted)
    return out


def projection(con, issuer_id, start, asof):
    """취득 후 소각 스레드(m2_cancel)용: 이 법인·취득 시작일의 프로그램이 현 속도로 끝나는 예상일(계획 종료일보다 빠를 때만 의미)."""
    for kind in ("직접 취득", "신탁 취득"):
        for f in con.execute("""SELECT f.*, s.issuer_id AS iss FROM filing f JOIN security s USING(security_id) WHERE f.src='KIND' AND s.issuer_id=? AND f.title IN (?,?) AND f.body_path IS NOT NULL""", (issuer_id, *TITLES)).fetchall():
            d = parse(f["title"], re.sub(r"[ \t]+", " ", text_of(f)))
            if d["start"] == start and d["kind"] == kind and d["end"]:
                d.update(security_id=f["security_id"])
                p = progress(con, d, asof)
                if p["basis"] == "actual":
                    return {**p, "plan_end": d["end"]}
    return None


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
        d["prog"] = progress(con, d, asof)
        code_ = (con.execute("SELECT code FROM security_code WHERE security_id=? AND code_type='SHORT'", (d["security_id"],)).fetchone() or [None])[0]
        d["prog"]["ctx"] = market_context(con, code_, d, d["prog"]) if code_ else None
        out.append(d)
    out.sort(key=lambda x: -(x["prog"]["remaining"] or 0))
    return out


if __name__ == "__main__":
    con = db.connect()
    asof = sys.argv[1] if len(sys.argv) > 1 else dt.date.today().isoformat()
    for d in active(con, asof):
        p = d["prog"]
        print(f"{d['name']:<10} {d['kind']:<6} 총 {(d['amount'] or 0) / 1e8:>8,.0f}억 취득 {p['frac'] * 100:5.1f}% 남은 {p['remaining'] / 1e8:>8,.0f}억 {p['basis']:<6} 종료 {d['end']} 예상소진 {p.get('proj_end')} {'소각' if d['burn'] else '    '}")
