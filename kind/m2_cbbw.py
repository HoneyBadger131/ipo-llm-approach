"""M2 — 전환사채(CB)·신주인수권부사채(BW) 스레드: 발행 조건 + 전환/행사에 따른 신주 상장 이력 + 잔여 희석분.

지수 규칙(index_rules.py): 보통주 전환·행사로 늘어난 주식은 *전환(행사) 신주 상장일*에 지수 주식수가 증가한다.
  → 개별 전환·행사 상장(추가상장 / 상장안내 공시)은 M1 이 원장(share_ledger)에 이미 +로 기록한다. 여기서는 그것을 발행 시리즈(회차)에 묶고
    '발행 당시 전환 가능 주식수 − 누적 전환 = 잔여 가능 주식수'(희석 overhang)를 추적한다.
스레드 키 'CBW:<issuer_id>:<최초 결정일>' (정정공시는 '정정대상 공시서류의 최초제출일'로 원 스레드에 붙음).
  .venv/bin/python kind/m2_cbbw.py [--asof YYYY-MM-DD] [--no-network]
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import kind_client as kc
from common import after, cal, kdate, link_filing, prune, set_slot, text_of
from m2_decision import num, split_items, toks

NOW = lambda: dt.datetime.now().isoformat(timespec="seconds")
KIND_BY_TITLE = {"전환사채권발행결정": "CB", "신주인수권부사채권발행결정": "BW"}


def parse_decision(text, kind):
    out = {"kind": kind, "amend_of": None, "amend_note": None}
    m = re.search(r"정정대상 공시서류의 최초제출일\s*:\s*\|?\s*\n?\s*([^\n|]+)", text)
    if m:
        out["amend_of"] = kdate(m.group(1))
    m = re.search(r"정정사유[^\n]*\n\s*([^|\n]+)", text)
    if m:
        out["amend_note"] = m.group(1).strip()[:80]
    head = "전환사채권 발행결정" if kind == "CB" else "신주인수권부사채권 발행결정"
    ms = list(re.finditer(re.escape(head) + r"\s*\n\s*1\.\s*사채의 종류", text))
    if not ms:
        return None
    it = {re.sub(r"\s+", "", l.split("(")[0]): v for l, v in split_items(toks(text[ms[-1].start():])).values()}

    def item(key):
        key = re.sub(r"\s+", "", key)
        for k, v in it.items():
            if key in k:
                return v
        return []
    v = item("사채의종류")
    out["round"] = num(after(v, "회차")) if after(v, "회차") else None
    out["type_text"] = after(v, "종류")
    out["face_amount"] = num((item("사채의권면") or [None])[0])
    v = item("자금조달의목적")
    use = {}
    for i in range(0, len(v) - 1, 2):
        use[re.sub(r"\s*\(원\)", "", v[i])] = num(v[i + 1]) or 0
    out["use_of_funds"] = {k: x for k, x in use.items() if x}
    v = item("사채의이율")
    out["coupon_pct"] = num(after(v, "표면이자율"))
    out["ytm_pct"] = num(after(v, "만기이자율"))
    out["maturity"] = kdate((item("사채만기일") or [""])[0])
    out["method"] = (item("사채발행방법") or [None])[0]
    if kind == "CB":
        v = item("전환에관한사항")
        out["strike"] = num(after(v, "전환가액 (원/주)")) or num(after(v, "전환가액"))
        out["shares"] = num(after(v, "주식수"))
        out["pct_of_total"] = num(after(v, "주식총수 대비비율")) or num(after(v, "주식총수대비비율"))
        out["ex_start"] = kdate(after(v, "시작일")) if after(v, "시작일") else None
        out["ex_end"] = kdate(after(v, "종료일")) if after(v, "종료일") else None
        out["separable"] = None
    else:
        v = item("신주인수권에관한사항")
        out["strike"] = num(after(v, "행사가액 (원/주)"))
        out["shares"] = num(after(v, "주식수"))
        out["pct_of_total"] = num(after(v, "주식총수 대비비율")) or num(after(v, "주식총수대비비율"))
        out["ex_start"] = kdate(after(v, "시작일")) if after(v, "시작일") else None
        out["ex_end"] = kdate(after(v, "종료일")) if after(v, "종료일") else None
        out["separable"] = after(v, "사채와 인수권의 분리여부")
    flat = re.sub(r"\s+", " ", text[ms[-1].start():])
    m = re.search(r"최저 조정가액 \(원\)\s*\|\s*([\d,]+|-)", flat)
    out["refix_floor"] = num(m.group(1)) if m and m.group(1) != "-" else None
    m = re.search(r"조기상환일[^.]{0,40}?(\d{4}년\s*\d{1,2}월\s*\d{1,2}일)|이 되는 (?:날)?\(?(\d{4}년\s*\d{1,2}월\s*\d{1,2}일)", flat)
    pm = re.search(r"조기상환청구권[^.]{0,200}?(\d{4}년\s*\d{1,2}월\s*\d{1,2}일)", flat)
    out["put_first"] = kdate(pm.group(1)) if pm else None
    out["maturity_redemption_pct"] = None
    m2 = re.search(r"원금의\s*([\d.]+)%로 일시상환", flat)
    if m2:
        out["maturity_redemption_pct"] = float(m2.group(1))
    for key, label in (("sub_date", "청약일"), ("payment", "납입일"), ("board_date", "이사회결의일")):
        out[key] = kdate((item(label) or [""])[0])
    out["sec_filing_required"] = (item("증권신고서제출대상여부") or [None])[0]
    return out


def p_warrant_listing(text):
    it = {}
    for line in text.split("\n"):
        m = re.match(r"\s*(\d)\.\s*([^:]+?)\s*:\s*(.+)$", line)
        if m:
            it[m.group(2).strip()] = m.group(3).strip()
    g = lambda k: next((v for l, v in it.items() if k in l), None)
    cnt = re.search(r"([\d,]+)\s*증권", g("신주인수권 증권의 수") or "")
    ex = re.search(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})", g("행사기간") or "")
    return {"instrument": g("상장종목"), "list_date": kdate(g("상장일")), "count": num(cnt.group(1)) if cnt else None, "strike": num((g("행사가격") or "").replace("원", "")),
            "issue_date": kdate(g("발행일자")), "ex_start": ex.group(1) if ex else None, "ex_end": ex.group(2) if ex else None}


def warrant_remaining(text):
    """상장안내(보통주 추가상장 및 신주인수권(증권) 변경상장)의 '변경전 → 변경후' 잔여 증권수"""
    m = re.search(r"([\d,]+)증권\s*→\s*([\d,]+)증권", text)
    return (num(m.group(1)), num(m.group(2))) if m else None


def load(con):
    th = {}
    rows = con.execute("""SELECT f.*, s.issuer_id AS iss FROM filing f JOIN security s USING(security_id)
                          WHERE f.src='KIND' AND f.title IN ('전환사채권발행결정','신주인수권부사채권발행결정') AND f.body_path IS NOT NULL ORDER BY f.filed_at""").fetchall()
    for f in rows:
        kind = KIND_BY_TITLE[f["title"]]
        d = parse_decision(re.sub(r"[ \t]+", " ", text_of(f)), kind)
        if d is None:
            con.execute("UPDATE filing SET parse_status='review', skip_reason='cbbw_parse' WHERE filing_id=?", (f["filing_id"],))
            continue
        kd = d["amend_of"] or f["filed_date"]
        key = f"CBW:{f['iss']}:{kd}:{kind}"
        t = th.setdefault(key, {"key": key, "kind": kind, "issuer_id": f["iss"], "security_id": f["security_id"], "start": f["filed_at"], "start_date": kd, "items": [], "conv": []})
        t["items"].append((f["filed_at"], "DECISION", f, d))
    # 같은 회차를 일정·조건 변경으로 이사회가 재결의한 경우(엘앤에프 BW 제7회: 6/16·6/27·7/8·7/15) 하나의 시리즈로 병합.
    # 규칙: (법인, 종류, 회차)가 같고 뒤 결정이 앞 결정의 납입일 이전에 제출되면 같은 시리즈.
    merged = {}
    for key, t in sorted(th.items(), key=lambda kv: kv[1]["start"]):
        d0 = next(i[3] for i in t["items"] if i[1] == "DECISION")
        gk = (t["issuer_id"], t["kind"], d0["round"])
        tgt = merged.get(gk)
        pay = None
        if tgt:
            pays = [i[3]["payment"] for i in tgt["items"] if i[1] == "DECISION" and i[3]["payment"]]
            pay = max(pays) if pays else None
        if tgt and (pay is None or t["start"][:10] <= pay):
            tgt["items"].extend(t["items"])
            tgt["items"].sort(key=lambda x: x[0])
        else:
            merged[gk] = t
    return {t["key"]: t for t in merged.values()}


CONV_RX = re.compile(r"^(추가상장\((국내CB전환|국내BW행사|신주인수권행사|전환권행사|CB전환|BW행사)|상장안내\(보통주 추가상장 및 신주인수권)")


def attach(con, th):
    by_iss = {}
    for t in th.values():
        by_iss.setdefault((t["issuer_id"], t["kind"]), []).append(t)
    for l in by_iss.values():
        l.sort(key=lambda t: t["start"])
    orphans = []
    for r in con.execute("""SELECT l.*, f.title, f.filed_at, f.body_path, s.issuer_id AS iss FROM share_ledger l JOIN filing f ON f.filing_id=l.source_filing_id
                            JOIN security s ON s.security_id=l.security_id WHERE l.superseded_by IS NULL ORDER BY l.effective_date""").fetchall():
        title = r["title"]
        if not CONV_RX.match(title):
            continue
        kind = "CB" if ("CB" in title or "전환" in title) else "BW"
        cands = [t for t in by_iss.get((r["iss"], kind), []) if t["start"] <= r["filed_at"]]
        if not cands:
            orphans.append(dict(r))
            continue
        t = cands[-1]  # 같은 종류 시리즈가 여럿이면 가장 최근 발행분(가격 대조는 후속)
        txt = text_of({"body_path": r["body_path"]}) if r["body_path"] else ""
        t["conv"].append({"ledger_id": r["ledger_id"], "filing": r["source_filing_id"], "list_date": r["effective_date"], "shares": r["delta_shares"], "issue_date": r["issue_date"],
                          "before": r["shares_before"], "after": r["shares_after"], "title": title, "warrant_remaining": warrant_remaining(txt) if kind == "BW" else None,
                          "price": num(((re.search(r"1주의 발행가액\s*\(액면가:[\d,]+원\)\s*:\s*([\d,]+)원", txt) or re.search(r"1주의 발행가액\s*:\s*([\d,]+)원", txt)) or [None, None])[1]) if txt else None,
                          "issue_detail": json.loads(r["issue_detail"]) if r["issue_detail"] else None})
    q = """SELECT f.*, s.issuer_id AS iss FROM filing f JOIN security s USING(security_id) WHERE f.src='KIND' AND f.body_path IS NOT NULL
           AND (f.title LIKE '신주인수권증권 신규상장%' OR f.title LIKE '유상증자 또는 주식관련사채 등의 발행결과%')"""
    for f in con.execute(q).fetchall():
        txt = text_of(f)
        if f["title"].startswith("신주인수권증권"):
            kinds = ["BW"]
        else:
            ic, ib = txt.find("전환사채"), txt.find("신주인수권부사채")
            if ic < 0 and ib < 0:
                continue  # 주식 발행(유상증자) 결과 — 사채 아님
            kinds = ["BW"] if (ib >= 0 and (ic < 0 or ib < ic)) else ["CB"]  # 본문에 먼저 나오는 사채 종류
        for kd in kinds:
            c = [t for t in by_iss.get((f["iss"], kd), []) if t["start"] <= f["filed_at"]]
            if c:
                t = c[-1]
                t["items"].append((f["filed_at"], "WARRANT_LISTING" if f["title"].startswith("신주인수권증권") else "ISSUE_RESULT", f,
                                   p_warrant_listing(txt) if f["title"].startswith("신주인수권증권") else {"payment": kdate((re.search(r"납입일\s*\|?\s*(\d{4}-\d{2}-\d{2})", re.sub(r"\s+", " ", txt)) or [None, ""])[1])}))
                break
    for t in th.values():
        t["items"].sort(key=lambda x: x[0])
    return orphans


def replay(con, t, asof):
    key = t["key"]
    ev = con.execute("SELECT event_id FROM event WHERE thread_key=?", (key,)).fetchone()
    if ev:
        eid = ev[0]
        con.execute("DELETE FROM event_date WHERE event_id=?", (eid,))
        con.execute("DELETE FROM event_filing WHERE event_id=?", (eid,))
    else:
        eid = con.execute("""INSERT INTO event(issuer_id,security_id,event_type,status,title,created_at,updated_at,thread_key)
                             VALUES (?,?,'CONVERTIBLE_ISSUE','confirmed','주식관련사채',?,?,?)""", (t["issuer_id"], t["security_id"], NOW(), NOW(), key)).lastrowid
    S = {"amendments": [], "sources": [], "warrant": None, "results": []}
    prev, first = None, True
    for at, kind, f, p in t["items"]:
        fid = f["filing_id"]
        link_filing(con, eid, f, kind == "DECISION", first, S)
        if kind == "DECISION":
            d = p
            if first:
                set_slot(con, eid, "RESOLUTION", d["amend_of"] or d["board_date"] or f["filed_date"], 0, fid)
            for role, val in (("SUBSCRIPTION", d["sub_date"]), ("PAYMENT", d["payment"]), ("EXERCISE_START", d["ex_start"]), ("EXERCISE_END", d["ex_end"]),
                              ("PUT_FIRST", d["put_first"]), ("MATURITY", d["maturity"])):
                set_slot(con, eid, role, val, 0, fid)
            if prev:
                ch = {k: [prev.get(k), d.get(k)] for k in ("face_amount", "strike", "shares", "ex_start", "ex_end", "payment", "maturity", "refix_floor", "put_first") if prev.get(k) != d.get(k)}
                S["amendments"].append({"filing": fid, "at": f["filed_at"], "note": d["amend_note"], "changes": ch})
            S["decision"] = d
            prev, first = d, False
        elif kind == "WARRANT_LISTING":
            S["warrant"] = {"filing": fid, **p}
            set_slot(con, eid, "WARRANT_LISTING", p["list_date"], 0, fid)
        elif kind == "ISSUE_RESULT":
            S["results"].append({"filing": fid, **p})
            if p.get("payment"):
                set_slot(con, eid, "PAYMENT", p["payment"], 0, fid)
    for c in t["conv"]:
        con.execute("UPDATE share_ledger SET event_id=? WHERE ledger_id=?", (eid, c["ledger_id"]))
        con.execute("INSERT OR IGNORE INTO event_filing VALUES (?,?,?)", (eid, c["filing"], "follow"))
    return eid, S


def official_balance(con, t, S, network=True):
    """CB: 신고사항(주식관련사채) '전환청구권·신주인수권·교환청구권 행사' 최신 공시의 잔액·전환가능 주식수 (온디맨드, 수집 범위 밖)"""
    if not network or t["kind"] != "CB":
        return None
    codes, _ = kc.filing_type_codes()
    sub = "|".join(c for c, _ in codes["04"]) + "|"
    code = con.execute("SELECT code FROM security_code WHERE security_id=? AND code_type='SHORT'", (t["security_id"],)).fetchone()[0]
    from collector import windows  # 상세검색은 1년 초과 구간이면 오류 없이 0건 → 330일 단위로 분할
    rows = []
    for w0, w1 in windows(t["start_date"], dt.date.today().isoformat()):
        rows += kc.list_filings(code=code, frm=w0, to=w1, disclosureType04=sub, pDisclosureType04=sub)
    cand = sorted([r for r in rows if r["title"].startswith("전환청구권") and "행사" in r["title"]], key=lambda r: r["datetime"], reverse=True)
    if not cand:
        return None
    r = cand[0]
    tk = toks(kc.body_text(r["acpt_no"]))
    bal = None
    for i, v in enumerate(tk):
        if v.startswith("전환사채 잔액") or v.startswith("신주인수권부사채 잔액"):
            nums = [x for x in tk[i + 1:i + 20] if re.fullmatch(r"[\d,]+", x)]
            if len(nums) >= 5:  # 회차, 권면총액, 미전환 잔액, 전환가액, 전환가능 주식수
                bal = {"round": int(nums[0].replace(",", "")), "face": num(nums[1]), "remaining_amount": num(nums[2]), "strike": num(nums[3]), "remaining_shares": num(nums[4])}
            break
    cum = next((num(tk[j + 1]) for j, x in enumerate(tk) if x.startswith("2. 행사주식수 누계")), None)
    return {"notice_date": r["datetime"][:10], "acpt_no": r["acpt_no"], "balance": bal, "cumulative_claim_shares": cum}


def finalize(con, t, eid, S, asof, network=True):
    d = S["decision"]
    conv = sorted(t["conv"], key=lambda c: (c["list_date"], c["ledger_id"]))
    potential = (S["warrant"] or {}).get("count") or d["shares"]
    cum, rows = 0, []
    for c in conv:
        cum += c["shares"]
        rows.append({"list_date": c["list_date"], "issue_date": c["issue_date"], "shares": c["shares"], "cum": cum, "remaining": (potential - cum) if potential else None,
                     "filing": c["filing"], "price": c["price"], "warrant_remaining": (c["warrant_remaining"] or (None, None))[1]})
    listed = None
    r = con.execute("SELECT shares_after FROM share_ledger WHERE security_id=? AND superseded_by IS NULL AND effective_date<=? AND shares_after IS NOT NULL ORDER BY effective_date DESC, ledger_id DESC LIMIT 1", (t["security_id"], asof)).fetchone()
    listed = r[0] if r else None
    remaining = (potential - cum) if potential else None
    check = None
    last_w = next((x["warrant_remaining"] for x in reversed(rows) if x["warrant_remaining"] is not None), None)
    if t["kind"] == "BW" and last_w is not None and remaining is not None:
        check = {"warrant_notice_remaining": last_w, "computed_remaining": remaining, "ok": last_w == remaining}
    off = official_balance(con, t, S, network)
    if off and off.get("balance") and potential:
        # 공시 시점 이전에 *청구(발행)된* 전환분만 모아 공식 잔여와 대조 — 상장은 청구 후 약 2주 뒤라 발행일별 수량(issue_detail)로 계산
        claimed = 0
        for c in conv:
            det = c.get("issue_detail") or ([[c["issue_date"], c["shares"]]] if c["issue_date"] else None)
            if det:
                claimed += sum(q for d_, q in det if d_ <= off["notice_date"])
        off["computed_remaining_at_notice"] = potential - claimed
        off["check_ok"] = off["computed_remaining_at_notice"] == off["balance"]["remaining_shares"]
        after_notice = sum(q for c in conv for d_, q in (c.get("issue_detail") or ([[c["issue_date"], c["shares"]]] if c["issue_date"] else [])) if d_ > off["notice_date"])
        off["claimed_after_notice"] = after_notice
    iss = con.execute("SELECT name FROM issuer WHERE issuer_id=?", (t["issuer_id"],)).fetchone()[0]
    out = {"issuer": iss, "kind": t["kind"], "round": d["round"], "type_text": d["type_text"], "face_amount": d["face_amount"], "method": d["method"], "coupon_pct": d["coupon_pct"], "ytm_pct": d["ytm_pct"],
           "maturity": d["maturity"], "maturity_redemption_pct": d["maturity_redemption_pct"], "strike": d["strike"], "shares_at_issue": d["shares"], "pct_of_total": d["pct_of_total"],
           "potential": potential, "converted": cum, "remaining": remaining, "remaining_amount": (remaining * d["strike"]) if remaining and d["strike"] else None,
           "remaining_pct_of_listed": round(remaining / listed * 100, 2) if remaining and listed else None, "listed_now": listed, "conversions": rows, "warrant": S["warrant"],
           "put_first": d["put_first"], "refix_floor": d["refix_floor"], "separable": d["separable"], "use_of_funds": d["use_of_funds"], "amendments": S["amendments"],
           "results": S["results"], "check_warrant": check, "official": off, "sources": S["sources"]}
    done = remaining is not None and remaining <= 0
    con.execute("UPDATE event SET status=?, detail_json=?, updated_at=?, title=? WHERE event_id=?",
                ("done" if done else "confirmed", json.dumps(out, ensure_ascii=False, default=str), NOW(), f"{'전환사채' if t['kind'] == 'CB' else '신주인수권부사채'} 제{d['round']}회", eid))
    for it in t["items"]:
        if it[1] == "DECISION":
            con.execute("UPDATE filing SET parse_status='parsed', skip_reason=NULL WHERE filing_id=? AND parse_status IN ('new','review','failed')", (it[2]["filing_id"],))
    return out


def run(con, asof=None, network=True):
    asof = asof or dt.date.today().isoformat()
    th = load(con)
    orphans = attach(con, th)
    prune(con, "CBW:", set(th))
    res = {}
    for key, t in th.items():
        eid, S = replay(con, t, asof)
        try:
            res[key] = (eid, finalize(con, t, eid, S, asof, network))
        except Exception as e:
            res[key] = (eid, {"error": f"{type(e).__name__}: {e}"})
    con.commit()
    return res, orphans


if __name__ == "__main__":
    con = db.connect()
    asof = sys.argv[sys.argv.index("--asof") + 1] if "--asof" in sys.argv else None
    r, orphans = run(con, asof, network="--no-network" not in sys.argv)
    for k, (eid, o) in r.items():
        print(k, eid, o.get("issuer"), o.get("kind"), o.get("round"), "전환/행사", o.get("converted"), "잔여", o.get("remaining"), o.get("error", ""), (o.get("check_warrant") or {}))
    print("orphan conversions:", len(orphans), sorted({(o["security_id"]) for o in orphans}))
