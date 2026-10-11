"""M2 — 유상증자 이벤트 스레드.

한 번의 유상증자(결정 → 정정들 → 발행가 확정 → 권리락 → 신주인수권증서 상장 → 청약 → 납입 → 신주 상장)를 하나의 event(thread)로 묶는다.
스레드 키: 'PCI:<issuer_id>:<최초 결정일>:<R|T|P|O 방식>'  (정정공시는 '정정대상 공시서류의 최초제출일'로 원 스레드에 붙는다)

트랙
  RIGHTS       주주배정 / 주주배정후 실권주 일반공모 / 주주우선공모  → 지수 주식수 증가일 = 권리락일 (= 신주배정기준일 직전 영업일, T+2 결제 기준; 권리락 공시로 확정)
  THIRD_PARTY  제3자배정                                        → 지수 주식수 증가일 = 신주 상장일
  PUBLIC/OTHER 일반공모 등                                      → 신주 상장일로 두되 review_flag (규칙 미확정)

재생(replay) 방식: 스레드에 속한 공시를 시간순으로 적용해 날짜 슬롯(event_date)을 갱신한다. 값이 바뀌면 이전 값은 superseded_by 로 보존,
정정으로 삭제된 날짜(예: '일정 미정')는 superseded_by = 자기 자신(철회 표시)으로 남긴다. 재실행 시 같은 event_id 로 전부 재구성한다(멱등).

  .venv/bin/python kind/m2_rights_issue.py [--asof YYYY-MM-DD] [--no-network]
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import kind_client as kc
from common import cal, ex_from_record, kdate, link_filing, prune, set_slot, tdiff, text_of
from m2_decision import parse_decision, split_items, toks, num

NOW = lambda: dt.datetime.now().isoformat(timespec="seconds")
FOLLOW_TITLES = ("유상증자 신주발행가액", "신주인수권증서 신규상장", "유상증자 또는 주식관련사채 등의 청약결과", "유상증자 또는 주식관련사채 등의 발행결과")
RIGHTS_METHODS = ("주주배정", "주주우선공모")
DATE_RX = r"(\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일|\d{4}-\d{2}-\d{2})"


# ───────────── 후속 공시 파서 ─────────────
def items_of(text):
    return {l: v for l, v in split_items(toks(text)).values()}


def first_val(it, key):
    for l, v in it.items():
        if key in l:
            return v
    return []


def p_price_notice(text):
    it = items_of(text)
    kind = (first_val(it, "구분") or [""])[0] if any("구분" in l for l in it) else ""
    price = num(next((x for x in first_val(it, "주당 발행가액") if re.fullmatch(r"[\d,]+", x)), None))
    flat = re.sub(r"\s+", " ", text)
    m = re.search(r"확정 발행가액은[^.]*?" + DATE_RX + r"에 공시", flat)
    return {"kind": "FINAL" if "확정" in kind and "신주배정기준일" not in kind else "FIRST", "label": kind, "price": price,
            "final_notice_due": kdate(m.group(1)) if m else None}


def p_rights_listing(text):
    it = {}
    for line in text.split("\n"):
        m = re.match(r"\s*(\d)\.\s*([^:]+?)\s*:\s*(.+)$", line)
        if m:
            it[m.group(2).strip()] = m.group(3).strip()
    g = lambda k: next((v for l, v in it.items() if k in l), None)
    cnt = re.search(r"([\d,]+)\s*증서", g("신주인수권 증서의 수") or "")
    return {"list_date": kdate(g("상장일")), "delist_date": kdate(g("상장폐지일")), "rights_count": num(cnt.group(1)) if cnt else None,
            "price_expected": num((g("발행가액") or "").replace("원", "")), "sub_start": kdate(g("청약개시일")), "sub_end": kdate(g("청약종료일")),
            "instrument": g("상장종목")}


def p_sub_result(text):
    flat = re.sub(r"\s+", " ", text)
    d = {}
    for key, rx in (("planned_shares", r"발행예정주식수\(주\)\s*\|?\s*([\d,]+)"), ("subscribed", r"해당 청약주식수\(주\)\s*\|?\s*([\d,]+)"),
                    ("cumulative", r"청약주식수\(누계\)\(주\)\s*\|?\s*([\d,]+)"), ("rate_pct", r"청약률\(%\)\s*\|?\s*([\d.]+)"),
                    ("esop", r"우리사주조합 청약 주식수\s*:\s*([\d,]+)"), ("rights_sub", r"신주인수권증서 청약 주식수\s*:\s*([\d,]+)"),
                    ("excess", r"초과청약 주식수\s*:\s*([\d,]+)"), ("odd_lot", r"단수주\s*:\s*([\d,]+)")):
        m = re.search(rx, flat)
        d[key] = num(m.group(1)) if m else None
    m = re.search(r"청약일자\s*\|?\s*" + DATE_RX, flat)
    d["sub_date"] = kdate(m.group(1)) if m else None
    m = re.search(r"일반공모 청약일\s*:\s*" + DATE_RX + r"\s*(?:및|~|,)\s*" + DATE_RX, flat)
    d["public_offer"] = (kdate(m.group(1)), kdate(m.group(2))) if m else None
    for key, rx in (("payment", r"주금 납입일\s*:\s*" + DATE_RX), ("listing", r"신주 상장\(유통\)예정일\s*:\s*" + DATE_RX)):
        m = re.search(rx, flat)
        d[key] = kdate(m.group(1)) if m else None
    return d


def p_issue_result(text):
    flat = re.sub(r"\s+", " ", text)
    d = {}
    for key, rx in (("planned_shares", r"발행예정주식수\(주\)\s*\|?\s*([\d,]+)"), ("planned_amount", r"발행예정금액\(원\)\s*\|?\s*([\d,]+)"),
                    ("actual_shares", r"실제발행주식수\(주\)\s*\|?\s*([\d,]+)"), ("actual_amount", r"실제발행금액\(원\)\s*\|?\s*([\d,]+)")):
        m = re.search(rx, flat)
        d[key] = num(m.group(1)) if m else None
    m = re.search(r"납입일\s*\|?\s*" + DATE_RX, flat)
    d["payment"] = kdate(m.group(1)) if m else None
    m = re.search(r"신주 상장 예정일\s*:\s*" + DATE_RX, flat)
    d["listing"] = kdate(m.group(1)) if m else None
    return d


def p_prospectus(text):
    flat = re.sub(r"\s+", " ", text)
    m = re.search(r"상장기간은\s*" + DATE_RX + r"\s*부터\s*" + DATE_RX + r"\s*까지", flat)
    dl = re.search(r"신주인수권증서는\s*" + DATE_RX + r"에 상장폐지될 예정", flat)
    return {"list_start": kdate(m.group(1)) if m else None, "list_end": kdate(m.group(2)) if m else None, "delist": kdate(dl.group(1)) if dl else None}


# ───────────── 목적 한 줄 ─────────────
def purpose_line(con, issuer_id, decision, filed_date):
    use = decision.get("use_of_funds") or {}
    if not use:
        return None
    total = sum(use.values())
    big, amt = max(use.items(), key=lambda kv: kv[1])
    share = amt / total * 100
    fmt = lambda v: f"{v / 1e12:.2f}조원" if v >= 1e12 else f"{v / 1e8:,.0f}억원"
    parts = " · ".join(f"{k} {fmt(v)}({v / total * 100:.0f}%)" for k, v in sorted(use.items(), key=lambda kv: -kv[1]))
    line = parts
    if "타법인" in big:  # 같은 시기의 타법인 양수/취득결정에서 대상 회사 확인
        lo = (dt.date.fromisoformat(filed_date) - dt.timedelta(days=60)).isoformat()
        for r in con.execute("""SELECT body_path, title, filed_date FROM filing WHERE issuer_id=? AND title LIKE '타법인 주식 및 출자증권 %결정%' AND title NOT LIKE '%종속회사%'
                                AND body_path IS NOT NULL AND filed_date BETWEEN ? AND ? ORDER BY filed_date DESC""", (issuer_id, lo, (dt.date.fromisoformat(filed_date) + dt.timedelta(days=3)).isoformat())):
            t = kc._html_to_text(open(os.path.join(db.HERE, r["body_path"]), encoding="utf-8").read())
            t = re.sub(r"\s+", " ", t)
            a = re.search(r"(?:양수|취득)금액\(원\)\(A\)\s*\|?\s*([\d,]+)", t)
            if not a or abs(num(a.group(1)) - amt) / amt > 0.05:
                continue
            nm = re.search(r"회사명\s*\|\s*([^|]+)\|", t)
            ctry = re.search(r"국적\s*\|\s*([^|]+)\|", t)
            biz = re.search(r"주요사업\s*\|\s*([^|]+)\|", t)
            pct = re.search(r"지분비율\(%\)\s*\|\s*([\d.]+)", t)
            goal = re.search(r"(?:양수|취득)목적\s*\|\s*([^|]+)\|", t)
            line = (f"{big} {fmt(amt)}({share:.0f}%) — {nm.group(1).strip() if nm else '타법인'}"
                    f"({(ctry.group(1).strip() + ', ') if ctry else ''}{biz.group(1).strip() if biz else ''}) "
                    f"지분 {pct.group(1) + '% ' if pct else ''}취득 자금" + (f" · 목적: {goal.group(1).strip()}" if goal else "") + f" [{r['title']} {r['filed_date']}]")
            if len(use) > 1:
                line += " · 기타: " + ", ".join(f"{k} {fmt(v)}" for k, v in use.items() if k != big)
            break
    return line


# ───────────── 스레드 구성 ─────────────
def load_threads(con):
    th = {}
    rows = con.execute("""SELECT f.*, s.issuer_id AS iss FROM filing f JOIN security s USING(security_id)
                          WHERE f.src='KIND' AND f.title='유상증자결정' AND f.body_path IS NOT NULL ORDER BY f.filed_at""").fetchall()
    for f in rows:
        d = parse_decision(re.sub(r"[ \t]+", " ", text_of(f)))
        if d is None:
            con.execute("UPDATE filing SET parse_status='review', skip_reason='decision_parse' WHERE filing_id=?", (f["filing_id"],))
            continue
        acpt_d = f["acpt_no"][:4] + "-" + f["acpt_no"][4:6] + "-" + f["acpt_no"][6:8]  # 접수번호의 날짜 = 최초제출일(시간외 접수는 목록 일시가 다음 영업일이라 filed_date 와 다를 수 있다)
        key_date = d["amend_of"] or acpt_d
        tr = track_of(d["method"])
        # 같은 날 서로 다른 증자(예: 제3자배정 + 주주배정 후 실권주 공모)가 같은 '최초제출일'로 정정되는 경우가 있어 방식을 키에 넣는다.
        # 같은 방식의 후속(정정) 공시는 같은 스레드에서 시간순으로 앞 값을 덮어쓴다(가장 최근 공시가 현재 값).
        key = f"PCI:{f['iss']}:{key_date}:{ {'RIGHTS': 'R', 'THIRD_PARTY': 'T', 'PUBLIC': 'P'}.get(tr, 'O') }"
        t = th.setdefault(key, {"key": key, "issuer_id": f["iss"], "security_id": f["security_id"], "start": f["filed_at"], "start_date": key_date, "track": tr, "items": []})
        t["items"].append((f["filed_at"], "DECISION", f, d))
    return th


def attach_follow(con, th):
    """후속 공시를 (같은 법인) 직전에 시작된 스레드에 붙인다."""
    by_issuer = {}
    for t in th.values():
        by_issuer.setdefault(t["issuer_id"], []).append(t)
    for l in by_issuer.values():
        l.sort(key=lambda t: t["start"])
    q = """SELECT f.*, s.issuer_id AS iss FROM filing f JOIN security s USING(security_id) WHERE f.src='KIND' AND f.body_path IS NOT NULL
           AND (""" + " OR ".join(["f.title LIKE ?"] * (len(FOLLOW_TITLES) + 2)) + ") ORDER BY f.filed_at"
    args = [t + "%" for t in FOLLOW_TITLES] + ["추가상장(유상증자%", "권리락 기준가격 안내%"]
    for f in con.execute(q, args).fetchall():
        cands = [t for t in by_issuer.get(f["iss"], []) if t["start"] <= f["filed_at"]]
        if not cands:
            continue
        title = f["title"]
        rights_only = title.startswith(("유상증자 신주발행가액", "신주인수권증서 신규상장", "권리락 기준가격 안내")) or "청약결과" in title
        rc = [c for c in cands if c.get("track") == "RIGHTS"]
        t = (rc[-1] if rc else cands[-1]) if rights_only else cands[-1]
        if title.startswith("유상증자 신주발행가액"):
            t["items"].append((f["filed_at"], "PRICE_NOTICE", f, p_price_notice(text_of(f))))
        elif title.startswith("신주인수권증서 신규상장"):
            t["items"].append((f["filed_at"], "RIGHTS_LISTING", f, p_rights_listing(text_of(f))))
        elif "청약결과" in title:
            t["items"].append((f["filed_at"], "SUB_RESULT", f, p_sub_result(text_of(f))))
        elif "발행결과" in title:
            t["items"].append((f["filed_at"], "ISSUE_RESULT", f, p_issue_result(text_of(f))))
        elif title.startswith("추가상장(유상증자"):
            lg = con.execute("SELECT * FROM share_ledger WHERE source_filing_id=? ORDER BY ledger_id", (f["filing_id"],)).fetchall()
            # 같은 법인에 증자가 여러 건이면 '직전 스레드'가 아니라 계획 신주수가 가장 가까운 미매칭 스레드에 붙인다
            dl = sum((x["delta_shares"] or 0) for x in lg)
            plan = lambda c: next(((i[3]["new_shares"] or 0) for i in reversed(c["items"]) if i[1] == "DECISION"), 0)
            pool = [c for c in cands if not c.get("listed")] or cands
            t = min(pool, key=lambda c: abs(plan(c) - dl) / (plan(c) or 1)) if dl else cands[-1]
            t["listed"] = True
            t["items"].append((f["filed_at"], "NEW_LISTING", f, [dict(x) for x in lg]))
        elif title.startswith("권리락 기준가격 안내"):
            r = con.execute("""SELECT e.event_id, e.security_id, e.detail_json, d.the_date FROM event e JOIN event_filing ef USING(event_id)
                               JOIN event_date d ON d.event_id=e.event_id AND d.role='EX_DATE' AND d.superseded_by IS NULL
                               WHERE ef.filing_id=? AND e.event_type='RIGHTS_EX'""", (f["filing_id"],)).fetchone()
            if r and "유상증자" in (json.loads(r["detail_json"] or "{}").get("reason") or ""):
                t["items"].append((f["filed_at"], "EX_NOTICE", f, {"ex_date": r["the_date"], "security_id": r["security_id"], "detail": json.loads(r["detail_json"])}))
    for t in th.values():
        t["items"].sort(key=lambda x: x[0])


def track_of(method):
    """지수 반영 규칙(사용자 확정): 주주배정류 → 권리락일 / 제3자배정·일반공모 → 신주 상장일 / 그 외 → 검토."""
    m = method or ""
    if any(k in m for k in RIGHTS_METHODS):
        return "RIGHTS"
    if "제3자" in m:
        return "THIRD_PARTY"
    if "일반공모" in m or m.strip() in ("공모", "공모증자"):
        return "PUBLIC"
    return "OTHER"


def replay(con, t, asof, network=True):
    key = t["key"]
    ev = con.execute("SELECT event_id FROM event WHERE thread_key=?", (key,)).fetchone()
    if ev:
        eid = ev[0]
        con.execute("DELETE FROM index_share_adj WHERE event_id=?", (eid,))
        con.execute("DELETE FROM event_date WHERE event_id=?", (eid,))  # self-reference 포함 전부 재구성
        con.execute("DELETE FROM event_filing WHERE event_id=?", (eid,))
    else:
        eid = con.execute("""INSERT INTO event(issuer_id,security_id,event_type,status,title,created_at,updated_at,thread_key)
                             VALUES (?,?,'PAID_CAPITAL_INCREASE','confirmed','유상증자',?,?,?)""", (t["issuer_id"], t["security_id"], NOW(), NOW(), key)).lastrowid
    S = {"amendments": [], "price_history": [], "sources": [], "sub_results": [], "track": None, "method": None}
    prev = None
    first_decision = True
    for at, kind, f, p in t["items"]:
        fid = f["filing_id"]
        link_filing(con, eid, f, kind == "DECISION", first_decision, S)
        if kind == "DECISION":
            d = p
            S["method"], S["track"] = d["method"], track_of(d["method"])
            if first_decision:
                set_slot(con, eid, "RESOLUTION", d["board_date"] or f["filed_date"] if not d["amend_of"] else d["amend_of"], 0, fid)
            for role, val in (("RECORD", d["record_date"]), ("SUB_ESOP", d["subscription"].get("우리사주조합_start")),
                              ("SUB_OLD_START", d["subscription"].get("구주주_start")), ("SUB_OLD_END", d["subscription"].get("구주주_end")),
                              ("PUBLIC_OFFER_START", (d["public_offer"] or (None, None))[0]), ("PUBLIC_OFFER_END", (d["public_offer"] or (None, None))[1]),
                              ("PRICE_FINAL_DUE", d["price_confirm_due"]), ("PAYMENT", d["payment_date"]), ("NEW_SHARE_LISTING", d["listing_date"])):
                if S["track"] != "RIGHTS" and role not in ("PAYMENT", "NEW_SHARE_LISTING"):
                    continue
                if role == "NEW_SHARE_LISTING" and any(i[1] == "NEW_LISTING" and i[0] <= at for i in t["items"]):
                    continue
                set_slot(con, eid, role, val, 0, fid)
            if S["track"] == "RIGHTS":
                cur_ex = con.execute("SELECT is_estimated FROM event_date WHERE event_id=? AND role='EX_DATE' AND superseded_by IS NULL", (eid,)).fetchone()
                if not (cur_ex and cur_ex[0] == 0):  # 권리락 공시로 확정된 날짜는 계산값(추정)으로 덮어쓰지 않는다
                    set_slot(con, eid, "EX_DATE", ex_from_record(con, d["record_date"]) if d["record_date"] else None, 1, fid)
            px = d["price_confirmed"] or d["price_expected"]
            if px:
                S["price_history"].append({"date": f["filed_date"], "kind": "확정" if d["price_confirmed"] else "예정", "price": px, "filing": fid})
            if prev:
                ch = {}
                for k_ in ("new_shares", "price_expected", "price_confirmed", "record_date", "payment_date", "listing_date", "alloc_ratio", "method", "esop_pct"):
                    if prev.get(k_) != d.get(k_):
                        ch[k_] = [prev.get(k_), d.get(k_)]
                if prev.get("use_of_funds") != d.get("use_of_funds"):
                    ch["use_of_funds"] = [prev.get("use_of_funds"), d.get("use_of_funds")]
                for k_ in ("subscription", "public_offer"):
                    if prev.get(k_) != d.get(k_):
                        ch[k_] = [prev.get(k_), d.get(k_)]
                S["amendments"].append({"filing": fid, "at": f["filed_at"], "note": d["amend_note"], "changes": ch})
            else:
                S["initial"] = {"filing": fid, "at": f["filed_at"], "new_shares": d["new_shares"], "price": px, "amount": (d["new_shares"] or 0) * (px or 0)}
            S["decision"] = d
            prev = d
            first_decision = False
        elif kind == "PRICE_NOTICE":
            S["price_history"].append({"date": f["filed_date"], "kind": "1차 확정" if p["kind"] == "FIRST" else "최종 확정", "price": p["price"], "filing": fid})
            set_slot(con, eid, "PRICE_FIRST_FIXED" if p["kind"] == "FIRST" else "PRICE_FINAL_FIXED", f["filed_date"], 0, fid)
            if p["final_notice_due"]:
                set_slot(con, eid, "PRICE_FINAL_DUE", p["final_notice_due"], 0, fid)
            S["price_" + p["kind"].lower()] = p["price"]
        elif kind == "EX_NOTICE":
            set_slot(con, eid, "EX_DATE", p["ex_date"], 0, fid)
            S.setdefault("ex_notice", []).append({"filing": fid, "date": p["ex_date"], "prices": p["detail"].get("prices")})
        elif kind == "RIGHTS_LISTING":
            set_slot(con, eid, "RIGHTS_LIST_START", p["list_date"], 0, fid)
            if p["delist_date"]:
                set_slot(con, eid, "RIGHTS_LIST_END", cal(con, p["delist_date"], "prev_trading_date"), 0, fid)
                set_slot(con, eid, "RIGHTS_DELIST", p["delist_date"], 0, fid)
            set_slot(con, eid, "SUB_OLD_START", p["sub_start"] or None, 0, fid) if p["sub_start"] else None
            set_slot(con, eid, "SUB_OLD_END", p["sub_end"] or None, 0, fid) if p["sub_end"] else None
            S["rights_listing"] = {k_: v for k_, v in p.items()}
        elif kind == "SUB_RESULT":
            S["sub_results"].append({"filing": fid, **p})
            if p["public_offer"]:
                set_slot(con, eid, "PUBLIC_OFFER_START", p["public_offer"][0], 0, fid)
                set_slot(con, eid, "PUBLIC_OFFER_END", p["public_offer"][1], 0, fid)
            if p["payment"]:
                set_slot(con, eid, "PAYMENT", p["payment"], 0, fid)
            if p["listing"]:
                set_slot(con, eid, "NEW_SHARE_LISTING", p["listing"], 0, fid)
        elif kind == "ISSUE_RESULT":
            S["issue_result"] = {"filing": fid, **p}
            if p["payment"]:
                set_slot(con, eid, "PAYMENT", p["payment"], 0, fid)
            if p["listing"]:
                set_slot(con, eid, "NEW_SHARE_LISTING", p["listing"], 0, fid)
        elif kind == "NEW_LISTING":
            for lg in p:
                if lg["security_id"] == t["security_id"]:
                    set_slot(con, eid, "NEW_SHARE_LISTING", lg["effective_date"], 0, fid)
                    if lg["issue_date"]:
                        set_slot(con, eid, "ISSUE", lg["issue_date"], 0, fid)
                    S["listing_actual"] = {"filing": fid, "shares": lg["delta_shares"], "date": lg["effective_date"], "ledger_id": lg["ledger_id"]}
                    con.execute("UPDATE share_ledger SET event_id=? WHERE ledger_id=?", (eid, lg["ledger_id"]))
    return eid, S


def fetch_prospectus(con, t, eid, S, asof):
    """증권신고서/투자설명서는 수집 범위(수시·시장조치) 밖이라, 신주인수권증서 거래기간이 필요할 때만 온디맨드로 읽는다."""
    d = S.get("decision") or {}
    if S["track"] != "RIGHTS" or d.get("rights_listed") != "예":
        return
    if con.execute("SELECT 1 FROM event_date WHERE event_id=? AND role='RIGHTS_LIST_START' AND superseded_by IS NULL", (eid,)).fetchone():
        return
    codes, mj = kc.filing_type_codes()
    sub = "|".join(c for c, _ in codes["07"]) + "|"
    code = con.execute("SELECT code FROM security_code WHERE security_id=? AND code_type='SHORT'", (t["security_id"],)).fetchone()[0]
    lo = t["start_date"]
    hi = (dt.date.fromisoformat(lo) + dt.timedelta(days=200)).isoformat()
    rows = kc.list_filings(code=code, frm=lo, to=min(hi, asof if asof > lo else hi), disclosureType07=sub, pDisclosureType07=sub)
    cand = sorted([r for r in rows if r["title"] == "투자설명서"], key=lambda r: r["datetime"], reverse=True)
    for r in cand[:2]:
        fid = "KIND:" + r["acpt_no"]
        con.execute("""INSERT OR IGNORE INTO filing(filing_id,src,acpt_no,filed_at,filed_date,issuer_id,security_id,company_raw,title,cat_major,skip_reason,parse_status)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (fid, "KIND", r["acpt_no"], r["datetime"], r["datetime"][:10], t["issuer_id"], t["security_id"], r["company"], r["title"], "발행공시", "m2_on_demand", "skipped"))
        txt = kc.body_text(r["acpt_no"])
        pp = p_prospectus(txt)
        con.execute("INSERT OR IGNORE INTO event_filing VALUES (?,?,?)", (eid, fid, "reference"))
        if pp["list_start"]:
            set_slot(con, eid, "RIGHTS_LIST_START", pp["list_start"], 0, fid)
            set_slot(con, eid, "RIGHTS_LIST_END", pp["list_end"], 0, fid)
            if pp["delist"]:
                set_slot(con, eid, "RIGHTS_DELIST", pp["delist"], 0, fid)
            S["rights_listing"] = {"source": "투자설명서(예정)", "list_date": pp["list_start"], "list_end": pp["list_end"], "delist_date": pp["delist"]}
            S["sources"].append({"filing": fid, "at": r["datetime"], "title": "투자설명서 (온디맨드)"})
            return


