"""KIND 일일 리포트(마크다운): 기준일 영업일 기준 ① 주식수 원장 ② 변동 이력 ③ 이벤트 캘린더(M1) ④ 시장경보·거래정지 현황(M3) ⑤ 유상증자 스레드(M2) ⑥ 처리 현황.
  .venv/bin/python kind/daily_report.py [YYYY-MM-DD]     # 기본: 오늘 이전(포함) 마지막 영업일
출력: 콘솔 + kind/reports/kind_<기준일>.md
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import index_shares
import m2_report

ROLE = {"EX_DATE": "기준가/락", "HALT_START": "거래정지 시작", "HALT_END": "거래정지 해제"}
TYPE = {"RIGHTS_EX": "권리락", "DIVIDEND_EX": "배당락", "HALT": "거래정지", "SPLIT_RELIST_PRICE": "분할 변경상장 기준가", "PAR_VALUE_CHANGE": "액면 변경", "CORPORATE_SPLIT": "회사분할(인적)", "CORPORATE_SPLIT_PHYSICAL": "회사분할(물적)"}


def main():
    con = db.connect()
    today = sys.argv[1] if len(sys.argv) > 1 else __import__("datetime").date.today().isoformat()
    asof = con.execute("SELECT max(cal_date) FROM calendar_day WHERE is_trading=1 AND cal_date<=?", (today,)).fetchone()[0]
    nxt = con.execute("SELECT next_trading_date FROM calendar_day WHERE cal_date=?", (asof,)).fetchone()[0]
    t0 = con.execute("SELECT tseq FROM calendar_day WHERE cal_date=?", (asof,)).fetchone()[0]
    horizon = con.execute("SELECT max(cal_date) FROM calendar_day WHERE is_trading=1 AND tseq<=?", (t0 + 20,)).fetchone()[0]
    back = con.execute("SELECT min(cal_date) FROM calendar_day WHERE is_trading=1 AND tseq>=?", (t0 - 60,)).fetchone()[0]
    L = [f"# KIND 리포트 — 기준일 {asof} (다음 영업일 {nxt})", "",
         "## 1. 상장주식수 원장 현황 (워치리스트 종목)", "",
         "| 종목 | 최신 상장주식수 | 지수 반영 주식수 | 최근 변동 | 변동 주식수 | 근거 |", "|---|---:|---:|---|---:|---|"]
    for s in con.execute("""SELECT s.security_id, s.name FROM watchlist w JOIN security s USING(security_id) WHERE w.watch_name='phase1' ORDER BY s.security_id"""):
        r = con.execute("""SELECT * FROM share_ledger WHERE security_id=? AND superseded_by IS NULL AND effective_date<=? ORDER BY effective_date DESC, ledger_id DESC LIMIT 1""",
                        (s["security_id"], asof)).fetchone()
        c = con.execute("""SELECT * FROM share_ledger WHERE security_id=? AND superseded_by IS NULL AND delta_shares IS NOT NULL AND effective_date<=? ORDER BY effective_date DESC LIMIT 1""",
                        (s["security_id"], asof)).fetchone()
        ix, _lst, pend, _it = index_shares.index_shares(con, s["security_id"], asof)
        ixs = f"{ix:,}" + (f" (+{pend:,} 선반영)" if pend else "") if ix else "-"
        L.append(f"| {s['name']} | {r['shares_after']:,} | {ixs} | {c['effective_date'] + ' ' + c['reason'] if c else '-'} | {(format(c['delta_shares'], '+,') if c else '-')} | `{c['source_filing_id'] if c else r['source_filing_id']}` |")
    L += ["", "_상장주식수 = DART 반기(2026-06-30) 시드 + KIND 변경·추가상장(변경상장일 기준). 지수 반영 주식수 = 상장주식수 + 주주배정 유상증자의 권리락일~신주 상장 전 선반영분 (지수 3원칙: 신규상장일·변경상장일 기준, 주주배정만 권리락일). `계산` = 공시에 없는 잔고를 앞/뒤 잔고에서 산출한 행._", ""]
    L += ["## 2. 원장 변동 이력", "", "| 종목 | 변경상장일 | 발행/소각일 | 전 | 증감 | 후 | 사유 | 계산 |", "|---|---|---|---:|---:|---:|---|---|"]
    for r in con.execute("""SELECT s.name, l.* FROM share_ledger l JOIN security s USING(security_id) WHERE l.reason NOT LIKE 'SEED:%' ORDER BY l.effective_date DESC"""):
        f = lambda v: "-" if v is None else format(v, ",")
        L.append(f"| {r['name']} | {r['effective_date']} | {r['issue_date'] or '-'} | {f(r['shares_before'])} | {f(r['delta_shares'])} | {f(r['shares_after'])} | {r['reason']} | {'계산' if r['is_computed'] else ''} |")
    L += ["", f"## 3. 이벤트 캘린더 ({back} ~ {horizon}, 과거 60영업일 + 향후 20영업일)", "",
          "| 일자 | 영업일 | 종목 | 이벤트 | 구분 | 상태 | 내용 |", "|---|:-:|---|---|---|---|---|"]
    rows = con.execute("""SELECT v.the_date, v.is_trading, s.name, v.event_type, v.role, v.status, v.condition_note, e.detail_json, v.source_filing_id
                          FROM v_event_calendar v JOIN event e USING(event_id) JOIN security s ON s.security_id=e.security_id
                          WHERE v.the_date BETWEEN ? AND ? ORDER BY v.the_date, s.security_id""", (back, horizon)).fetchall()
    for r in rows:
        if r["event_type"].startswith("CORPORATE_SPLIT") and r["role"] in ("HALT_START", "HALT_NOTICE"):
            continue  # 거래정지는 M1 의 HALT 이벤트로 이미 표시
        d = json.loads(r["detail_json"] or "{}")
        info = d.get("reason") or ""
        if d.get("prices") and "class" in d["prices"][0]:
            p = d["prices"][0]
            info += f" · {p['class']} {'/'.join(format(x, ',') for x in p['values'])}원"
        if r["condition_note"]:
            info += f" (해제일: {r['condition_note']} — 미확정)"
        L.append(f"| {r['the_date']} | {'○' if r['is_trading'] else '휴'} | {r['name']} | {TYPE.get(r['event_type'], r['event_type'])} | {ROLE.get(r['role'], r['role'])} | {r['status']} | {info} · `{r['source_filing_id']}` |")
    if not rows:
        L.append("| (해당 없음) | | | | | | |")
    KIND_KR = {"CAUTION": "투자주의", "WARNING_NOTICE": "투자경고 지정예고", "WARNING": "투자경고", "RISK": "투자위험", "SHORT_BAN": "공매도 과열(금지)", "HALT": "거래정지", "OVERHEAT": "단기과열"}
    L += ["", f"## 4. 시장경보·거래정지 현황 (기준일 {asof})", "", "### 4-1. 현재 지정 중", "",
          "| 종목 | 구분 | 시작 | 종료(마지막 지정일) | 종료 확정 | 근거 |", "|---|---|---|---|:-:|---|"]
    act = con.execute("""SELECT d.*, s.name FROM designation d JOIN security s USING(security_id)
                         WHERE d.start_date<=? AND (d.end_date IS NULL OR d.end_date>=? OR (d.end_is_estimated=1 AND d.state='active')) AND d.state='active' ORDER BY d.start_date""", (asof, asof)).fetchall()
    for d in act:
        L.append(f"| {d['name']} | {KIND_KR.get(d['kind'], d['kind'])} | {d['start_date']} | {d['end_date'] or '미정'} | {'확정' if not d['end_is_estimated'] else '추정'} | `{d['open_source_filing_id']}` |")
    if not act:
        L.append("| (현재 지정 중인 종목 없음) | | | | | |")
    L += ["", "### 4-2. 이력 (워치리스트, 최근 순)", "", "| 종목 | 구분 | 기간(포함) | 영업일수 | 상태 | 비고 |", "|---|---|---|---:|---|---|"]
    for d in con.execute("""SELECT d.*, s.name, (SELECT count(*) FROM calendar_day c WHERE c.is_trading=1 AND c.cal_date BETWEEN d.start_date AND coalesce(d.end_date,d.start_date)) nd
                            FROM designation d JOIN security s USING(security_id) ORDER BY d.start_date DESC"""):
        n = json.loads(d["note"] or "{}")
        memo = n.get("reason") or ""
        if n.get("release_date"):
            memo += f" / 해제일 {n['release_date']}"
        if n.get("converted_to"):
            memo += f" / → 투자경고 지정({n['converted_to']})"
        if n.get("pending_condition"):
            memo += f" / 해제 조건: {n['pending_condition']}"
        L.append(f"| {d['name']} | {KIND_KR.get(d['kind'], d['kind'])} | {d['start_date']} ~ {d['end_date'] or '미정'}{'(추정)' if d['end_is_estimated'] and d['end_date'] else ''} | {d['nd']} | {d['state']} | {memo[:90]} |")
    L += ["", "## 5. 유상증자 이벤트 스레드 (M2)", "", "★ = 지수·참여 핵심일 · D-day는 영업일 기준(`*`=휴장일) · ✅ 완료 / ⏳ 예정 / 추정 = 기준일에서 계산한 값", ""] + m2_report.render(con, asof)
    L += ["", "## 5-2. 자기주식 소각 스레드 (M2)", ""] + m2_report.render_cancel(con, asof)
    L += ["", "## 5-3. 전환사채·신주인수권부사채 (M2)", ""] + m2_report.render_cbbw(con, asof)
    L += ["", "## 5-4. 회사분할 — 인적분할 (M2)", ""] + m2_report.render_split(con, asof)
    L += ["", "## 6. 처리 현황", ""]
    for r in con.execute("""SELECT cat_major, parse_status, count(*) n FROM filing WHERE src='KIND' AND cat_major IN ('시장조치','수시공시') GROUP BY 1,2 ORDER BY 1,2"""):
        L.append(f"- {r['cat_major']} / {r['parse_status']}: {r['n']}건")
    L += ["", "미처리 시장조치(M3 대상):"]
    for r in con.execute("SELECT filed_date, title FROM filing WHERE cat_major='시장조치' AND parse_status='new' ORDER BY filed_at"):
        L.append(f"- {r['filed_date']} {r['title']}")
    out = os.path.join(db.HERE, "reports")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"kind_{asof}.md")
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\n→ {path}")


if __name__ == "__main__":
    main()
