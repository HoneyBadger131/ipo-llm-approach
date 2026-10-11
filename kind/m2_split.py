"""M2 — 회사분할(인적분할) 이벤트 스레드.

흐름: 회사분할 결정(+정정, 일정·분할비율 변경) → 임시주주총회 결과 → 매매거래정지(회사분할에 따른 전자등록 변경, 말소; 해제=변경상장일)
      → 변경상장(회사분할(존속)) 공시 → 변경상장일(= 존속법인 지수반영주식수 감소일) → 변경상장 기준가격결정방법 안내
      + 신설법인 재상장(= 존속 변경상장일과 같은 날, 별개 종목)
지수 규칙(사용자 확정, docs/KIND_INDEX_METHOD.md 4절): 존속법인 감소 = 변경상장일(붙임2의 '첫 매매일 익일' 아님) · 신설법인은 별개 종목(재상장일, 계속 트래킹 → 워치리스트 자동 추가).
물적분할은 범위 밖: 스레드만 만들고(PHYSICAL) 주식수 조정은 하지 않는다.

신설법인 상장주식수: 재상장 공시 전에는 *계산값* = 존속 감소분 × (분할회사 1주의 금액 ÷ 분할신설회사 1주의 금액)
  (자기주식 배정 제외는 반영 못 하는 근사 — 재상장 공시의 수치가 나오면 덮어쓴다. 사용자 확정)

스레드 키 'SPL:<issuer_id>:<최초 결정일>'. 재실행 시 처음부터 재구성(멱등).
  .venv/bin/python kind/m2_split.py --register   # 신설법인을 KIND 에서 해석해 issuer/security/watchlist 에 추가, 마지막 줄에 단축코드(쉼표) 출력
  .venv/bin/python kind/m2_split.py [--asof YYYY-MM-DD]
"""
import datetime as dt
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import kind_client as kc
from common import cal, kdate, link_filing, prune, set_slot, tdiff, text_of
from m2_decision import num, split_items, toks

NOW = lambda: dt.datetime.now().isoformat(timespec="seconds")
WATCH = "phase1"
CAL_MARK = "계산:"  # 신설법인 계산 원장 행의 reason 접두 (재실행 시 삭제 후 재생성)
CHANGED_FIELDS = ("ratio_new", "reduction_pct", "halt_start", "halt_end", "record_date", "listing_date", "egm_date", "split_date")


