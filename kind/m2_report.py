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
    L = [f"# 유상증자 이벤트 스레드 — 기준일 {asof}", "", "★ = 지수·참여 관점 핵심일. D-day는 영업일 기준(`*`=휴장일), ✅ 완료 / ⏳ 예정 / 추정 = 기준일로부터 계산한 값.", ""] + render(con, asof, only_active_days=100000 if "--all" in sys.argv else 120)
    out = os.path.join(db.HERE, "reports", f"m2_rights_issue_{asof}.md")
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))
    print("→", out)
