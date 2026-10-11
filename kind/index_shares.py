"""지수 주식수(지수채용주식수) 산출 — 사용자 확정 3원칙(2026-10-10).

 1) 지수 주식수는 '주식의 신규상장일' 기준으로 증가한다. 증자(일반공모·제3자배정 등)로 늘어난 주식은 신주 상장일에 반영.
 2) 단, 기준가 조정이 일어나는 주주배정 유상증자는 '권리락일'에 주식수가 증가한다(신주 상장 전 선반영).
 3) 자사주 소각은 '변경상장일'에 감소한다 (소각결의 → 소각예정일 → 변경상장 공시 → 변경상장일).
구현: 상장주식수 원장(share_ledger; 변경·추가상장은 모두 상장/변경상장일 기준 → 1·3 충족) + 주주배정 선반영분(index_share_adj; 권리락일 ≤ 기준일 < 신주 상장일).
분할·합병 등은 별도 규칙(지침 대기). 이 함수는 증자·소각만 다룬다.
"""
import sys


def listed_shares(con, sid, d):
    r = con.execute("""SELECT shares_after FROM share_ledger WHERE security_id=? AND superseded_by IS NULL AND effective_date<=? AND shares_after IS NOT NULL
                       ORDER BY effective_date DESC, ledger_id DESC LIMIT 1""", (sid, d)).fetchone()
    if r:
        return r[0]
    r = con.execute("""SELECT reason, shares_before, shares_after FROM share_ledger WHERE security_id=? AND superseded_by IS NULL AND effective_date>? ORDER BY effective_date, ledger_id LIMIT 1""", (sid, d)).fetchone()
    if r:
        return r["shares_after"] if r["reason"].startswith("SEED:") else r["shares_before"]
    return None


def pending_rights_adj(con, sid, d):
    """효력일(권리락일 또는 신주 상장일) ≤ d 이면서, 원장에 해당 신주의 실제 상장 행이 아직 없는(상장일 ≤ d 로 연결된 행이 없는) 증자의 선반영 수량 합.
    상장 공시가 아직 없으면 예정일이 지나도 선반영을 유지한다(지수가 되돌아가면 안 됨)."""
    tot, items = 0, []
    for a in con.execute("""SELECT a.* FROM index_share_adj a WHERE a.security_id=? AND a.effective_date IS NOT NULL AND a.effective_date<=?
                            AND NOT EXISTS (SELECT 1 FROM share_ledger l WHERE l.event_id=a.event_id AND l.security_id=a.security_id AND l.effective_date<=? AND l.superseded_by IS NULL)""", (sid, d, d)):
        tot += a["delta_shares"]
        items.append((a["event_id"], a["effective_date"], a["delta_shares"]))
    return tot, items


def index_shares(con, sid, d):
    """→ (지수 주식수, 상장주식수, 선반영분, 선반영 내역). 상장주식수를 모르면 (None, …)."""
    lst = listed_shares(con, sid, d)
    pend, items = pending_rights_adj(con, sid, d)
    return (lst + pend if lst is not None else None), lst, pend, items


if __name__ == "__main__":
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import db
    con = db.connect()
    d = sys.argv[1] if len(sys.argv) > 1 else "2026-10-08"
    for s in con.execute("SELECT s.security_id, s.name FROM watchlist w JOIN security s USING(security_id) WHERE w.watch_name='phase1' ORDER BY 1"):
        ix, lst, pend, _ = index_shares(con, s["security_id"], d)
        print(f"{s['name']:<10} 상장 {lst or 0:>15,}  선반영 {pend:>12,}  지수 {ix or 0:>15,}")