# ───────────── 결정 공시 파서 ─────────────
def parse_split(text):
    out = {"amend_of": None, "amend_note": None}
    m = re.search(r"정정대상 공시서류의 최초제출일\s*:\s*\|?\s*\n?\s*([^\n|]+)", text)
    if m:
        out["amend_of"] = kdate(m.group(1))
    ms = list(re.finditer(r"회사분할 결정\s*\n\s*1\.\s*분할방법", text))
    if not ms:
        return None
    it = split_items(toks(text[ms[-1].start():]))
    g = lambda n: it.get(n, ("", []))[1]
    flat = lambda n: " ".join(g(n))
    m1 = flat(1)
    out["kind"] = "PERSONAL" if "인적분할" in m1[:600] else "PHYSICAL"
    m = re.search(r"분할신설회사\s*:\s*([^\s(]+(?:\s*주식회사)?)", m1)
    out["surv_name"] = (re.search(r"분할존속회사\s*:\s*([^\s(\-]+(?:\s*주식회사)?)", m1) or [None, None])[1]
    v7 = g(7)
    nm = v7[v7.index("회사명") + 1] if "회사명" in v7 and len(v7) > v7.index("회사명") + 1 else (m.group(1) if m else None)
    nm = re.sub(r"\(.*", "", nm or "")
    out["new_name"] = re.sub(r"\s*주식회사\s*|㈜|\(주\)", "", nm).strip() or None
    out["new_relist"] = (v7[v7.index("재상장신청 여부") + 1] if "재상장신청 여부" in v7 and len(v7) > v7.index("재상장신청 여부") + 1 else None)
    r4 = flat(4)
    a = re.search(r"분할존속회사\s*:\s*([\d.]+)", r4)
    b = re.search(r"분할신설회사\s*:\s*([\d.]+)", r4)
    out["ratio_surv"], out["ratio_new"] = (float(a.group(1)) if a else None), (float(b.group(1)) if b else None)
    v8 = g(8)

    def after(lbl, n=1, vals=None):
        vals = v8 if vals is None else vals
        for i, x in enumerate(vals):
            if x.startswith(lbl):
                return vals[i + n] if i + n < len(vals) else None
        return None
    out["reduction_pct"] = num(after("감자비율"))
    i = v8.index("매매거래정지 예정기간") if "매매거래정지 예정기간" in v8 else None
    out["halt_start"] = kdate(after("시작일", 1, v8[i:])) if i is not None else None
    out["halt_end"] = kdate(after("종료일", 1, v8[i:])) if i is not None and kdate(after("종료일", 1, v8[i:])) else None
    out["record_date"] = kdate(after("신주배정기준일"))
    out["listing_date"] = kdate(after("신주의 상장예정일"))
    cond = after("신주배정조건") or ""
    out["alloc_text"] = re.sub(r"\s+", " ", cond)[:400]
    out["alloc"] = {k: float(x) for k, x in re.findall(r"(보통주식|종류주식\([^)]*\))\s*:\s*([\d.]+)주", cond)}
    # 1주의 금액: '5,000원(분할회사 1주의 금액) / 1,000원(분할신설회사 1주의 금액)' 또는 '분할회사 1주의 금액 2,500원을 분할신설회사의 1주의 금액 2,500원으로'
    p = re.search(r"([\d,]+)원\s*\(\s*분할회사\s*1주의\s*금액\s*\)\s*/\s*([\d,]+)원", cond) or re.search(r"분할회사\s*1주의\s*금액\s*([\d,]+)원[을를]?\s*분할신설회사의?\s*1주의\s*금액\s*([\d,]+)원", cond)
    out["par_old"], out["par_new"] = (num(p.group(1)), num(p.group(2))) if p else (None, None)
    v9 = g(9)
    out["board_date"] = kdate(after("이사회결의일", 1, v9))
    out["egm_date"] = kdate(after("주주총회예정일자", 1, v9))
    out["split_date"] = kdate(after("분할기일", 1, v9))
    out["register_date"] = kdate(after("분할등기예정일자", 1, v9))
    out["record_holders_date"] = kdate(after("주주확정기준일", 1, v9))
    return out


# ───────────── 신설법인 등록 ─────────────
def decisions(con):
    """(filing, parsed) 목록 — 시간순. 자회사 공시(제목에 '자회사')와 본문 없는 건은 제외."""
    res = []
    for f in con.execute("""SELECT f.*, s.issuer_id AS iss FROM filing f JOIN security s USING(security_id)
                            WHERE f.src='KIND' AND f.title='회사분할 결정' AND f.body_path IS NOT NULL ORDER BY f.filed_at""").fetchall():
        d = parse_split(re.sub(r"[ \t]+", " ", text_of(f)))
        if d is None:
            con.execute("UPDATE filing SET parse_status='review', skip_reason='split_parse' WHERE filing_id=?", (f["filing_id"],))
            continue
        res.append((f, d))
    return res


def pick_listed(res, name):
    for x in res:
        if x.get("comabbrv") == name and x.get("secugrpId") == "ST" and x.get("liststatcd") == "Y":
            return x
    return None


def register(con):
    """인적분할 신설법인 → issuer/security(COMMON)/watchlist. KIND 에 상장 종목으로 아직 안 나오면(분할 전) 건너뛴다. 반환: 단축코드 목록"""
    from seed_master import upsert_issuer, upsert_security
    codes = []
    for f, d in decisions(con):
        if d["kind"] != "PERSONAL" or not d["new_name"]:
            continue
        res = pick_listed(kc.resolve_name(d["new_name"]), d["new_name"])
        if not res:
            print(f"  신설법인 미상장/해석 실패: {d['new_name']} ({f['filing_id']})", file=sys.stderr)
            continue
        short = res["repisusrtcd"][1:]
        iss = upsert_issuer(con, d["new_name"], res["isurcd"])
        sid = upsert_security(con, iss, "COMMON", d["new_name"], short, res["repisucd"], None, "KOSPI")
        con.execute("INSERT OR IGNORE INTO watchlist VALUES (?,?,?)", (WATCH, sid, NOW()))
        if short not in codes:
            codes.append(short)
    con.commit()
    return codes


