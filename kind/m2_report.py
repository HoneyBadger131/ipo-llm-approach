"""유상증자 스레드 카드(마크다운). 일일 리포트 5절과 단독 실행 모두에서 쓴다.

카드 구성: 현재 단계 → 왜(목적 한 줄) → 규모·발행가 → 구주주 참여 규모 → 지수 영향 → 일정 → 정정 이력.
  .venv/bin/python kind/m2_report.py [YYYY-MM-DD] [--all]     # → kind/reports/m2_rights_issue_<asof>.md   (--all: 완료 후 120일 지난 스레드도 표시)
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

LABEL = {"RESOLUTION": "유상증자 결정 공시", "PRICE_FIRST_FIXED": "1차 발행가액 확정 공시", "EX_DATE": "권리락일", "RECORD": "신주배정기준일",
         "RIGHTS_LIST_START": "신주인수권증서 상장(거래 시작)", "RIGHTS_LIST_END": "신주인수권증서 거래 종료", "RIGHTS_DELIST": "신주인수권증서 상장폐지",
         "PRICE_FINAL_DUE": "최종 발행가액 확정(예정)", "PRICE_FINAL_FIXED": "최종 발행가액 확정 공시", "SUB_ESOP": "우리사주조합 청약",
         "SUB_OLD_START": "구주주 청약 시작", "SUB_OLD_END": "구주주 청약 종료", "PUBLIC_OFFER_START": "일반공모 청약 시작", "PUBLIC_OFFER_END": "일반공모 청약 종료",
         "PAYMENT": "납입일", "ISSUE": "신주 발행일", "NEW_SHARE_LISTING": "신주 상장"}
KEY = {"EX_DATE", "SUB_OLD_END", "NEW_SHARE_LISTING"}  # 지수·참여 관점에서 가장 중요한 날
ORDER = list(LABEL)
STAGES = [("RESOLUTION", "결정 공시"), ("PRICE_FIRST_FIXED", "1차 발행가 확정"), ("EX_DATE", "권리락"), ("RIGHTS_LIST_START", "신주인수권증서 거래"),
          ("SUB_OLD_START", "청약"), ("PAYMENT", "납입"), ("NEW_SHARE_LISTING", "신주 상장")]


def won(v):
    if v is None:
        return "-"
    return f"{v / 1e12:.3f}조원" if v >= 1e12 else (f"{v / 1e8:,.0f}억원" if v >= 1e8 else f"{v:,.0f}원")


def dday(con, asof, d):
    a = con.execute("SELECT tseq FROM calendar_day WHERE cal_date=?", (asof,)).fetchone()[0]
    b = con.execute("SELECT tseq FROM calendar_day WHERE cal_date=?", (d,)).fetchone()[0]
    n = b - a
    nt = con.execute("SELECT is_trading FROM calendar_day WHERE cal_date=?", (d,)).fetchone()[0]
    if d == asof:
        return "D-day"
    return (f"D-{n}" if n > 0 else (f"D+{-n}" if n < 0 else "D-day")) + ("" if nt else "*")


def fmt_change(k, old, new):
    names = {"new_shares": "신주수", "price_expected": "예정발행가", "price_confirmed": "확정발행가", "record_date": "신주배정기준일", "payment_date": "납입일",
             "listing_date": "신주 상장예정일", "alloc_ratio": "1주당 배정", "method": "방식", "esop_pct": "우리사주 비율", "use_of_funds": "자금용도",
             "subscription": "청약일정", "public_offer": "일반공모일"}
    if k == "subscription" and isinstance(old, dict) and isinstance(new, dict):
        sm = lambda s_: ("미정" if not any(s_.values()) else f"우리사주 {s_.get('우리사주조합_start')}, 구주주 {s_.get('구주주_start')}~{s_.get('구주주_end')}")
        return f"청약일정: {sm(old)} → {sm(new)}"
    f = lambda v: "미정" if v in (None, {}, [], ()) else (f"{v:,}" if isinstance(v, (int, float)) and k not in ("alloc_ratio", "esop_pct") else
                                                             (", ".join(f"{a} {b:,}" for a, b in v.items()) if k == "use_of_funds" and isinstance(v, dict) else
                                                              (", ".join(f"{a} {b}" for a, b in v.items()) if isinstance(v, dict) else
                                                               (" ~ ".join(str(x) for x in v) if isinstance(v, (list, tuple)) else str(v)))))
    return f"{names.get(k, k)}: {f(old)} → {f(new)}"


def card(con, e, asof):
    d = json.loads(e["detail_json"] or "{}")
    sec = con.execute("SELECT s.name FROM security s WHERE s.security_id=?", (e["security_id"],)).fetchone()[0]
    slots = {r["role"]: r for r in con.execute("SELECT * FROM event_date WHERE event_id=? AND superseded_by IS NULL", (e["event_id"],))}
    L = [f"### {sec} 유상증자 — {d.get('method')}", ""]
    track = d.get("track")
    # 단계
    done = [k for k, _ in STAGES if k in slots and slots[k]["the_date"] <= asof]
    nxt = sorted((v["the_date"], k) for k, v in slots.items() if v["the_date"] > asof and k in LABEL)
    cur = (dict(STAGES).get(done[-1]) if done else "결정 전") if e["status"] != "done" else "완료(신주 상장)"
    nx = f" · 다음: **{LABEL[nxt[0][1]]} {nxt[0][0]}** ({dday(con, asof, nxt[0][0])})" if nxt else ""
    L.append(f"**현재 단계**: {cur}{nx} · 트랙: {'주주배정(권리락 트랙)' if track == 'RIGHTS' else ('제3자배정' if track == 'THIRD_PARTY' else ('일반공모' if track == 'PUBLIC' else '기타(규칙 미확정·검토 필요)'))}")
    L.append("")
    if d.get("purpose"):
        L.append(f"- **왜**: {d['purpose']}")
    pre = d.get("pre_shares")
    px = d.get("price")
    ph = d.get("price_history") or []
    ini = d.get("initial") or {}
    sz = f"신주 **{d['new_shares']:,}주**" + (f" (증자 전 {pre:,}주 대비 +{d['dilution_pct']}%)" if pre else "")
    if px:
        sz += f" · 발행가 **{px:,}원** ({d.get('price_kind')}) → 조달 **{won(d.get('amount'))}**"
    if d.get("amount_actual"):
        sz += f" · 실제 발행금액 {won(d['amount_actual'])}"
    L.append(f"- **규모**: {sz}")
    if ini and (ini.get("price") != px or ini.get("new_shares") != d["new_shares"]):
        L.append(f"  - 최초 결정({ini['at'][:10]}): 신주 {ini['new_shares']:,}주 × {ini['price']:,}원 = {won(ini['amount'])}")
    if len(ph) > 1:
        L.append("  - 발행가 경과: " + " → ".join(f"{h['price']:,}원({h['kind']} {h['date'][5:]})" for h in ph))
    a = d.get("alloc")
    if a:
        L.append(f"- **구주주 참여**: 1주당 {a['ratio']:.10g}주 배정(≈ {a['shares_per_one_new']}주 보유당 1주) · 100주 보유 시 {100 * a['ratio']:.2f}주 배정, "
                 f"납입 약 {a['per_100_shares_cost']:,}원 · 구주주 배정분 {a['old_holder_shares']:,}주(≈ {won(a['old_holder_amount'])}) + 우리사주 {a['esop_pct']:g}% {a['esop_shares']:,}주 · 실권 시 일반공모")
    ix = d.get("index")
    if ix:
        st = "✅ 반영됨" if ix["effective_date"] and ix["effective_date"] <= asof else "⏳ 예정"
        li = f" · 지수 주식수 {ix['listed_before']:,} → **{ix['index_after']:,}**" if ix.get("index_after") else ""
        L.append(f"- **지수 영향**: {st} — **{ix['effective_date'] or '미정'}**(권리락일 개장 기준가부터)에 **+{ix['delta_shares']:,}주**{li}" if track == "RIGHTS" else
                 f"- **지수 영향**: {st} — **{ix['effective_date'] or '미정'}**(신주 상장일)에 **+{ix['delta_shares']:,}주**{li}")
        L.append(f"  - {ix['why']} · 반영 수량 기준: {ix['basis']}")
        if track == "RIGHTS":
            L.append(f"  - 신주 상장일에는 지수 주식수 추가 변동 없음(이미 반영). 상장 수량이 반영 수량과 다르면(실권·정정) 그때 조정.")
    ck = d.get("rights_listing_check")
    if ck and not ck["ok"]:
        L.append(f"- ⚠ 신주인수권증서 거래기간 점검 필요: 거래일수 {ck['trading_days']}일, 폐지일-마지막거래일 {ck['delist_gap']}영업일 (통상 5일 이상 / 1영업일)")
    # 일정표
    L += ["", "| 일정 | 일자 | D-day(영업일) | 상태 | 근거 |", "|---|---|---|---|---|"]
    rows = sorted(slots.values(), key=lambda r: (r["the_date"], ORDER.index(r["role"]) if r["role"] in ORDER else 99))
    for r in rows:
        if r["role"] not in LABEL:
            continue
        lab = LABEL[r["role"]]
        if r["role"] == "EX_DATE" and track != "RIGHTS":
            continue
        st = "✅" if r["the_date"] <= asof else "⏳"
        if r["is_estimated"]:
            st += " 추정"
        L.append(f"| {'★ ' if r['role'] in KEY else ''}{lab} | {r['the_date']} | {dday(con, asof, r['the_date'])} | {st} | `{r['source_filing_id']}` |")
    if track in ("THIRD_PARTY", "PUBLIC") and "NEW_SHARE_LISTING" not in slots:
        L.append("| ★ 신주 상장 | 미정 | - | ⏳ | 추가상장 공시 대기 |")
    # 청약 결과
    for s in d.get("sub_results") or []:
        L.append("")
        L.append(f"- **청약 결과**({s.get('sub_date')}): 발행예정 {s['planned_shares']:,}주 대비 청약 {s['cumulative']:,}주 (**{s['rate_pct']}%**) · 우리사주 {s['esop']:,} / 구주주(증서) {s['rights_sub']:,} / 초과청약 {s['excess']:,} · 단수주 {s['odd_lot']:,}주 → 일반공모")
    ir = d.get("issue_result")
    if ir:
        L.append(f"- **발행 결과**: 실제 {ir['actual_shares']:,}주 · {won(ir['actual_amount'])} (납입 {ir['payment']})")
    la = d.get("listing_actual")
    if la:
        L.append(f"- **신주 상장**: {la['date']} +{la['shares']:,}주 (`{la['filing']}`)")
    am = d.get("amendments") or []
    if am:
        L += ["", f"<details><summary>정정 이력 {len(am)}회</summary>", ""]
        for x in am:
            ch = "; ".join(fmt_change(k, v[0], v[1]) for k, v in x["changes"].items()) or "(본문 항목 변경 없음)"
            note = (x.get("note") or "").replace("금번 주요사항보고서 정정은 ", "").split("에 따른")[0].split("것이며")[0]
            L.append(f"- {x['at'][:10]} — {(note + ': ') if note.strip() else ''}{ch}")
        L += ["", "</details>"]
    L.append("")
    return L


CXL_LABEL = {"RESOLUTION": "소각 결정(이사회)", "ACQ_START": "자기주식 취득 시작", "ACQ_END": "자기주식 취득 종료(예정)", "CANCEL_DATE": "소각일",
             "CHANGE_LISTING_NOTICE": "변경상장 공시", "CHANGE_LISTING": "변경상장일 = 지수 주식수 감소일"}


def cancel_card(con, e, asof):
    d = json.loads(e["detail_json"] or "{}")
    slots = {r["role"]: r for r in con.execute("SELECT * FROM event_date WHERE event_id=? AND superseded_by IS NULL", (e["event_id"],))}
    L = [f"### {d['issuer']} 자기주식 소각 — {'기취득 자기주식 소각' if d['type'] == 'EXISTING' else '취득 후 소각(진행 중)' if e['status'] != 'done' else '취득 후 소각'}", ""]
    nxt = sorted((v["the_date"], k) for k, v in slots.items() if v["the_date"] > asof)
    nx = f" · 다음: **{CXL_LABEL[nxt[0][1]]} {nxt[0][0]}**{' (추정)' if slots[nxt[0][1]]['is_estimated'] else ''} ({dday(con, asof, nxt[0][0])})" if nxt else ""
    L += [f"**현재 단계**: {d['status_text']}{nx}", ""]
    parts = []
    if d.get("qty_common"):
        parts.append(f"보통주 **{d['qty_common']:,}주**" + (f" (발행 {d['pre_common']:,}주의 {d['pct_common']}%)" if d.get("pct_common") else ""))
    if d.get("qty_pref"):
        parts.append(f"우선주 **{d['qty_pref']:,}주**" + (f" (발행 {d['pre_pref']:,}주의 {d['pct_pref']}%)" if d.get("pct_pref") else ""))
    L.append(f"- **규모**: 소각 " + " · ".join(parts) + (f" · 소각예정금액 {won(d['amount'])}" + (" (장부가 기준)" if d["type"] == "EXISTING" else " (전일 종가 기준 산정 — 실제 수량·금액은 취득 결과로 변동, 정정공시 예정)") if d.get("amount") else ""))
    if d["type"] == "ACQUIRE":
        a = d.get("acquire") or {}
        L.append(f"- **취득 계획**: {d['acq_method']} · 기간 {d['acq_start']} ~ {d['acq_end']} · 위탁 {d.get('broker')}" + (f" · 취득예정 {a['shares']:,}주 / {won(a['amount'])} · 1일 한도 {a['daily_limit']:,}주" if a.get("shares") else "") + " · 취득 완료 후 전량 일괄 소각 (소각예정일 미정)")
    elif d.get("related"):
        L.append("- **취득 이력**: " + ", ".join(f"{x[0]} {x[1]}" for x in d["related"]))
    lst = d.get("listing")
    est = d.get("estimate")
    if lst:
        rows = []
        for r in lst["rows"]:
            nm = con.execute("SELECT name FROM security WHERE security_id=?", (r["security_id"],)).fetchone()[0]
            rows.append(f"{nm} {r['before']:,} → **{r['after']:,}** ({r['delta']:+,})")
        L.append(f"- **지수 영향**: {'✅ 반영됨' if lst['listing_date'] <= asof else '⏳ 예정'} — **{lst['listing_date']}**(변경상장일)에 감소: " + " · ".join(rows) + f". 소각일({lst['cancel_date']})이 아니라 변경상장일 기준.")
    elif est:
        L.append(f"- **지수 영향(예상)**: 변경상장일에 소각 수량만큼 감소 — 추정 **{est['mid']}** (범위 {est['lo']} ~ {est['hi']}; {est['basis']}). 변경상장 공시일 + 3영업일 = 변경상장일(관측 전건 일치)로 공시 후 확정.")
    else:
        q = (d.get("qty_common") or 0) + (d.get("qty_pref") or 0)
        pre = con.execute("SELECT shares_after FROM share_ledger WHERE security_id=? AND superseded_by IS NULL ORDER BY effective_date DESC, ledger_id DESC LIMIT 1", (e["security_id"],)).fetchone()
        proj = f" · 상장주식수 {pre[0]:,} → 약 {pre[0] - q:,} (−{q:,}주, 수량은 예정치)" if pre and q else ""
        L.append(f"- **지수 영향(예상)**: 변경상장일에 감소 — **날짜 미정**(취득 완료 후 소각일 확정 → 변경상장 공시 → +3영업일){proj}")
        if d["type"] == "ACQUIRE" and d.get("acq_end"):
            import m2_cancel
            lg = m2_cancel.lag_stats(con)
            if lg:
                lo, hi = lg["cancel_to_listing"]["min"], lg["cancel_to_listing"]["max"]
                L.append(f"  - 참고(가정): 취득이 예정 종료일({d['acq_end']})에 끝나 같은 날 소각한다면 변경상장일은 약 **{m2_cancel.nth_trading(con, d['acq_end'], lo)} ~ {m2_cancel.nth_trading(con, d['acq_end'], hi)}** (소각일 +{lo}~{hi}영업일, 관측 {lg['n']}건). 취득이 일찍 끝나면 그만큼 앞당겨짐.")
    L += ["", "| 일정 | 일자 | D-day(영업일) | 상태 | 근거 |", "|---|---|---|---|---|"]
    for r in sorted(slots.values(), key=lambda r: (r["the_date"], list(CXL_LABEL).index(r["role"]) if r["role"] in CXL_LABEL else 99)):
        if r["role"] not in CXL_LABEL:
            continue
        st = ("✅" if r["the_date"] <= asof else "⏳") + (" 추정" if r["is_estimated"] else "")
        L.append(f"| {'★ ' if r['role'] == 'CHANGE_LISTING' else ''}{CXL_LABEL[r['role']]} | {r['the_date']} | {dday(con, asof, r['the_date'])} | {st} | `{r['source_filing_id']}` |")
    if d["type"] == "ACQUIRE" and "CANCEL_DATE" not in slots:
        L.append("| 소각일 | 미정 | - | ⏳ | 취득 완료 후 공시 |")
        L.append("| ★ 변경상장일 = 지수 주식수 감소일 | 미정 | - | ⏳ | 소각일 확정 후 |")
    am = d.get("amendments") or []
    if am:
        L += ["", f"<details><summary>정정 이력 {len(am)}회</summary>", ""]
        for x in am:
            L.append(f"- {x['at'][:10]}: " + "; ".join(f"{k}: {v[0]} → {v[1]}" for k, v in x["changes"].items()))
        L += ["", "</details>"]
    L.append("")
    return L


def render_cancel(con, asof, only_active_days=120):
    L = []
    cut = (dt.date.fromisoformat(asof) - dt.timedelta(days=only_active_days)).isoformat()
    n = 0
    for e in con.execute("SELECT * FROM event WHERE event_type='TREASURY_CANCELLATION' ORDER BY created_at").fetchall():
        last = con.execute("SELECT max(the_date) FROM event_date WHERE event_id=? AND superseded_by IS NULL", (e["event_id"],)).fetchone()[0]
        if e["status"] == "done" and last < cut:
            continue
        L += cancel_card(con, e, asof)
        n += 1
    return L or ["(진행 중이거나 최근 완료된 자기주식 소각 없음)"]


CBW_LABEL = {"RESOLUTION": "발행 결정(이사회)", "SUBSCRIPTION": "청약", "PAYMENT": "납입(발행)", "WARRANT_LISTING": "신주인수권증권 상장", "EXERCISE_START": "전환·행사 청구 시작",
             "EXERCISE_END": "전환·행사 청구 종료", "PUT_FIRST": "조기상환청구(풋) 첫 도래", "MATURITY": "만기"}


def cbbw_card(con, e, asof):
    d = json.loads(e["detail_json"] or "{}")
    if d.get("error"):
        return [f"### (오류) {e['thread_key']}: {d['error']}", ""]
    kind = "전환사채(CB)" if d["kind"] == "CB" else "신주인수권부사채(BW)"
    slots = {r["role"]: r for r in con.execute("SELECT * FROM event_date WHERE event_id=? AND superseded_by IS NULL", (e["event_id"],))}
    nm = "전환가액" if d["kind"] == "CB" else "행사가액"
    L = [f"### {d['issuer']} {kind} 제{d['round']}회 — {d['type_text']}", ""]
    st = "전환·행사 완료" if e["status"] == "done" else ("전환·행사 가능 기간" if slots.get("EXERCISE_START") and slots["EXERCISE_START"]["the_date"] <= asof else "발행 후 청구 개시 전")
    L.append(f"**현재 단계**: {st} · 최근 상장: {d['conversions'][-1]['list_date'] + ' +' + format(d['conversions'][-1]['shares'], ',') + '주' if d['conversions'] else '없음'}")
    L.append("")
    L.append(f"- **조건**: 권면 {won(d['face_amount'])} · {nm} **{d['strike']:,}원** → 전환·행사 가능 최대 **{d['potential']:,}주**" + (f" (결정 시 총수 대비 {d['pct_of_total']}%)" if d.get("pct_of_total") else "")
             + f" · 표면 {d['coupon_pct']}% / 만기 {d['ytm_pct']}%" + (f" · 만기상환 {d['maturity_redemption_pct']}%" if d.get("maturity_redemption_pct") else "") + f" · {d['method']}")
    if d.get("refix_floor"):
        L.append(f"- **리픽싱**: 시가 하락 시 조정, 최저 조정가액 {d['refix_floor']:,}원")
    use = d.get("use_of_funds") or {}
    if use:
        L.append("- **자금용도**: " + ", ".join(f"{k} {won(v)}" for k, v in use.items()))
    prog = f"- **전환·행사 현황**: 누적 **{d['converted']:,}주**" + (f" ({d['converted'] / d['potential'] * 100:.1f}%)" if d['potential'] else "") + f" 상장 · 잔여 가능 **{d['remaining']:,}주**"
    if d.get("remaining_amount"):
        prog += f" (≈ {won(d['remaining_amount'])}, 상장주식수의 {d['remaining_pct_of_listed']}%)"
    L.append(prog)
    ck = d.get("check_warrant")
    if ck:
        L.append(f"  - 점검: 최신 신주인수권증권 변경상장 공시의 잔여 {ck['warrant_notice_remaining']:,}증권 = 계산 잔여 {ck['computed_remaining']:,}주 {'✅ 일치' if ck['ok'] else '⚠ 불일치'}")
    off = d.get("official")
    if off and off.get("balance"):
        b = off["balance"]
        L.append(f"  - 공식 행사공시({off['notice_date']}): 미전환 잔액 {won(b['remaining_amount'])} · 전환가능 {b['remaining_shares']:,}주 — 우리 계산 {off.get('computed_remaining_at_notice'):,}주 {'✅ 일치' if off.get('check_ok') else '⚠ 불일치'}; 이후 청구분 {off.get('claimed_after_notice', 0):,}주 반영 시 잔여 {b['remaining_shares'] - off.get('claimed_after_notice', 0):,}주")
    L.append(f"- **지수 영향**: 전환·행사 신주는 **신주 상장일**마다 지수 주식수 +(청구 후 약 2주 뒤 상장). 남은 최대 증가 가능분 {d['remaining']:,}주 (현재 상장주식수 {d['listed_now']:,}주 대비 {d['remaining_pct_of_listed']}%)" if d.get("remaining") else "- **지수 영향**: 전환·행사 완료")
    if d.get("warrant"):
        w = d["warrant"]
        L.append(f"- **신주인수권증권**: {w['instrument']} 상장 {w['list_date']} · {w['count']:,}증권 · 행사가 {w['strike']:,}원 · 행사기간 {w['ex_start']} ~ {w['ex_end']}")
    L += ["", "| 일정 | 일자 | D-day(영업일) | 상태 |", "|---|---|---|---|"]
    for r in sorted(slots.values(), key=lambda r: (r["the_date"], list(CBW_LABEL).index(r["role"]) if r["role"] in CBW_LABEL else 99)):
        if r["role"] in CBW_LABEL:
            L.append(f"| {CBW_LABEL[r['role']]} | {r['the_date']} | {dday(con, asof, r['the_date'])} | {'✅' if r['the_date'] <= asof else '⏳'} |")
    if d["conversions"]:
        # 소량 규칙(사용자 지침 2026-10-10): 1천주 이하는 이력 표에서 생략(누계·잔여에는 반영), 10만주 이하는 가벼운 행으로 유지
        small = [c for c in d["conversions"] if c["shares"] <= 1000]
        L += ["", f"<details><summary>전환·행사 신주 상장 이력 {len(d['conversions'])}건 (지수 주식수 증가일)" + (f" — 1천주 이하 {len(small)}건 표에서 생략" if small else "") + "</summary>", "", "| 상장일(지수 반영) | 청구(발행)일 | 주식수 | 누계 | 잔여 가능 |", "|---|---|---:|---:|---:|"]
        for c in d["conversions"]:
            if c["shares"] <= 1000:
                continue
            det = c.get("issue_date") or ""
            L.append(f"| {c['list_date']} | {det} | {c['shares']:,} | {c['cum']:,} | {c['remaining']:,} |")
        L += ["", "</details>"]
    am = d.get("amendments") or []
    if am:
        L += ["", f"<details><summary>정정·재결정 이력 {len(am)}회</summary>", ""]
        for x in am:
            L.append(f"- {x['at'][:10]}: " + ("; ".join(f"{k}: {v[0]} → {v[1]}" for k, v in x["changes"].items()) or "(주요 항목 변경 없음)"))
        L += ["", "</details>"]
    L.append("")
    return L


def render_cbbw(con, asof, only_active_days=100000):
    L = []
    for e in con.execute("SELECT * FROM event WHERE event_type='CONVERTIBLE_ISSUE' ORDER BY created_at").fetchall():
        d = json.loads(e["detail_json"] or "{}")
        if e["status"] == "done" and not only_active_days:
            continue
        L += cbbw_card(con, e, asof)
    return L or ["(CB·BW 스레드 없음)"]


def render(con, asof, only_active_days=120):
    L = []
    rows = con.execute("SELECT * FROM event WHERE event_type='PAID_CAPITAL_INCREASE' ORDER BY created_at").fetchall()
    cut = (dt.date.fromisoformat(asof) - dt.timedelta(days=only_active_days)).isoformat()
    shown = 0
    for e in rows:
        last = con.execute("SELECT max(the_date) FROM event_date WHERE event_id=? AND superseded_by IS NULL", (e["event_id"],)).fetchone()[0]
        if e["status"] == "done" and last < cut:
            continue
        L += card(con, e, asof)
        shown += 1
    if not shown:
        L.append("(진행 중이거나 최근 완료된 유상증자 없음)")
    return L


if __name__ == "__main__":
    con = db.connect()
    args_ = [a for a in sys.argv[1:] if not a.startswith("--")]
    today = args_[0] if args_ else dt.date.today().isoformat()
    asof = con.execute("SELECT max(cal_date) FROM calendar_day WHERE is_trading=1 AND cal_date<=?", (today,)).fetchone()[0]
    ad = 100000 if "--all" in sys.argv else 120
    L = [f"# 이벤트 스레드 (유상증자 · 자기주식 소각 · CB/BW) — 기준일 {asof}", "", "★ = 지수·참여 핵심일. D-day는 영업일 기준(`*`=휴장일), ✅ 완료 / ⏳ 예정 / 추정 = 기준일로부터 계산한 값.", "", "## 유상증자", ""] + render(con, asof, only_active_days=ad) + ["", "## 자기주식 소각", ""] + render_cancel(con, asof, only_active_days=ad) + ["", "## 전환사채(CB)·신주인수권부사채(BW)", ""] + render_cbbw(con, asof)
    out = os.path.join(db.HERE, "reports", f"m2_rights_issue_{asof}.md")
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))
    print("→", out)
