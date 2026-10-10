"""KIND 인덱스 리포트(HTML) — 다가오는 이벤트를 시총 변동 순으로 나열, 선택하면 상세(DART 리포트 양식: 헤더·KPI·핵심 포인트·뉴스 근거·원문 링크 1개).

  .venv/bin/python kind/html_report.py [YYYY-MM-DD]     # 기본: 오늘 이전 마지막 영업일
출력: kind/reports/kind_report_<기준일>.html (단일 파일, 외부 의존 없음)

원칙(사용자 지침 2026-10-10): 주의력은 한정 자원 — 지수 주식수 변동에 직접 관련된 것만 보인다(우선주·우리사주·일반공모·정정 이력·근거 공시 나열은 넣지 않고 DB 에만 둔다).
  · 정렬 = |시총 변동| (변동 주식수 × 기준일 종가, kind/universe/prices_<날짜>.csv)
  · '중요 요소'(지수 주식수 변동·시총 변동·지수 반영일)는 ★ 로 표지
  · 근거는 KIND 원문 링크 하나, '왜'는 kind/news.json 의 한 줄 + 뉴스(없으면 생략)
  · CB/BW 장기 대기는 한 줄 요약만. 종결 건은 맨 뒤(7일 이내만, 없으면 절 자체를 숨김)
"""
import csv
import datetime as dt
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import index_shares
import m2_report as R

HERE = os.path.dirname(os.path.abspath(__file__))
TYPE_KR = {"PAID_CAPITAL_INCREASE": "유상증자", "TREASURY_CANCELLATION": "자기주식 소각", "CONVERTIBLE_ISSUE": "CB/BW", "CORPORATE_SPLIT": "인적분할",
           "BONUS_ISSUE": "무상증자", "STOCK_DIVIDEND": "주식배당", "PAR_SPLIT": "액면분할", "MERGER": "합병"}
KIND_URL = "https://kind.krx.co.kr/common/disclsviewer.do?method=search&acptno="


def load_prices(asof):
    best = None
    for f in glob.glob(os.path.join(HERE, "universe", "prices_*.csv")):
        d = re.search(r"prices_(\d{8})", f).group(1)
        d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        if d <= asof and (best is None or d > best[0]):
            best = (d, f)
    if not best:
        return {}, None
    return {r["code"]: int(r["close"]) for r in csv.DictReader(open(best[1], encoding="utf-8"))}, best[0]


def won(v):
    a = abs(v)
    s = f"{a / 1e12:.2f}조원" if a >= 1e12 else (f"{a / 1e8:,.0f}억원" if a >= 1e8 else f"{a:,.0f}원")
    return ("+" if v > 0 else "−" if v < 0 else "") + s


def sgn(n):
    return ("+" if n > 0 else "−" if n < 0 else "") + f"{abs(n):,}"


def kind_link(con, e):
    """대표 원문 1건: 이벤트 스레드의 결정 공시 중 가장 최근(정정 포함) KIND 공시."""
    r = con.execute("""SELECT f.acpt_no, f.title, f.filed_date FROM event_filing ef JOIN filing f USING(filing_id)
                       WHERE ef.event_id=? AND f.src='KIND' AND f.title LIKE '%결정%' ORDER BY f.filed_at DESC LIMIT 1""", (e["event_id"],)).fetchone()
    if not r:
        r = con.execute("""SELECT f.acpt_no, f.title, f.filed_date FROM event_filing ef JOIN filing f USING(filing_id)
                           WHERE ef.event_id=? AND f.src='KIND' ORDER BY f.filed_at LIMIT 1""", (e["event_id"],)).fetchone()
    return {"url": KIND_URL + r["acpt_no"], "label": f"KIND 공시 원문 — {r['title']} ({r['filed_date']})"} if r else None


def index_of(e, d):
    t = e["event_type"]
    if t == "CONVERTIBLE_ISSUE":
        return None
    if t == "PAID_CAPITAL_INCREASE":
        ix = d.get("index") or {}
        return {"delta": ix.get("delta_shares"), "date": ix.get("effective_date"), "est": ix.get("is_estimated")}
    if t == "TREASURY_CANCELLATION":
        if d.get("listing"):
            return {"delta": sum(r["delta"] for r in d["listing"]["rows"]), "date": d["listing"]["listing_date"], "est": 0}
        q = (d.get("qty_common") or 0) + (d.get("qty_pref") or 0)
        est = d.get("estimate")
        return {"delta": -q if q else None, "date": est["mid"] if est else None, "est": 1}
    if t == "CORPORATE_SPLIT":
        sv = d.get("survivor") or {}
        return {"delta": sum(r["delta"] for r in sv.get("rows", []) if r.get("sec_type") == "COMMON") or None, "date": sv.get("listing_date"), "est": sv.get("is_estimated")}
    ix = d.get("index") or {}
    return {"delta": ix.get("delta_shares"), "date": ix.get("effective_date"), "est": ix.get("is_estimated")}