# ───────────── 신설법인 재상장 공시 → 원장 ─────────────
def parse_relist(text):
    """'◎ X 주권 재상장 내역(재상장-인적분할)' → 종류별 [{label, name, short, isin, listing_date, shares, par, accrual}] (보통주/종류주권 블록)"""
    out = []
    for blk in re.split(r"\n\s*\(\d\)\s*(?=[^\n]*주권)", "\n" + text):
        m = re.search(r"④\s*표준코드\s*:\s*(\S+)\s*\(\s*단축코드\s*:\s*A(\w+)\s*\)", blk)
        n = re.search(r"⑤\s*주식의 종류와 수\s*:\s*(?:기명식\s*)?(\S+)\s+([\d,]+)주", blk)
        d = re.search(r"②\s*상장일\s*:\s*([^\n]+)", blk)
        if not (m and n and d):
            continue
        ab = re.search(r"종목약명\s*:\s*\(한글\)\s*([^/\n]+?)\s*/", blk)
        par = re.search(r"⑥[^:\n]*:\s*([\d,]+)원", blk)
        dist = re.search(r"⑨\s*주식분포상황[^\n]*\n(.*?)(?=\n\s*⑩|\Z)", blk, re.S)  # 최대주주·소액주주 지분 등
        out.append({"label": n.group(1), "sec_type": "PREFERRED" if "우" in n.group(1) or "종류" in blk[:blk.find("①")+1] else "COMMON", "name": ab.group(1).strip() if ab else None,
                    "short": m.group(2), "isin": m.group(1), "listing_date": kdate(d.group(1)), "shares": num(n.group(2)), "par": num(par.group(1)) if par else None,
                    "distribution": re.sub(r"\s*\n\s*", " / ", dist.group(1).strip())[:400] if dist else None})
    return out


def load_relists(con):
    """'재상장(…, 상장일 …)' 공시(재상장-인적분할) → 신설법인 종목(없으면 종류주식 종목 생성) + 원장 행. 멱등."""
    from seed_master import upsert_security
    n = 0
    for f in con.execute("""SELECT f.*, s.issuer_id AS iss FROM filing f JOIN security s USING(security_id)
                            WHERE f.src='KIND' AND f.title LIKE '재상장(%' AND f.body_path IS NOT NULL ORDER BY f.filed_at""").fetchall():
        text = re.sub(r"[ \t]+", " ", text_of(f))
        if "인적분할" not in text[:300]:
            continue
        rows = parse_relist(text)
        if not rows:
            con.execute("UPDATE filing SET parse_status='review', skip_reason='relist_parse' WHERE filing_id=?", (f["filing_id"],))
            continue
        for r in rows:
            st = "PREFERRED" if "우" in (r["label"] or "") else "COMMON"
            sid = upsert_security(con, f["iss"], st, r["name"] or r["short"], r["short"], r["isin"], None, "KOSPI")
            con.execute("INSERT OR IGNORE INTO watchlist VALUES (?,?,?)", (WATCH, sid, NOW()))
            con.execute("""INSERT OR IGNORE INTO share_ledger(security_id,effective_date,delta_shares,shares_before,shares_after,issue_date,is_computed,reason,source_filing_id,issue_detail)
                           VALUES (?,?,?,?,?,NULL,0,'재상장(회사분할 신설)',?,?)""", (sid, r["listing_date"], r["shares"], 0, r["shares"], f["filing_id"],
                                                                                json.dumps({"distribution": r["distribution"]}, ensure_ascii=False) if r.get("distribution") else None))
            n += 1
        con.execute("UPDATE filing SET parse_status='parsed', skip_reason=NULL WHERE filing_id=?", (f["filing_id"],))
    con.commit()
    return n