def listed_as_of(con, sid, d, exclude_event):
    """상장주식수(원장) as-of d: d 이전 마지막 행의 after, 없으면 d 이후 첫 행의 before(시드 행이면 after)."""
    r = con.execute("""SELECT shares_after FROM share_ledger WHERE security_id=? AND superseded_by IS NULL AND effective_date<=? AND (event_id IS NOT ?) AND shares_after IS NOT NULL
                       ORDER BY effective_date DESC, ledger_id DESC LIMIT 1""", (sid, d, exclude_event)).fetchone()
    if r:
        return r[0]
    r = con.execute("""SELECT reason, shares_before, shares_after FROM share_ledger WHERE security_id=? AND superseded_by IS NULL AND effective_date>? ORDER BY effective_date, ledger_id LIMIT 1""", (sid, d)).fetchone()
    if r:
        return r["shares_after"] if r["reason"].startswith("SEED:") else r["shares_before"]
    return None


def compact_prices(h):
    """같은 날짜는 공시 성격이 분명한 항목(1차/최종 확정)을 우선, 연속된 같은 가격은 한 번만."""
    rank = lambda x: 0 if "확정" in x["kind"] and x["kind"] != "확정" else 1
    out = []
    for x in sorted(h, key=lambda x: (x["date"], rank(x))):
        if out and out[-1]["date"] == x["date"]:
            continue
        if out and out[-1]["price"] == x["price"] and out[-1]["kind"][:2] == x["kind"][:2]:
            continue
        out.append(x)
    return out