def facts(con, e, d, asof, slots, ix, news):
    """종류별 헤드라인·4번째 KPI·핵심 포인트·일정(핵심만)."""
    t = e["event_type"]
    s = slots.get
    pts, sched, kpi4, head = [], [], None, ""
    lst_d = (s("NEW_SHARE_LISTING") or s("CHANGE_LISTING") or (None, 0))[0]
    if t == "PAID_CAPITAL_INCREASE":
        n = d["new_shares"]
        head = f"신주 {n:,}주({d['dilution_pct']}%) · 약 {d['amount'] / 1e12:.2f}조원 조달 — {d['method']}"
        kpi4 = {"label": "발행가", "value": f"{d['price']:,}원", "sub": d["price_kind"]}
        ex = s("EX_DATE")
        done = ex and ex[0] <= asof
        pts.append(("key", f"권리락 {ex[0] if ex else '미정'}{' (반영 완료)' if done else ''}: 지수 상장주식수에 +{n:,}주를 선반영, 신주 상장일({lst_d})에 실제 상장 수량으로 확정"))
        for role, label, key in (("EX_DATE", "권리락", True), ("PAYMENT", "납입", False), ("NEW_SHARE_LISTING", "신주 상장", True)):
            if s(role):
                sched.append({"label": label, "date": s(role)[0], "est": s(role)[1], "key": key})
    elif t == "TREASURY_CANCELLATION":
        q = (d.get("qty_common") or 0) + (d.get("qty_pref") or 0)
        if d["type"] == "ACQUIRE":
            head = f"자기주식 {q:,}주({d.get('pct_common')}%) 장내 취득 후 전량 소각 — 예정 {d['amount'] / 1e12:.1f}조원"
            kpi4 = {"label": "취득 기간", "value": f"{d['acq_start'][5:]} ~ {d['acq_end'][5:]}", "sub": d["acq_method"]}
            pts.append(("key", f"소각 후 변경상장일에 지수 상장주식수 −{q:,}주 — 소각일·변경상장일 미정(취득 종료 후 소각 → 변경상장 공시 +3영업일)"))
            pts.append(("info", "수량·금액은 결정 시점 종가 기준 예정치 — 실제 취득 결과에 따라 달라짐"))
            sched.append({"label": "취득 종료(예정)", "date": d["acq_end"], "est": 0, "key": False})
        else:
            head = f"기취득 자기주식 {q:,}주 소각"
            kpi4 = {"label": "소각일", "value": (s("CANCEL_DATE") or ("미정",))[0], "sub": "변경상장일 기준 반영"}
    elif t == "MERGER":
        dc = d["decision"]
        head = f"{dc.get('extinct')} 흡수합병 — 합병신주 {dc['new_shares']:,}주 · 합병비율 1:{dc['ratio']}"
        kpi4 = {"label": "합병비율", "value": f"1 : {dc['ratio']}", "sub": dc.get("form") or "흡수합병"}
        et = d.get("extinct_track") or {}
        pts.append(("key", f"합병신주 상장일 {lst_d}에 지수 상장주식수 +{dc['new_shares']:,}주 — 소멸회사 {dc.get('extinct')} 상장폐지일과 같은 날(과거 합병 2건 동일)"))
        if et.get("halt_est_range"):
            pts.append(("info", f"소멸회사 거래정지 시작 {et['halt_est_range'][0]} ~ {et['halt_est_range'][1]} 예상(신주 상장 16~18영업일 전)"))
        for role, label, key in (("MERGER_DATE", "합병기일", False), ("EXT_HALT_START", f"{dc.get('extinct')} 거래정지(추정)", False), ("NEW_SHARE_LISTING", "신주 상장 = 소멸회사 상장폐지", True)):
            if s(role):
                sched.append({"label": label, "date": s(role)[0], "est": s(role)[1], "key": key})
    elif t == "CONVERTIBLE_ISSUE":
        head = f"{d['kind']} {d['round']}회 — 잔여 전환·행사 가능 {d['remaining']:,}주(상장주식수의 {d['remaining_pct_of_listed']}%)"
        pts.append(("info", f"행사가 {d['strike']:,}원 · 만기 {d['maturity']}" + (f" · 조기상환청구 {d['put_first']}" if d.get("put_first") else "")))
    else:  # 무상증자·주식배당·액면분할·인적분할 (현재 진행 건 없음 — 일반형)
        n = d.get("planned_shares") or 0
        head = f"{TYPE_KR[t]} — {n:,}주"
        pts.append(("key", f"지수 반영일 {(ix or {}).get('date') or '미정'}에 상장주식수 {sgn(n)}주"))
    nw = news.get(e["thread_key"] or "", {})
    if nw.get("why"):
        pts.insert(1 if pts and pts[0][0] == "key" else 0, ("why", nw["why"]))
    if nw.get("risk"):
        pts.append(("risk", nw["risk"]))
    return {"headline": head, "kpi4": kpi4, "points": pts, "sched": sched, "news": nw.get("news", [])}