# ───────────── 스레드 구성 ─────────────
def load(con):
    th = {}
    for f, d in decisions(con):
        kd = d["amend_of"] or f["filed_date"]
        key = f"SPL:{f['iss']}:{kd}"
        t = th.setdefault(key, {"key": key, "issuer_id": f["iss"], "start": f["filed_at"], "start_date": kd, "items": [], "security_id": f["security_id"]})
        t["items"].append((f["filed_at"], "DECISION", f, d))
    return th


def halt_dates(text):
    m = re.search(r"매매거래정지일\s*\|?\s*\n?\s*([^\n|]+)", text)
    return kdate(m.group(1)) if m else None


def attach(con, th):
    by_iss = {}
    for t in th.values():
        by_iss.setdefault(t["issuer_id"], []).append(t)
    for l in by_iss.values():
        l.sort(key=lambda t: t["start"])

    def owner(iss, filed_at):  # 공시 시각 직전에 시작한 스레드(해당 법인)
        c = [t for t in by_iss.get(iss, []) if t["start"] <= filed_at]
        return c[-1] if c else None
    for f in con.execute("""SELECT f.*, s.issuer_id AS iss FROM filing f JOIN security s USING(security_id) WHERE f.src='KIND' AND f.body_path IS NOT NULL
                            AND (f.title LIKE '매매거래정지및정지해제(회사분할%' OR f.title LIKE '회사분할로 인한 변경상장 기준가격결정방법 안내%'
                                 OR f.title='임시주주총회 결과') ORDER BY f.filed_at""").fetchall():
        t = owner(f["iss"], f["filed_at"])
        if not t or (t.get("done_at") and f["filed_at"] > t["done_at"] and f["title"] == "임시주주총회 결과"):
            continue
        if f["title"] == "임시주주총회 결과":
            if "분할계획서" not in text_of(f) or any(i[1] == "EGM" for i in t["items"]):
                continue
            t["items"].append((f["filed_at"], "EGM", f, None))
        elif f["title"].startswith("매매거래정지"):
            if not any(i[1] == "HALT" for i in t["items"]):
                t["items"].append((f["filed_at"], "HALT", f, halt_dates(text_of(f))))
        else:
            t["items"].append((f["filed_at"], "PRICE", f, None))
    q = """SELECT l.*, f.filed_at, f.filed_date, s.issuer_id AS iss, s.sec_type, s.name AS sname FROM share_ledger l JOIN filing f ON f.filing_id=l.source_filing_id
           JOIN security s ON s.security_id=l.security_id WHERE l.reason LIKE '변경상장(회사분할%' AND l.superseded_by IS NULL ORDER BY l.effective_date"""
    groups = {}
    for r in con.execute(q).fetchall():
        groups.setdefault(r["source_filing_id"], []).append(dict(r))
    for fid, rows in sorted(groups.items(), key=lambda kv: kv[1][0]["filed_at"]):
        t = owner(rows[0]["iss"], rows[0]["filed_at"])
        if not t:
            continue
        f = con.execute("SELECT * FROM filing WHERE filing_id=?", (fid,)).fetchone()
        t["items"].append((rows[0]["filed_at"], "LISTING", f, rows))
        t["done_at"] = rows[0]["filed_at"]
    for t in th.values():
        t["items"].sort(key=lambda x: x[0])


def survivor_secs(con, issuer_id):
    return con.execute("""SELECT s.security_id, s.sec_type, s.name FROM security s WHERE s.issuer_id=? AND s.sec_type IN ('COMMON','PREFERRED')
                          AND EXISTS (SELECT 1 FROM share_ledger l WHERE l.security_id=s.security_id) ORDER BY s.security_id""", (issuer_id,)).fetchall()


def listed_before(con, sid, d):
    from index_shares import listed_shares
    return listed_shares(con, sid, d)


