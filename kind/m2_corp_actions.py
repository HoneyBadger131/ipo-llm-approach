"""M2 — 무상증자 · 주식배당 · 액면분할 · 합병 이벤트 스레드 (시범: docs/KIND_M2_CORP_ACTIONS.md).

공통 흐름: 결정 공시(+정정) → [기준가격 안내: 권리락/배당락/액면분할] → [거래정지(액면분할)] → 상장 공시(추가상장/변경상장) → 원장 반영
지수 규칙(index_rules.py · KIND_INDEX_METHOD.md 붙임2):
  무상증자   권리락일에 +증자주식수            (신주 상장일에 실제 상장 수량으로 교체)
  주식배당   배당락일에 +배당주식수            (배당기준일이 결정일보다 앞서면 배당락 없음 → 신주 상장일)
  액면분할   변경상장일에 ×분할비율            (원장 변경상장 행 = 상장주식수 증가)
  합병       합병신주 상장일에 +합병신주       (구성종목 간 합병은 소멸회사 상장폐지가 별도 — 우리는 존속 쪽 신주만)
공시 전 선반영은 index_share_adj(PLANNED), 상장 공시가 원장에 들어오면 원장(실제 수량)이 대체한다. 매번 처음부터 replay(멱등).

스레드 키 'BON|DIV|PSP|MRG:<issuer_id>:<최초 결정일>'.
  .venv/bin/python kind/m2_corp_actions.py [--asof YYYY-MM-DD]
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
from m2_rights_issue import cal, ex_from_record, prune, set_slot, tdiff

NOW = lambda: dt.datetime.now().isoformat(timespec="seconds")
CFG = {
    "BONUS": dict(prefix="BON", title="무상증자결정", etype="BONUS_ISSUE", label="무상증자", anchor=r"1\.\s*신주의 종류와 수", ledger="추가상장(무상증자)", ex="RIGHTS_EX", ex_reason="무상증자"),
    "STOCK_DIV": dict(prefix="DIV", title="주식배당결정", etype="STOCK_DIVIDEND", label="주식배당", anchor=r"1\.\s*1주당 배당주식수", ledger="추가상장(주식배당)", ex="DIVIDEND_EX", ex_reason="주식배당"),
    "PAR_SPLIT": dict(prefix="PSP", title="주식분할 결정", etype="PAR_SPLIT", label="액면분할", anchor=r"1\.\s*주식분할 내용", ledger="변경상장(액면분할)", ex=None, ex_reason=None),
    "MERGER": dict(prefix="MRG", title="회사합병 결정", etype="MERGER", label="합병", anchor=r"1\.\s*합병방법", ledger="추가상장(합병)", ex=None, ex_reason=None),
}
BY_TITLE = {c["title"]: k for k, c in CFG.items()}
LABEL_KR = {"RESOLUTION": "결정(이사회)", "RECORD": "기준일", "EGM": "주주총회(예정)", "EX_DATE": "권리락/배당락일 = 지수 주식수 증가일", "EXT_HALT_START": "소멸회사 거래정지 시작", "EXT_DELIST": "소멸회사 상장폐지", "EFFECTIVE": "효력발생(발행)일",
            "HALT_START": "거래정지 시작", "MERGER_DATE": "합병기일", "REGISTER": "합병등기", "ISSUE": "신주 발행일", "NEW_SHARE_LISTING": "신주 상장일",
            "CHANGE_LISTING": "변경상장일 = 지수 주식수 증가일"}


# ───────────── 결정 공시 파서 ─────────────
def after(vals, label, n=1):
    for i, v in enumerate(vals):
        if v.startswith(label):
            return vals[i + n] if i + n < len(vals) else None
    return None


def dash(v):
    return None if v in (None, "-", "") else v


def parse_decision(kind, text):
    out = {"amend": bool(re.search(r"정\s*정\s*신\s*고", text[:120])), "amend_of": None}
    m = re.search(r"정정대상 공시서류의 최초제출일\s*:\s*\|?\s*\n?\s*([^\n|]+)", text)
    if m:
        out["amend_of"] = kdate(m.group(1))
    # 서식 시작 위치: 정정 표·기타 항목의 '1. …' 인용과 헷갈리지 않도록 항목 수가 가장 많은(동수면 뒤쪽) 후보를 쓴다
    best = None
    for m_ in re.finditer(CFG[kind]["anchor"], text):
        its = split_items(toks(text[m_.start():]))
        if best is None or len(its) >= len(best):
            best = its
    if not best:
        return None
    it = {re.sub(r"\s+", "", l.split("(")[0]): v for l, v in best.values()}

    def item(key):
        key = re.sub(r"\s+", "", key)
        for k, v in it.items():
            if key in k:
                return v
        return []
    out["board_date"] = kdate((item("이사회결의일") or [""])[0])
    if kind == "BONUS":
        out["new_shares"] = num(after(item("신주의 종류와 수"), "보통주식"))
        out["new_other"] = num(after(item("신주의 종류와 수"), "기타주식"))
        out["par"] = num((item("1주당 액면가액") or [None])[0])
        out["pre_shares"] = num(after(item("증자전 발행주식총수"), "보통주식"))
        out["record_date"] = kdate((item("신주배정기준일") or [""])[0])
        out["ratio"] = num(after(item("1주당 신주배정 주식수"), "보통주식"))
        out["accrual_date"] = kdate((item("신주의 배당기산일") or [""])[0])
        out["listing_date"] = kdate((item("신주의 상장 예정일") or [""])[0])
        etc = " ".join(item("기타 투자판단"))
        mt = re.search(r"자기주식\s*총수\s*:?\s*([\d,]+)\s*주", etc) or re.search(r"자기주식의?\s*총수\s*:?\s*([\d,]+)\s*주", etc)
        out["treasury"] = num(mt.group(1)) if mt else None
        mf = re.search(r"신주의\s*재원\s*:?\s*([^\s-][^-\n]{0,20}?)(?=\s*(?:[-\d]|$))", etc)
        out["source"] = mf.group(1).strip() if mf else None
    elif kind == "STOCK_DIV":
        out["ratio"] = num(after(item("1주당 배당주식수"), "보통주식"))
        out["ratio_other"] = num(after(item("1주당 배당주식수"), "종류주식"))
        out["new_shares"] = num(after(item("배당주식총수"), "보통주식"))
        out["new_other"] = num(after(item("배당주식총수"), "종류주식"))
        out["pre_shares"] = num(after(item("발행주식총수"), "보통주식"))
        out["record_date"] = kdate((item("배당기준일") or [""])[0])
        out["listing_date"] = None
        out["treasury"] = None
        mt = re.search(r"자기주식\s*([\d,]+)\s*주를\s*제외한", " ".join(item("기타 투자판단")))
        out["treasury"] = num(mt.group(1)) if mt else None
    elif kind == "PAR_SPLIT":
        v = item("주식분할 내용")
        i = next((k for k, x in enumerate(v) if x.startswith("1주당 가액")), None)
        out["par_before"], out["par_after"] = (num(v[i + 1]), num(v[i + 2])) if i is not None else (None, None)
        j = next((k for k, x in enumerate(v) if x.startswith("보통주식")), None)
        out["shares_before"], out["shares_after"] = (num(v[j + 1]), num(v[j + 2])) if j is not None else (None, None)
        s = item("주식분할 일정")
        out["egm_date"] = kdate(after(s, "주주총회예정일"))
        out["effective_date"] = kdate(after(s, "신주의 효력발생일"))
        k = next((q for q, x in enumerate(s) if x.startswith("매매거래정지기간")), None)
        out["halt_start"] = kdate(after(s[k:], "시작일")) if k is not None else None
        out["halt_end"] = kdate(after(s[k:], "종료일")) if k is not None else None
        out["listing_date"] = kdate(after(s, "신주권상장예정일"))
        out["purpose"] = (item("주식분할목적") or [None])[0]
        out["ratio"] = round(out["shares_after"] / out["shares_before"], 6) if out["shares_before"] and out["shares_after"] else None
    else:  # MERGER
        m1 = " ".join(item("합병방법"))
        out["method"] = re.sub(r"\s+", " ", m1)[:200]
        MK = r"\((유가증권시장\s*상장법인|코스닥시장\s*상장법인|코넥스시장\s*상장법인|주권비상장법인|비상장법인|[^()]*상장[^()]*)\)"
        sv = re.search(r"(?:합병)?존속회사[^:：]*[:：]\s*(.+?)\s*" + MK, m1)
        ex = re.search(r"(?:합병)?소멸회사[^:：]*[:：]\s*(.+?)\s*" + MK, m1)
        clean = lambda n: re.sub(r"\s*\(주\)\s*|㈜|주식회사|\s+", "", n or "") or None
        out["survivor"], out["survivor_mkt"] = (clean(sv.group(1)), re.sub(r"\s+", "", sv.group(2))) if sv else (None, None)
        out["extinct"], out["extinct_mkt"] = (clean(ex.group(1)), re.sub(r"\s+", "", ex.group(2))) if ex else (None, None)
        if not out["survivor"]:  # 시장 표기 없는 서식: '존속회사: A- 소멸회사: B'
            a = re.search(r"존속회사\s*[:：]\s*([^\-|※]+)", m1)
            b = re.search(r"소멸회사\s*[:：]\s*([^\-|※]+)", m1)
            out["survivor"], out["extinct"] = clean(a.group(1)) if a else None, clean(b.group(1)) if b else None
        mf = re.search(r"합병형태\s*[:|-]?\s*(소규모합병|간이합병|[가-힣]+)", m1)
        out["form"] = dash(mf.group(1)) if mf and mf.group(1) != "해당사항없음" else None
        out["form"] = out["form"] or (dash(after(item("합병방법"), "합병형태")) if dash(after(item("합병방법"), "합병형태")) not in ("해당사항없음",) else None)
        mr = re.search(r"=\s*1\s*:\s*([\d.]+)", " ".join(item("합병비율")))
        out["ratio"] = float(mr.group(1)) if mr else None
        out["new_shares"] = num(after(item("합병신주의 종류와 수"), "보통주식"))
        out["new_other"] = num(after(item("합병신주의 종류와 수"), "종류주식"))
        s = item("합병일정")
        out["contract_date"] = kdate(after(s, "합병계약일"))
        out["record_date"] = kdate(after(s, "주주확정기준일"))
        out["egm_date"] = kdate(after(s, "주주총회예정일자"))
        out["merger_date"] = kdate(after(s, "합병기일"))
        out["register_date"] = kdate(after(s, "합병등기예정일자"))
        out["listing_date"] = kdate(after(s, "신주의 상장예정일"))
        k = next((q for q, x in enumerate(s) if x.startswith("매매거래")), None)
        out["halt_start"] = kdate(after(s[k:], "시작일")) if k is not None else None
        out["pre_shares"] = None
    return out


FIELDS = {"BONUS": ("new_shares", "record_date", "listing_date", "ratio"), "STOCK_DIV": ("new_shares", "record_date", "ratio"),
          "PAR_SPLIT": ("shares_after", "egm_date", "effective_date", "halt_start", "halt_end", "listing_date"),
          "MERGER": ("new_shares", "ratio", "egm_date", "merger_date", "register_date", "listing_date", "record_date")}


# ───────────── 합병 소멸회사(상장사) 등록 ─────────────
ALIAS = [("에이치디현대", "HD현대"), ("에이치디", "HD"), ("에스케이", "SK"), ("엘지", "LG"), ("엘에스", "LS"), ("씨제이", "CJ"), ("지에스", "GS"), ("케이티", "KT")]
EXTINCT_WATCH = "merger_extinct"


def name_variants(n):
    out = [n]
    for a, b in ALIAS:
        if a in n:
            out.append(n.replace(a, b))
    return list(dict.fromkeys(out))


def register_extinct(con):
    """합병 소멸회사가 상장사(서식 표기 또는 표기 없음)이면 KIND 에서 해석(상장폐지 종목 포함)해 issuer/security/watchlist(merger_extinct) 에 등록.
    반환: [(단축코드, 수집 시작일)] — 호출 측이 그 법인의 공시(거래정지·상장폐지)를 수집한다."""
    import kind_client as kc
    from seed_master import upsert_issuer, upsert_security
    out = []
    for f, d in [(i[2], i[3]) for t in load(con).values() if t["kind"] == "MERGER" for i in t["items"] if i[1] == "DECISION"][::-1]:
        ex = d.get("extinct")
        if not ex or "비상장" in (d.get("extinct_mkt") or ""):
            continue
        res = None
        for nm in name_variants(ex):
            r = [x for x in kc.resolve_name(nm) if x.get("secugrpId") == "ST" and x.get("comabbrv") == nm]
            if r:
                res = r[0]
                break
        if not res:
            print(f"  소멸회사 KIND 해석 실패: {ex} ({f['filing_id']})", file=sys.stderr)
            continue
        short = res["repisusrtcd"][1:]
        iss = upsert_issuer(con, res["comabbrv"], res["isurcd"])
        mkt = "KOSDAQ" if "코스닥" in (d.get("extinct_mkt") or "") else "KOSPI"
        sid = upsert_security(con, iss, "COMMON", res["comabbrv"], short, res["repisucd"], None, mkt)
        con.execute("INSERT OR IGNORE INTO watchlist VALUES (?,?,?)", (EXTINCT_WATCH, sid, NOW()))
        start = (dt.date.fromisoformat(d.get("contract_date") or f["filed_date"]) - dt.timedelta(days=15)).isoformat()
        if (short, start) not in out and short not in [o[0] for o in out]:
            out.append((short, start))
    con.commit()
    return out


# ───────────── 스레드 구성 ─────────────
def load(con):
    th = {}
    last = {}  # (kind, issuer) → 최근 스레드
    for f in con.execute("""SELECT f.*, s.issuer_id AS iss FROM filing f JOIN security s USING(security_id)
                            WHERE f.src='KIND' AND f.title IN (%s) AND f.body_path IS NOT NULL ORDER BY f.filed_at""" % ",".join("?" * len(BY_TITLE)), tuple(BY_TITLE)).fetchall():
        kind = BY_TITLE[f["title"]]
        d = parse_decision(kind, re.sub(r"[ \t]+", " ", text_of(f)))
        if d is None:
            con.execute("UPDATE filing SET parse_status='review', skip_reason='corpact_parse' WHERE filing_id=?", (f["filing_id"],))
            continue
        if kind == "MERGER" and d.get("extinct"):  # 소멸회사가 낸 같은 합병 결정 공시 → 존속회사 스레드 하나로만 본다(소멸회사는 거래정지·상장폐지만 추적)
            nm = con.execute("SELECT name FROM issuer WHERE issuer_id=?", (f["iss"],)).fetchone()[0]
            if re.sub(r"\s", "", nm) in name_variants(d["extinct"]):
                con.execute("UPDATE filing SET parse_status='parsed', skip_reason=NULL WHERE filing_id=? AND parse_status IN ('new','review')", (f["filing_id"],))
                continue
        prev = last.get((kind, f["iss"]))
        t = None
        gap = lambda p: (dt.date.fromisoformat(f["filed_date"]) - dt.date.fromisoformat(p["items"][-1][0][:10])).days
        if prev and d["amend"] and (d["amend_of"] in (None, prev["start_date"]) or d["amend_of"] == prev["start_date"]) and gap(prev) <= 200:
            t = prev                                  # 정정 → 직전 스레드
        elif prev and f["filed_date"] == prev["items"][-1][0][:10] and not d["amend"]:
            t = prev                                  # 같은 날 재공시(앞 건 오기재 정정) → 뒤 건이 최신
        if t is None:
            key = f"{CFG[kind]['prefix']}:{f['iss']}:{d['amend_of'] or f['filed_date']}"
            t = th.setdefault(key, {"key": key, "kind": kind, "issuer_id": f["iss"], "start": f["filed_at"], "start_date": d["amend_of"] or f["filed_date"], "items": [], "security_id": f["security_id"]})
        t["items"].append((f["filed_at"], "DECISION", f, d))
        last[(kind, f["iss"])] = t
    return th


def issuer_secs(con, iss):
    return [r[0] for r in con.execute("SELECT security_id FROM security WHERE issuer_id=?", (iss,))]


def attach(con, th):
    by = {}
    for t in th.values():
        by.setdefault((t["kind"], t["issuer_id"]), []).append(t)
    for l in by.values():
        l.sort(key=lambda t: t["start"])
    # ① 상장 공시(원장 행) — 같은 종류 스레드 중 계획 수량이 가장 가까운 미매칭 스레드
    matched = set()
    groups = {}
    for kind, c in CFG.items():
        for r in con.execute("""SELECT l.*, f.filed_at, f.filed_date, s.issuer_id AS iss, s.sec_type, s.name AS sname FROM share_ledger l JOIN filing f ON f.filing_id=l.source_filing_id
                                JOIN security s ON s.security_id=l.security_id WHERE l.reason=? AND l.superseded_by IS NULL ORDER BY l.effective_date""", (c["ledger"],)):
            groups.setdefault((kind, r["source_filing_id"]), []).append(dict(r))
    for (kind, fid), rows in sorted(groups.items(), key=lambda kv: kv[1][0]["filed_at"]):
        cands = [t for t in by.get((kind, rows[0]["iss"]), []) if t["start"] <= rows[0]["filed_at"] and t["key"] not in matched]
        if not cands:
            continue
        tot = sum(r["delta_shares"] or 0 for r in rows)

        def planned(t):
            d = [i for i in t["items"] if i[1] == "DECISION"][-1][3]
            return (d.get("shares_after") - d.get("shares_before")) if kind == "PAR_SPLIT" and d.get("shares_after") else (d.get("new_shares") or 0)
        pick = min(cands, key=lambda t: abs(planned(t) - tot) / (planned(t) or 1))
        matched.add(pick["key"])
        f = con.execute("SELECT * FROM filing WHERE filing_id=?", (fid,)).fetchone()
        pick["items"].append((rows[0]["filed_at"], "LISTING", f, rows))
    # ② 권리락/배당락 기준가격(m1 이벤트) · 액면분할 기준가격 · 거래정지(액면분할)
    for t in th.values():
        c = CFG[t["kind"]]
        secs = issuer_secs(con, t["issuer_id"])
        decs = [i for i in t["items"] if i[1] == "DECISION"]
        if c["ex"]:
            rec = decs[-1][3]["record_date"]
            est = ex_from_record(con, rec) if rec else None
            best = None
            for e in con.execute("""SELECT e.event_id, e.detail_json, d.the_date, d.source_filing_id FROM event e JOIN event_date d ON d.event_id=e.event_id AND d.role='EX_DATE' AND d.superseded_by IS NULL
                                    WHERE e.event_type=? AND e.security_id IN (%s)""" % ",".join("?" * len(secs)), (c["ex"], *secs)):
                dj = json.loads(e["detail_json"] or "{}")
                if c["ex_reason"] not in (dj.get("reason") or "") or not (t["start_date"] <= e["the_date"]):
                    continue
                gap = abs(tdiff(con, est, e["the_date"])) if est else 0
                if gap <= 5 and (best is None or gap < best[0]):
                    best = (gap, e, dj)
            if best:
                f = con.execute("SELECT * FROM filing WHERE filing_id=?", (best[1]["source_filing_id"],)).fetchone()
                t["items"].append((f["filed_at"], "EXNOTICE", f, {"date": best[1]["the_date"], "prices": best[2].get("prices"), "reason": best[2].get("reason")}))
        if t["kind"] == "PAR_SPLIT":
            for f in con.execute("""SELECT f.*, s.issuer_id AS iss FROM filing f JOIN security s USING(security_id) WHERE f.src='KIND' AND f.body_path IS NOT NULL AND s.issuer_id=? AND f.filed_at>=?
                                    AND (f.title LIKE '매매거래정지및정지해제(주식분할%' OR f.title='액면분할 기준가격 안내') ORDER BY f.filed_at""", (t["issuer_id"], t["start"])):
                if f["title"].startswith("매매거래정지"):
                    if not any(i[1] == "HALT" for i in t["items"]):
                        mm = re.search(r"매매거래정지일\s*\|?\s*\n?\s*([^\n|]+)", text_of(f))
                        t["items"].append((f["filed_at"], "HALT", f, kdate(mm.group(1)) if mm else None))
                else:
                    e = con.execute("SELECT e.detail_json, d.the_date FROM event e JOIN event_filing ef USING(event_id) JOIN event_date d ON d.event_id=e.event_id AND d.role='EX_DATE' AND d.superseded_by IS NULL WHERE ef.filing_id=?", (f["filing_id"],)).fetchone()
                    t["items"].append((f["filed_at"], "EXNOTICE", f, {"date": e["the_date"] if e else None, "prices": json.loads(e["detail_json"]).get("prices") if e else None, "reason": "액면분할"}))
        if t["kind"] == "MERGER":  # 소멸회사(상장사) 거래정지·상장폐지 — register_extinct 로 등록·수집된 경우
            d0 = decs[-1][3]
            ex = d0.get("extinct")
            r = None
            for nm in (name_variants(ex) if ex and "비상장" not in (d0.get("extinct_mkt") or "") else []):
                r = con.execute("SELECT security_id FROM security WHERE name=? AND sec_type='COMMON' ORDER BY security_id DESC LIMIT 1", (nm,)).fetchone()
                if r:
                    break
            if r:
                t["ext_sid"] = r["security_id"]
                for f in con.execute("""SELECT * FROM filing WHERE src='KIND' AND security_id=? AND body_path IS NOT NULL AND filed_at>=?
                                        AND (title LIKE '%매매거래정지%' OR title LIKE '상장폐지%') ORDER BY filed_at""", (r["security_id"], t["start"])):
                    txt = re.sub(r"\s+", " ", text_of(f))
                    if "합병" not in txt or "중요내용공시" in f["title"]:
                        continue
                    if f["title"].startswith("상장폐지"):
                        m = re.search(r"상장폐지일\s*\|?\s*(\d{4}-\d{2}-\d{2})", txt)
                        sh = re.search(r"(?:보통주|보통주식)\s*\|\s*([\d,]+)\s*\|", txt)
                        t["items"].append((f["filed_at"], "EXT_DELIST", f, {"date": m.group(1) if m else None, "shares": num(sh.group(1)) if sh else None}))
                    else:
                        m = re.search(r"정지(?:일시|일)\s*\|?\s*([\d년월일\- .]{8,})", txt)
                        t["items"].append((f["filed_at"], "EXT_HALT", f, {"start": kdate(m.group(1)) if m else None}))
        t["items"].sort(key=lambda x: x[0])


# ───────────── replay / finalize ─────────────
def replay(con, t, asof):
    key, kind, c = t["key"], t["kind"], CFG[t["kind"]]
    ev = con.execute("SELECT event_id FROM event WHERE thread_key=?", (key,)).fetchone()
    if ev:
        eid = ev[0]
        for tb in ("event_date", "event_filing", "index_share_adj"):
            con.execute(f"DELETE FROM {tb} WHERE event_id=?", (eid,))
    else:
        eid = con.execute("""INSERT INTO event(issuer_id,security_id,event_type,status,title,created_at,updated_at,thread_key) VALUES (?,?,?,'confirmed',?,?,?,?)""",
                          (t["issuer_id"], t["security_id"], c["etype"], c["label"], NOW(), NOW(), key)).lastrowid
    S = {"amendments": [], "sources": [], "ex": None, "listing": None, "halt": None}
    prev, first = None, True
    for at, k, f, p in t["items"]:
        fid = f["filing_id"]
        con.execute("INSERT OR IGNORE INTO event_filing VALUES (?,?,?)", (eid, fid, "initial" if (k == "DECISION" and first) else ("amend" if k == "DECISION" else "follow")))
        S["sources"].append({"filing": fid, "at": f["filed_at"], "title": f["title"]})
        if k == "DECISION":
            d = p
            if first:
                set_slot(con, eid, "RESOLUTION", d["board_date"] or f["filed_date"], 0, fid)
            set_slot(con, eid, "RECORD", d.get("record_date"), 0, fid)
            set_slot(con, eid, "EGM", d.get("egm_date"), 0, fid)
            if kind == "PAR_SPLIT":
                set_slot(con, eid, "EFFECTIVE", d["effective_date"], 0, fid)
                set_slot(con, eid, "HALT_START", d["halt_start"], 0, fid)
            if kind == "MERGER":
                set_slot(con, eid, "MERGER_DATE", d["merger_date"], 0, fid)
                set_slot(con, eid, "REGISTER", d["register_date"], 0, fid)
            if not S["listing"]:
                set_slot(con, eid, "CHANGE_LISTING" if kind == "PAR_SPLIT" else "NEW_SHARE_LISTING", d.get("listing_date"), 1, fid)
            if prev:
                ch = {q: [prev.get(q), d.get(q)] for q in FIELDS[kind] if prev.get(q) != d.get(q)}
                S["amendments"].append({"filing": fid, "at": f["filed_at"], "changes": ch})
            S["decision"], prev, first = d, d, False
        elif k == "EXNOTICE":
            S["ex"] = {"filing": fid, **p}
            set_slot(con, eid, "EX_DATE", p["date"], 0, fid)
        elif k == "HALT":
            S["halt"] = {"filing": fid, "start": p}
            set_slot(con, eid, "HALT_START", p, 0, fid)
        elif k == "EXT_HALT":
            S["ext_halt"] = {"filing": fid, "notice_date": f["filed_date"], **p}
            set_slot(con, eid, "EXT_HALT_START", p["start"], 0, fid)
        elif k == "EXT_DELIST":
            S["ext_delist"] = {"filing": fid, "notice_date": f["filed_date"], **p}
            set_slot(con, eid, "EXT_DELIST", p["date"], 0, fid)
        elif k == "LISTING":
            rows = p
            S["listing"] = {"filing": fid, "notice_date": f["filed_date"], "listing_date": rows[0]["effective_date"], "issue_date": rows[0]["issue_date"],
                            "rows": [{"security_id": r["security_id"], "name": r["sname"], "delta": r["delta_shares"], "before": r["shares_before"], "after": r["shares_after"], "ledger_id": r["ledger_id"]} for r in rows]}
            set_slot(con, eid, "ISSUE", rows[0]["issue_date"], 0, fid)
            set_slot(con, eid, "CHANGE_LISTING" if kind == "PAR_SPLIT" else "NEW_SHARE_LISTING", rows[0]["effective_date"], 0, fid)
            for r in rows:
                con.execute("UPDATE share_ledger SET event_id=? WHERE ledger_id=?", (eid, r["ledger_id"]))
    return eid, S


def anchor_ledger(con, S, kind):
    """결정 공시의 '증자전/분할전 발행주식총수'로 잔고를 모르는 상장 행의 전·후를 채운다(계산 표시). 시드가 없는 시범 종목용."""
    d, L = S["decision"], S["listing"]
    if not L:
        return
    pre = d.get("pre_shares") if kind in ("BONUS", "STOCK_DIV") else d.get("shares_before") if kind == "PAR_SPLIT" else None
    for r in L["rows"]:
        if r["before"] is None and pre and kind != "STOCK_DIV":
            con.execute("UPDATE share_ledger SET shares_before=?, shares_after=?, is_computed=1 WHERE ledger_id=?", (pre, pre + r["delta"], r["ledger_id"]))
            r["before"], r["after"] = pre, pre + r["delta"]


def finalize(con, t, eid, S, asof):
    kind, c, d = t["kind"], CFG[t["kind"]], S["decision"]
    anchor_ledger(con, S, kind)
    cur = {r["role"]: r for r in con.execute("SELECT * FROM event_date WHERE event_id=? AND superseded_by IS NULL", (eid,))}
    iss = con.execute("SELECT name FROM issuer WHERE issuer_id=?", (t["issuer_id"],)).fetchone()[0]
    L = S["listing"]
    plan = (d["shares_after"] - d["shares_before"]) if kind == "PAR_SPLIT" and d.get("shares_after") and d.get("shares_before") else d.get("new_shares")
    actual = sum(r["delta"] or 0 for r in L["rows"]) if L else None
    out = {"kind": kind, "issuer": iss, "decision": {k: v for k, v in d.items() if k not in ("amend", "amend_of")}, "planned_shares": plan, "actual_shares": actual,
           "amendments": S["amendments"], "ex": S["ex"], "halt": S["halt"], "listing": L, "sources": S["sources"]}
    if actual is not None and plan:
        out["plan_vs_actual"] = actual - plan
    if kind == "MERGER" and t.get("ext_sid") is not None:
        lst_d = cur["NEW_SHARE_LISTING"]["the_date"] if "NEW_SHARE_LISTING" in cur else None
        dl, hl = S.get("ext_delist"), S.get("ext_halt")
        et = {"security_id": t["ext_sid"], "name": d.get("extinct"), "halt": hl, "delist": dl}
        if lst_d and not (dl and dl.get("date")):
            set_slot(con, eid, "EXT_DELIST", lst_d, 1, S["sources"][0]["filing"])        # 상장폐지일 = 신주 상장일(관측 2/2)
            et["delist_est"] = lst_d
        if lst_d and not (hl and hl.get("start")):
            b = [r[0] for r in con.execute("SELECT cal_date FROM calendar_day WHERE is_trading=1 AND tseq IN (?,?,?) ORDER BY cal_date", (cal(con, lst_d, "tseq") - 18, cal(con, lst_d, "tseq") - 17, cal(con, lst_d, "tseq") - 16))]
            if b:
                et["halt_est_range"] = [b[0], b[-1]]
                set_slot(con, eid, "EXT_HALT_START", b[len(b) // 2], 1, S["sources"][0]["filing"])
        real = (dl or {}).get("date")
        if real and lst_d:
            et["delist_equals_listing"] = real == lst_d
        out["extinct_track"] = et
        cur = {r["role"]: r for r in con.execute("SELECT * FROM event_date WHERE event_id=? AND superseded_by IS NULL", (eid,))}
    # 지수 반영 시점
    eff, est, why = None, 0, None
    lst_role = "CHANGE_LISTING" if kind == "PAR_SPLIT" else "NEW_SHARE_LISTING"
    if kind in ("BONUS", "STOCK_DIV"):
        rec = d.get("record_date")
        exd = cur["EX_DATE"]["the_date"] if "EX_DATE" in cur else None
        if exd is None and rec and rec >= (d.get("board_date") or t["start_date"]):
            exd, est = ex_from_record(con, rec), 1
            set_slot(con, eid, "EX_DATE", exd, 1, S["sources"][0]["filing"])
        if exd:
            eff = exd
            why = ("무상증자: 권리락일" if kind == "BONUS" else "주식배당: 배당락일") + "에 지수 주식수 증가" + (" — 권리락/배당락 공시 전, 기준일에서 계산한 추정일" if est else "")
        else:
            eff = cur[lst_role]["the_date"] if lst_role in cur else None
            est = int(not L)
            why = "배당기준일이 결정일보다 앞서 배당락이 없음 → 신주 상장일에 증가" if kind == "STOCK_DIV" else "신주 상장일에 증가"
            out["no_ex_date"] = True
    elif kind == "PAR_SPLIT":
        eff = cur[lst_role]["the_date"] if lst_role in cur else None
        est = int(not L)
        why = "액면분할: 변경상장일에 상장주식수 × 분할비율(증가분 = 분할후 − 분할전)"
    else:
        eff = cur[lst_role]["the_date"] if lst_role in cur else None
        est = int(not L)
        why = "합병: 합병신주 상장일에 존속회사 지수 주식수 증가(= 소멸회사 상장폐지일, 관측 2/2)"
    sec = t["security_id"]
    if plan and eff and not L:
        con.execute("""INSERT INTO index_share_adj(event_id,security_id,effective_date,delta_shares,basis,is_estimated,source_filing_id,note) VALUES (?,?,?,?,?,?,?,?)""",
                    (eid, sec, eff, plan, "AS_OF_EFFECTIVE" if eff <= asof else "PLANNED", est, S["sources"][-1]["filing"], why))
    elif L and eff and kind in ("BONUS", "STOCK_DIV") and eff < L["listing_date"]:  # 권리락~상장 사이에는 실제 상장 수량으로 선반영
        con.execute("""INSERT INTO index_share_adj(event_id,security_id,effective_date,delta_shares,basis,is_estimated,source_filing_id,note) VALUES (?,?,?,?,?,?,?,?)""",
                    (eid, sec, eff, actual, "ACTUAL", est, L["filing"], why))
    out["index"] = {"effective_date": eff, "is_estimated": est, "why": why, "delta_shares": actual if L and actual is not None else plan,
                    "applied": bool(eff and eff <= asof)}
    done = bool(L) and L["listing_date"] <= asof
    h = (S["halt"] or {}).get("start") or d.get("halt_start")
    if kind == "PAR_SPLIT":
        out["status_text"] = "완료(변경상장)" if done else "변경상장 공시 후 변경상장일 대기" if L else "거래정지 중 — 변경상장 공시 대기" if h and h <= asof else "분할 일정 진행 중"
    elif kind == "MERGER" and not plan:
        mdt = d.get("merger_date")
        out["status_text"] = ("완료(합병기일 경과)" if mdt and mdt <= asof else "합병 일정 진행 중") + " — 신주 발행 없음(100% 자회사 흡수 등): 지수 주식수 영향 없음"
        done = bool(mdt and mdt <= asof)
        out["index"]["why"] = "합병신주 없음 → 지수 주식수 영향 없음"
    else:
        ex_done = bool(eff and eff <= asof and kind in ("BONUS", "STOCK_DIV") and not out.get("no_ex_date"))
        out["status_text"] = "완료(신주 상장)" if done else ("권리락/배당락 반영 · 신주 상장 대기" if ex_done else "일정 진행 중")
    con.execute("UPDATE event SET status=?, detail_json=?, updated_at=?, title=? WHERE event_id=?",
                ("done" if done else "confirmed", json.dumps(out, ensure_ascii=False, default=str), NOW(), f"{c['label']}", eid))
    for it in t["items"]:
        if it[1] == "DECISION":
            con.execute("UPDATE filing SET parse_status='parsed', skip_reason=NULL WHERE filing_id=? AND parse_status IN ('new','review','failed')", (it[2]["filing_id"],))
    return out


def run(con, asof=None):
    asof = asof or dt.date.today().isoformat()
    th = load(con)
    attach(con, th)
    for pfx in {c["prefix"] for c in CFG.values()}:
        prune(con, pfx + ":", {k for k in th if k.startswith(pfx + ":")})
    res = {}
    for key, t in th.items():
        eid, S = replay(con, t, asof)
        res[key] = (eid, finalize(con, t, eid, S, asof))
    con.commit()
    return res


if __name__ == "__main__":
    con = db.connect()
    if "--register-extinct" in sys.argv:
        print(",".join(f"{c}:{d}" for c, d in register_extinct(con)))
        sys.exit(0)
    asof = sys.argv[sys.argv.index("--asof") + 1] if "--asof" in sys.argv else None
    for k, (eid, o) in run(con, asof).items():
        print(k, eid, o["issuer"], o["kind"], o["status_text"], "계획", o["planned_shares"], "실제", o["actual_shares"], "지수", o["index"]["effective_date"], "추정" if o["index"]["is_estimated"] else "")