SCHED_LABEL = {"RESOLUTION": "결정 공시", "PRICE_FIRST_FIXED": "1차 발행가 확정", "EX_DATE": "권리락", "RECORD": "기준일", "PRICE_FINAL_DUE": "최종 발행가 확정(예정)",
               "PAYMENT": "납입", "NEW_SHARE_LISTING": "신주 상장", "CANCEL_DATE": "소각일", "CHANGE_LISTING": "변경상장", "CHANGE_LISTING_NOTICE": "변경상장 공시",
               "EGM": "주주총회", "MERGER_DATE": "합병기일", "REGISTER": "합병등기", "EXT_HALT_START": "소멸회사 거래정지 시작", "HALT_START": "거래정지 시작",
               "EFFECTIVE": "효력발생", "ACQ_START": "자기주식 취득", "SUB_OLD_START": "구주주 청약", "RIGHTS_LIST_START": "신주인수권증서 거래"}
SCHED_PAIR = {"ACQ_START": "ACQ_END", "SUB_OLD_START": "SUB_OLD_END", "RIGHTS_LIST_START": "RIGHTS_LIST_END"}
SCHED_DROP = {"SUB_ESOP", "PUBLIC_OFFER_START", "PUBLIC_OFFER_END", "RIGHTS_DELIST", "ISSUE", "EXT_DELIST", "ACQ_END", "SUB_OLD_END", "RIGHTS_LIST_END", "PRICE_FINAL_FIXED"}
SCHED_KEY = {"EX_DATE", "NEW_SHARE_LISTING", "CHANGE_LISTING"}


def schedule(con, e, slots, asof):
    """일정 전체(우리사주·일반공모·증서 상장폐지·발행일 등 부차 항목만 제외). 시작/종료 쌍은 한 행으로, 지난 일정은 완료 표시."""
    t, rows = e["event_type"], []
    for role, (date, est) in slots.items():
        if role in SCHED_DROP or role not in SCHED_LABEL:
            continue
        label, end = SCHED_LABEL[role], None
        if role in SCHED_PAIR and SCHED_PAIR[role] in slots:
            end = slots[SCHED_PAIR[role]][0]
        if role == "RECORD":
            label = {"MERGER": "주주확정기준일", "PAID_CAPITAL_INCREASE": "신주배정기준일"}.get(t, "기준일")
        if role == "NEW_SHARE_LISTING" and t == "MERGER":
            label = "신주 상장 = 소멸회사 상장폐지"
        if role == "CHANGE_LISTING" and t == "TREASURY_CANCELLATION":
            label = "변경상장 = 지수 주식수 감소"
        if role == "HALT_START":
            continue
        txt = date[5:].replace("-", "/") + (" ~ " + end[5:].replace("-", "/") if end and end != date else "")
        rows.append({"label": label, "sort": date, "date": f"{date[:4]}/{txt}" if date[:4] != asof[:4] or True else txt, "est": est, "key": role in SCHED_KEY,
                     "past": (end or date) <= asof, "dday": R.dday(con, asof, date if date > asof else (end or date)) if (end or date) > asof else ""})
    if t == "TREASURY_CANCELLATION" and "CHANGE_LISTING" not in slots:
        rows.append({"label": "소각일 → 변경상장 = 지수 주식수 감소", "sort": "9999", "date": "미정", "est": 0, "key": True, "past": False, "dday": ""})
    rows.sort(key=lambda r: r["sort"])
    return rows