def newco_security(con, name):
    r = con.execute("SELECT s.security_id, s.issuer_id, (SELECT code FROM security_code WHERE security_id=s.security_id AND code_type='SHORT') AS short FROM security s WHERE s.name=? AND s.sec_type='COMMON'", (name,)).fetchone()
    return r


def replay(con, t, asof):
    key = t["key"]
    ev = con.execute("SELECT event_id FROM event WHERE thread_key=?", (key,)).fetchone()
    if ev:
        eid = ev[0]
        for tb in ("event_date", "event_filing", "index_share_adj"):
            con.execute(f"DELETE FROM {tb} WHERE event_id=?", (eid,))
        con.execute("DELETE FROM share_ledger WHERE event_id=? AND reason LIKE ?", (eid, CAL_MARK + "%"))
    else:
        eid = con.execute("""INSERT INTO event(issuer_id,security_id,event_type,status,title,created_at,updated_at,thread_key)
                             VALUES (?,?,'CORPORATE_SPLIT','confirmed','회사분할',?,?,?)""", (t["issuer_id"], t["security_id"], NOW(), NOW(), key)).lastrowid
    S = {"amendments": [], "sources": [], "halt": None, "egm": None, "listing": None, "prices": []}
    prev, first = None, True
    for at, kind, f, p in t["items"]:
        fid = f["filing_id"]
        link_filing(con, eid, f, kind == "DECISION", first, S)
        if kind == "DECISION":
            d = p
            if first:
                set_slot(con, eid, "RESOLUTION", d["board_date"] or f["filed_date"], 0, fid)
            for role, k in (("EGM", "egm_date"), ("RECORD", "record_date"), ("SPLIT_DATE", "split_date"), ("HALT_START", "halt_start")):
                set_slot(con, eid, role, d[k], 0, fid)
            if not S.get("listing"):  # 변경상장 공시 전에는 결정 공시의 '신주의 상장예정일' = 예정 변경상장일
                set_slot(con, eid, "CHANGE_LISTING", d["listing_date"], 1, fid)
            if prev:
                ch = {k: [prev.get(k), d.get(k)] for k in CHANGED_FIELDS if prev.get(k) != d.get(k)}
                S["amendments"].append({"filing": fid, "at": f["filed_at"], "changes": ch})
            S["decision"], prev, first = d, d, False
        elif kind == "EGM":
            S["egm"] = {"filing": fid, "date": kdate(re.search(r"주주총회 일자\s*\|?\s*\n?\s*([^\n|]+)", text_of(f)).group(1)) if re.search(r"주주총회 일자", text_of(f)) else f["filed_date"],
                        "approved": "가결" in text_of(f) or "원안대로 승인" in text_of(f)}
            set_slot(con, eid, "EGM", S["egm"]["date"], 0, fid)
        elif kind == "HALT":
            S["halt"] = {"filing": fid, "notice_date": f["filed_date"], "start": p}
            set_slot(con, eid, "HALT_START", p, 0, fid)
            set_slot(con, eid, "HALT_NOTICE", f["filed_date"], 0, fid)
        elif kind == "PRICE":
            ev2 = con.execute("SELECT detail_json FROM event e JOIN event_filing ef USING(event_id) WHERE ef.filing_id=? AND e.event_type='SPLIT_RELIST_PRICE'", (fid,)).fetchone()
            S["prices"].append({"filing": fid, "title": f["title"], **(json.loads(ev2[0]) if ev2 and ev2[0] else {})})
        elif kind == "LISTING":
            rows = p
            S["listing"] = {"filing": fid, "notice_date": f["filed_date"], "listing_date": rows[0]["effective_date"], "split_date": rows[0]["issue_date"],
                            "rows": [{"security_id": r["security_id"], "name": r["sname"], "sec_type": r["sec_type"], "delta": r["delta_shares"], "before": r["shares_before"], "after": r["shares_after"]} for r in rows]}
            set_slot(con, eid, "SPLIT_DATE", rows[0]["issue_date"], 0, fid)
            set_slot(con, eid, "CHANGE_LISTING_NOTICE", f["filed_date"], 0, fid)
            set_slot(con, eid, "CHANGE_LISTING", rows[0]["effective_date"], 0, fid)
            for r in rows:
                con.execute("UPDATE share_ledger SET event_id=? WHERE ledger_id=?", (eid, r["ledger_id"]))
    return eid, S