def finalize(con, t, eid, S, asof):
    d = S.get("decision")
    if not d:
        return
    cur = {r["role"]: r["the_date"] for r in con.execute("SELECT role, the_date FROM event_date WHERE event_id=? AND superseded_by IS NULL", (eid,))}
    track = S["track"]
    iss = con.execute("SELECT issuer_id FROM security WHERE security_id=?", (t["security_id"],)).fetchone()[0]
    new_sh = (S.get("issue_result") or {}).get("actual_shares") or d["new_shares"]
    price = S.get("price_final") or d["price_confirmed"] or S.get("price_first") or d["price_expected"]
    price_kind = "최종 확정" if (S.get("price_final") or d["price_confirmed"]) else ("1차 확정(최종 확정 전)" if S.get("price_first") else "예정")
    if S.get("listing_actual") and price_kind == "예정":
        price_kind = "발행 완료 기준(정정 공시 최종값)"
    amount = new_sh * price if new_sh and price else None
    fsum = sum((d["use_of_funds"] or {}).values())
    amount_check = None if not (amount and fsum) else {"amount": amount, "funds_sum": fsum, "match": abs(amount - fsum) / fsum < 0.001}
    out = {"method": d["method"], "track": track, "new_shares": new_sh, "new_shares_decision": d["new_shares"], "pre_shares": d["pre_shares"],
           "dilution_pct": round(d["new_shares"] / d["pre_shares"] * 100, 2) if d["pre_shares"] and d["new_shares"] else None,
           "price": price, "price_kind": price_kind, "amount": amount, "amount_check": amount_check, "amount_actual": (S.get("issue_result") or {}).get("actual_amount"),
           "use_of_funds": d["use_of_funds"], "purpose": purpose_line(con, iss, d, t["start_date"]), "par": d["par"],
           "price_history": compact_prices(S["price_history"]), "amendments": S["amendments"], "initial": S.get("initial"), "sub_results": S["sub_results"],
           "rights_listing": S.get("rights_listing"), "issue_result": S.get("issue_result"), "ex_notice": S.get("ex_notice"), "listing_actual": S.get("listing_actual"),
           "lead_underwriters": d["lead_underwriters"], "shortsale_ban": d.get("shortsale_ban"), "sources": S["sources"]}
    if track == "RIGHTS" and d["alloc_ratio"]:
        esop = int(new_sh * (d["esop_pct"] or 0) / 100)
        old = new_sh - esop
        out["alloc"] = {"ratio": d["alloc_ratio"], "shares_per_one_new": round(1 / d["alloc_ratio"], 2), "esop_pct": d["esop_pct"], "esop_shares": esop,
                        "old_holder_shares": old, "old_holder_amount": old * price if price else None, "per_100_shares_cost": round(100 * d["alloc_ratio"] * price) if price else None}
    if cur.get("RIGHTS_LIST_START") and cur.get("RIGHTS_LIST_END"):  # 증서 거래기간 일관성: 5거래일 이상, 폐지일 = 마지막 거래일의 다음 영업일(실측 3건 모두 충족)
        n = tdiff(con, cur["RIGHTS_LIST_START"], cur["RIGHTS_LIST_END"]) + 1
        gap = tdiff(con, cur["RIGHTS_LIST_END"], cur["RIGHTS_DELIST"]) if cur.get("RIGHTS_DELIST") else None
        out["rights_listing_check"] = {"trading_days": n, "delist_gap": gap, "ok": n >= 5 and gap in (None, 1)}
    # 지수 반영
    eff, est, why = None, 0, None
    if track == "RIGHTS":
        eff, est = cur.get("EX_DATE"), int(not S.get("ex_notice"))
        why = "주주배정: 권리락일(= 신주배정기준일 직전 영업일, T+2 결제)부터 지수 주식수 증가" + ("" if S.get("ex_notice") else " — 권리락 공시 전, 기준일에서 계산한 추정일")
    elif track in ("THIRD_PARTY", "PUBLIC"):
        eff = cur.get("NEW_SHARE_LISTING")
        est = int(not S.get("listing_actual"))
        why = ("제3자배정" if track == "THIRD_PARTY" else "일반공모") + ": 신주 상장일에 지수 주식수 증가" + ("" if not est else " — 상장일 미확정(추가상장 공시 대기)")
    else:
        eff, est, why = cur.get("NEW_SHARE_LISTING"), 1, "규칙 미확정 방식 — 신주 상장일 가정"
        con.execute("UPDATE event SET review_flag=1 WHERE event_id=?", (eid,))
    basis = "ACTUAL" if (S.get("issue_result") and eff and eff <= asof) else ("AS_OF_EFFECTIVE" if eff and eff <= asof else "PLANNED")
    if new_sh:
        # 적용일 시점에 유효했던 신주수(그 시점까지의 공시) — 정정으로 이후 바뀌어도 이미 반영된 값은 고정
        delta = new_sh
        if eff and eff <= asof and S["amendments"]:
            asof_dec = [i[3] for i in t["items"] if i[1] == "DECISION" and i[0][:10] <= eff]
            if asof_dec and asof_dec[-1]["new_shares"]:
                delta = asof_dec[-1]["new_shares"] if not S.get("issue_result") else new_sh
        lst = listed_as_of(con, t["security_id"], eff or asof, eid)
        con.execute("""INSERT INTO index_share_adj(event_id,security_id,effective_date,delta_shares,basis,is_estimated,source_filing_id,note) VALUES (?,?,?,?,?,?,?,?)""",
                    (eid, t["security_id"], eff, delta, basis, est, (S.get("ex_notice") or [{}])[0].get("filing") if S.get("ex_notice") else S["sources"][-1]["filing"], why))
        out["index"] = {"delta_shares": delta, "effective_date": eff, "basis": basis, "is_estimated": est, "why": why,
                        "listed_before": lst, "index_after": (lst + delta) if lst else None}
    # 상태
    done = bool(S.get("listing_actual")) and cur.get("NEW_SHARE_LISTING", "9") <= asof
    con.execute("UPDATE event SET status=?, detail_json=?, updated_at=?, title=? WHERE event_id=?",
                ("done" if done else "confirmed", json.dumps(out, ensure_ascii=False, default=str), NOW(), f"유상증자({d['method']})", eid))
    return out


def run(con, asof=None, network=True):
    asof = asof or dt.date.today().isoformat()
    th = load_threads(con)
    attach_follow(con, th)
    prune(con, "PCI:", set(th))
    res = {}
    for key, t in th.items():
        eid, S = replay(con, t, asof)
        if network:
            try:
                fetch_prospectus(con, t, eid, S, asof)
            except Exception as e:  # 온디맨드 조회 실패는 스레드 구성을 막지 않는다
                S.setdefault("warnings", []).append(f"prospectus_fetch_failed: {e}")
        out = finalize(con, t, eid, S, asof)
        for _, kind, f, _p in t["items"]:
            st = "parsed"
            con.execute("UPDATE filing SET parse_status=?, skip_reason=NULL WHERE filing_id=? AND parse_status IN ('new','review','failed')", (st, f["filing_id"]))
        res[key] = (eid, out)
    con.commit()
    return res


if __name__ == "__main__":
    con = db.connect()
    asof = sys.argv[sys.argv.index("--asof") + 1] if "--asof" in sys.argv else None
    r = run(con, asof, network="--no-network" not in sys.argv)
    for key, (eid, out) in r.items():
        print(key, "event", eid, "|", out and out["method"], "|", out and out.get("index"))