def build(con, asof):
    prices, price_date = load_prices(asof)
    news = json.load(open(os.path.join(HERE, "news.json"), encoding="utf-8"))
    news = {k: v for k, v in news.items() if not k.startswith("_")}
    week_ago = (dt.date.fromisoformat(asof) - dt.timedelta(days=7)).isoformat()
    events, cbw, done = [], [], []
    types = ",".join("?" * len(TYPE_KR))
    for e in con.execute(f"SELECT * FROM event WHERE event_type IN ({types}) ORDER BY created_at", tuple(TYPE_KR)).fetchall():
        d = json.loads(e["detail_json"] or "{}")
        if e["event_type"] == "MERGER" and not d.get("planned_shares") and not d.get("actual_shares"):
            continue
        sec = con.execute("SELECT security_id, sec_type FROM security WHERE security_id=?", (e["security_id"],)).fetchone() if e["security_id"] else None
        if sec and sec["sec_type"] == "PREFERRED":
            continue  # 우선주는 다루지 않는다
        sid = sec["security_id"] if sec else con.execute("SELECT security_id FROM security WHERE issuer_id=? AND sec_type='COMMON' ORDER BY security_id LIMIT 1", (e["issuer_id"],)).fetchone()[0]
        code = con.execute("SELECT code FROM security_code WHERE security_id=? AND code_type='SHORT'", (sid,)).fetchone()
        code = code[0] if code else ""
        iss = con.execute("SELECT name FROM issuer WHERE issuer_id=?", (e["issuer_id"],)).fetchone()[0]
        slots = {r["role"]: (r["the_date"], r["is_estimated"]) for r in con.execute("SELECT role, the_date, is_estimated FROM event_date WHERE event_id=? AND superseded_by IS NULL", (e["event_id"],))}
        last = max((v[0] for v in slots.values()), default=None)
        if e["status"] == "done":
            if last and last >= week_ago:
                done.append({"issuer": iss, "code": code, "type": TYPE_KR[e["event_type"]], "date": last, "link": kind_link(con, e)})
            continue
        ix = index_of(e, d)
        listed = index_shares.listed_shares(con, sid, asof)
        f = facts(con, e, d, asof, slots, ix, news)
        f["sched"] = schedule(con, e, slots, asof) if e["event_type"] != "CONVERTIBLE_ISSUE" else []
        base = {"id": e["event_id"], "issuer": iss, "code": code, "type": TYPE_KR[e["event_type"]], **f, "link": kind_link(con, e)}
        if e["event_type"] == "CONVERTIBLE_ISSUE":
            base["type"] = f"{d['kind']} {d['round']}회"
            base["sort"] = d["remaining_pct_of_listed"]
            base["line"] = f"잔여 {d['remaining']:,}주 · 상장주식수의 {d['remaining_pct_of_listed']}%"
            base["nextkey"] = f"만기 {d['maturity']}" + (f" · 조기상환청구 {d['put_first']}" if d.get("put_first") and d["put_first"] > asof else "")
            cbw.append(base)
            continue
        delta = (ix or {}).get("delta")
        price = prices.get(code)
        mc = delta * price if (delta is not None and price) else None
        applied = bool(ix and ix["date"] and ix["date"] <= asof)
        base.update({"delta": delta, "date": ix["date"] if ix else None, "est": (ix or {}).get("est"), "applied": applied,
                     "dday": R.dday(con, asof, ix["date"]) if ix and ix["date"] else None, "price": price, "mc": mc,
                     "mc_txt": won(mc) if mc is not None else None, "pct": round(delta / listed * 100, 2) if (delta is not None and listed) else None,
                     "delta_txt": sgn(delta) if delta is not None else None, "listed": listed})
        events.append(base)
    events.sort(key=lambda x: -abs(x["mc"] or 0))
    mx = max((abs(x["mc"] or 0) for x in events), default=1) or 1
    for x in events:
        x["bar"] = round(abs(x["mc"] or 0) / mx * 100) if x["mc"] else 0
    cbw.sort(key=lambda x: -x["sort"])
    return {"asof": asof, "price_date": price_date, "events": events, "cbw": cbw, "done": done, "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}


TEMPLATE = open(os.path.join(HERE, "html_report_template.html"), encoding="utf-8").read()


def main():
    con = db.connect()
    today = sys.argv[1] if len(sys.argv) > 1 else dt.date.today().isoformat()
    asof = con.execute("SELECT max(cal_date) FROM calendar_day WHERE is_trading=1 AND cal_date<=?", (today,)).fetchone()[0]
    data = build(con, asof)
    html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/"))
    out = os.path.join(db.HERE, "reports", f"kind_report_{asof}.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write(html)
    print(out, f"events={len(data['events'])} cbw={len(data['cbw'])} done7d={len(data['done'])} price_date={data['price_date']}")


if __name__ == "__main__":
    main()