def finalize(con, t, eid, S, asof):
    d = S["decision"]
    cur = {r["role"]: r for r in con.execute("SELECT * FROM event_date WHERE event_id=? AND superseded_by IS NULL", (eid,))}
    lst_date = cur["CHANGE_LISTING"]["the_date"] if "CHANGE_LISTING" in cur else None
    est = 0 if S["listing"] else 1
    surv = con.execute("SELECT name FROM issuer WHERE issuer_id=?", (t["issuer_id"],)).fetchone()[0]
    out = {"kind": d["kind"], "issuer": surv, "new_name": d["new_name"], "ratio_surv": d["ratio_surv"], "ratio_new": d["ratio_new"], "reduction_pct": d["reduction_pct"],
           "alloc": d["alloc"], "alloc_text": d["alloc_text"], "par_old": d["par_old"], "par_new": d["par_new"], "halt_start": d["halt_start"], "halt_end_decision": d["halt_end"],
           "record_date": d["record_date"], "split_date": d["split_date"], "egm_date": d["egm_date"], "listing_date_decision": d["listing_date"],
           "amendments": S["amendments"], "egm": S["egm"], "halt": S["halt"], "listing": S["listing"], "ref_prices": S["prices"], "sources": S["sources"]}
    if d["kind"] != "PERSONAL":
        out["status_text"] = "물적분할 — 범위 밖(주식수 조정 없음)"
        con.execute("UPDATE event SET event_type='CORPORATE_SPLIT_PHYSICAL', status='done', detail_json=?, updated_at=?, title='회사분할(물적, 범위 밖)' WHERE event_id=?",
                    (json.dumps(out, ensure_ascii=False, default=str), NOW(), eid))
        _parsed(con, t)
        return out
    # 존속법인: 종류별 감소(실제 공시값 또는 감자비율로 계산한 예정값)
    rows = []
    cut = d["ratio_new"]
    plan_base = {}
    for s in survivor_secs(con, t["issuer_id"]):
        before = listed_before(con, s["security_id"], t["start_date"] if not lst_date else (cal(con, lst_date, "prev_trading_date") or lst_date))
        plan_base[s["security_id"]] = before
    if S["listing"]:
        for r in S["listing"]["rows"]:
            rows.append({**r, "basis": "ACTUAL"})
    else:
        for s in survivor_secs(con, t["issuer_id"]):
            b = plan_base.get(s["security_id"])
            if b and cut:
                dec = math.floor(b * cut)
                rows.append({"security_id": s["security_id"], "name": s["name"], "sec_type": s["sec_type"], "delta": -dec, "before": b, "after": b - dec, "basis": "PLANNED"})
        for r in rows:
            con.execute("""INSERT INTO index_share_adj(event_id,security_id,effective_date,delta_shares,basis,is_estimated,source_filing_id,note) VALUES (?,?,?,?,?,?,?,?)""",
                        (eid, r["security_id"], lst_date, r["delta"], "PLANNED", est, S["sources"][-1]["filing"], "인적분할 존속법인: 변경상장일에 감소(공시 전 — 감자비율×상장주식수로 계산한 예정값)"))
    out["survivor"] = {"name": surv, "rows": rows, "listing_date": lst_date, "is_estimated": est,
                       "why": "존속법인: 변경상장일에 지수 주식수 감소" + ("" if not est else " — 변경상장 공시 전, 결정 공시의 신주 상장예정일·감자비율로 계산한 예정값")}
    # 신설법인: 별개 종목. 계산값 → 재상장 공시(원장의 비계산 행)가 있으면 그 값으로 덮어쓴다 (보통주·종류주식별)
    nc = {"name": d["new_name"], "listing_date": lst_date, "classes": []}
    r0 = newco_security(con, d["new_name"]) if d["new_name"] else None
    par = (d["par_old"] / d["par_new"]) if d["par_old"] and d["par_new"] else None
    for r in rows:
        comp = int(round(-r["delta"] * par)) if par and r["delta"] else None
        sec = None
        if r0:
            sec = con.execute("SELECT security_id, name FROM security WHERE issuer_id=? AND sec_type=? ORDER BY security_id LIMIT 1", (r0["issuer_id"], r["sec_type"])).fetchone()
        c = {"sec_type": r["sec_type"], "security_id": sec["security_id"] if sec else None, "name": sec["name"] if sec else None, "computed": comp, "actual": None, "basis": None}
        act = con.execute("""SELECT * FROM share_ledger WHERE security_id=? AND superseded_by IS NULL AND reason NOT LIKE 'SEED:%' AND reason NOT LIKE ? ORDER BY effective_date, ledger_id LIMIT 1""",
                          (sec["security_id"], CAL_MARK + "%")).fetchone() if sec else None
        if act:
            c["actual"] = {"shares_after": act["shares_after"], "effective_date": act["effective_date"], "filing": act["source_filing_id"]}
            c["basis"] = "ACTUAL"
            c["diff"] = (act["shares_after"] - comp) if comp else None
            con.execute("UPDATE share_ledger SET event_id=? WHERE ledger_id=?", (eid, act["ledger_id"]))
        elif comp and lst_date and sec:
            con.execute("""INSERT INTO share_ledger(security_id,effective_date,delta_shares,shares_before,shares_after,issue_date,is_computed,reason,event_id,source_filing_id)
                           VALUES (?,?,?,?,?,?,1,?,?,?)""", (sec["security_id"], lst_date, comp, 0, comp, d["split_date"], CAL_MARK + "재상장(회사분할 신설)", eid, S["sources"][0]["filing"]))
            c["basis"] = "COMPUTED"
        elif comp:
            c["basis"] = "COMPUTED"  # 종목(종류주식)이 아직 없어 원장 행은 만들지 않고 계산값만 표기
        nc["classes"].append(c)
    out["newco"] = nc
    done = bool(S["listing"]) and lst_date and lst_date <= asof
    h = (S["halt"] or {}).get("start") or d["halt_start"]
    out["status_text"] = ("완료(변경상장·재상장)" if done else "변경상장 공시 후 변경상장일 대기" if S["listing"] else
                          "거래정지 중 — 변경상장 공시 대기" if h and h <= asof else "분할 일정 진행 중")
    con.execute("UPDATE event SET status=?, detail_json=?, updated_at=?, title=? WHERE event_id=?",
                ("done" if done else "confirmed", json.dumps(out, ensure_ascii=False, default=str), NOW(), f"회사분할(인적) → {d['new_name']}", eid))
    _parsed(con, t)
    return out


def _parsed(con, t):
    for it in t["items"]:
        if it[1] == "DECISION":
            con.execute("UPDATE filing SET parse_status='parsed', skip_reason=NULL WHERE filing_id=? AND parse_status IN ('new','review','failed')", (it[2]["filing_id"],))


def run(con, asof=None):
    asof = asof or dt.date.today().isoformat()
    load_relists(con)
    th = load(con)
    attach(con, th)
    prune(con, "SPL:", set(th))
    res = {}
    for key, t in th.items():
        eid, S = replay(con, t, asof)
        res[key] = (eid, finalize(con, t, eid, S, asof))
    con.commit()
    return res


if __name__ == "__main__":
    con = db.connect()
    if "--register" in sys.argv:
        codes = register(con)
        print(",".join(codes))
        sys.exit(0)
    asof = sys.argv[sys.argv.index("--asof") + 1] if "--asof" in sys.argv else None
    for k, (eid, o) in run(con, asof).items():
        nc = o.get("newco") or {}
        print(k, eid, o["issuer"], o["kind"], o["ratio_new"], o["status_text"], nc.get("computed"), (nc.get("actual") or {}).get("shares_after"))
