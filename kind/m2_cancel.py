"""M2 — 자기주식 소각 이벤트 스레드.

흐름: 주식 소각 결정(+정정) → [자기주식 취득(취득 후 소각형)] → 소각일 → 변경상장(주식소각) 공시 → 변경상장일(= 지수반영주식수 감소일)
지수 규칙(index_rules.py, 사용자 3원칙 ③): 자사주 소각은 *변경상장일*에 감소. 소각일과 다르다.

두 유형
  EXISTING    기취득 자기주식 소각 — 결정 공시에 소각 예정일 명시 (삼성전자·한화솔루션 우선주)
  ACQUIRE     취득 후 소각 — '소각 예정일 -', 취득 예정기간 동안 장내매수 후 일괄 소각 (SK하이닉스 2026-08)
추정 규칙(관측 4건): 변경상장 공시일 + 3영업일 = 변경상장일 (4/4 일치), 소각일 → 변경상장일 7~9영업일(중앙 8.5). 소각일을 알면 변경상장일을 '추정(범위)'로 표기.

스레드 키 'CXL:<issuer_id>:<최초 결정일>'. 재실행 시 처음부터 재구성(멱등).
  .venv/bin/python kind/m2_cancel.py [--asof YYYY-MM-DD]
"""
import datetime as dt
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
from m1_parser import kdate, text_of
from m2_decision import num, split_items, toks
from m2_rights_issue import cal, prune, set_slot, tdiff

NOW = lambda: dt.datetime.now().isoformat(timespec="seconds")
NOTICE_TO_LISTING = 3  # 변경상장 공시일 → 변경상장일 (영업일, 관측 4/4)


def after(vals, label, n=1):
    for i, v in enumerate(vals):
        if v.startswith(label):
            return vals[i + n] if i + n < len(vals) else None
    return None


def parse_cancel(text):
    out = {"amend_of": None, "amend_note": None}
    m = re.search(r"정정대상 공시서류의 최초제출일\s*:\s*\|?\s*\n?\s*([^\n|]+)", text)
    if m:
        out["amend_of"] = kdate(m.group(1))
    m = re.search(r"※\s*(금번[^\n]*?정정은[^\n]*?)(?:\n|$)", text)
    if m:
        out["amend_note"] = re.sub(r"\s+", " ", m.group(1))[:200]
    ms = list(re.finditer(r"주식 소각 결정\s*\n\s*1\.\s*소각할 주식의 종류와 수", text))
    if not ms:
        return None
    body = text[ms[-1].start():]
    it = {re.sub(r"\s+", "", l.split("(")[0]): v for l, v in split_items(toks(body)).values()}

    def item(key):
        key = re.sub(r"\s+", "", key)
        for k, v in it.items():
            if key in k:
                return v
        return []
    v = item("소각할주식의종류와수")
    out["qty_common"] = num(after(v, "보통주식")) or 0
    out["qty_pref"] = num(after(v, "종류주식")) or 0
    v = item("발행주식총수")
    out["pre_common"] = num(after(v, "보통주식"))
    out["pre_pref"] = num(after(v, "종류주식"))
    out["par"] = num((item("1주당가액") or [None])[0])
    out["amount"] = num((item("소각예정금액") or [None])[0])
    v = item("소각을위한자기주식취득예정기간")
    out["acq_start"] = kdate(after(v, "시작일")) if after(v, "시작일") not in (None, "-") else None
    out["acq_end"] = kdate(after(v, "종료일")) if after(v, "종료일") not in (None, "-") else None
    out["acq_method"] = (item("소각할주식의취득방법") or [None])[0]
    cd = (item("소각예정일") or [None])[0]
    out["cancel_date"] = kdate(cd) if cd and cd != "-" else None
    out["broker"] = (item("자기주식취득위탁투자중개업자") or [None])[0]
    out["board_date"] = kdate((item("이사회결의일") or [""])[0])
    rel = text[text.find("※관련공시"):] if "※관련공시" in text else ""
    out["related"] = [(a, re.sub(r"\s+", " ", b).strip()) for a, b in re.findall(r"(\d{4}-\d{2}-\d{2})\s+(.+?)(?=\s\d{4}-\d{2}-\d{2}\s|\s*\|?\s*$)", rel.replace("\n", " "))]
    out["type"] = "EXISTING" if out["acq_method"] and "기취득" in out["acq_method"] else "ACQUIRE"
    return out


def parse_acquire(text):
    """자기주식 취득 결정(소각 목적) — 취득 후 소각형의 취득 계획"""
    i = text.find("자기주식 취득 결정")
    it = {re.sub(r"\s+", "", l.split("(")[0]): v for l, v in split_items(toks(text[i:])).values()}
    g = lambda k: next((v for kk, v in it.items() if re.sub(r"\s+", "", k) in kk), [])
    v = g("취득예정주식")
    a = g("취득예정금액")
    p = g("취득예상기간")
    return {"shares": num(after(v, "보통주식")), "amount": num(after(a, "보통주식")), "start": kdate(after(p, "시작일")) if after(p, "시작일") not in (None, "-") else None,
            "end": kdate(after(p, "종료일")) if after(p, "종료일") not in (None, "-") else None, "purpose": (g("취득목적") or [None])[0], "method": (g("취득방법") or [None])[0],
            "broker": (g("위탁투자중개업자") or [None])[0], "daily_limit": num(after(g("1일매수주문수량한도"), "보통주식"))}


def lag_stats(con):
    """완료된 소각의 소각일 → 변경상장일 영업일 간격 (공시 1건 = 1 표본, 종목 종류별 중복 제거)"""
    lags = {}
    for r in con.execute("""SELECT l.source_filing_id fid, l.issue_date, l.effective_date, f.filed_date FROM share_ledger l JOIN filing f ON f.filing_id=l.source_filing_id
                            WHERE l.reason LIKE '변경상장(주식소각)%' AND l.issue_date IS NOT NULL"""):
        lags[r["fid"]] = (tdiff(con, r["issue_date"], r["effective_date"]), tdiff(con, r["filed_date"], r["effective_date"]))
    if not lags:
        return None
    a = sorted(x[0] for x in lags.values())
    return {"n": len(lags), "cancel_to_listing": {"min": a[0], "max": a[-1], "median": statistics.median(a)},
            "notice_to_listing": sorted(set(x[1] for x in lags.values()))}


def nth_trading(con, d, n):
    t = cal(con, d, "tseq") + n
    r = con.execute("SELECT min(cal_date) FROM calendar_day WHERE is_trading=1 AND tseq>=? AND cal_date>=?", (t, d)).fetchone()
    return r[0]


def load(con):
    th = {}
    for f in con.execute("""SELECT f.*, s.issuer_id AS iss FROM filing f JOIN security s USING(security_id)
                            WHERE f.src='KIND' AND f.title='주식 소각 결정' AND f.body_path IS NOT NULL ORDER BY f.filed_at""").fetchall():
        d = parse_cancel(re.sub(r"[ \t]+", " ", text_of(f)))
        if d is None:
            con.execute("UPDATE filing SET parse_status='review', skip_reason='cancel_parse' WHERE filing_id=?", (f["filing_id"],))
            continue
        kd = d["amend_of"] or f["filed_date"]
        key = f"CXL:{f['iss']}:{kd}"
        t = th.setdefault(key, {"key": key, "issuer_id": f["iss"], "start": f["filed_at"], "start_date": kd, "items": [], "security_id": f["security_id"]})
        t["items"].append((f["filed_at"], "DECISION", f, d))
    return th


def attach(con, th):
    by_iss = {}
    for t in th.values():
        by_iss.setdefault(t["issuer_id"], []).append(t)
    for l in by_iss.values():
        l.sort(key=lambda t: t["start"])
    matched = set()
    q = """SELECT l.*, f.filed_at, f.filed_date, s.issuer_id AS iss, s.sec_type FROM share_ledger l JOIN filing f ON f.filing_id=l.source_filing_id
           JOIN security s ON s.security_id=l.security_id WHERE l.reason LIKE '변경상장(주식소각)%' AND l.superseded_by IS NULL ORDER BY l.effective_date"""
    groups = {}
    for r in con.execute(q).fetchall():
        groups.setdefault(r["source_filing_id"], []).append(dict(r))
    for fid, rows in sorted(groups.items(), key=lambda kv: kv[1][0]["filed_at"]):
        iss = rows[0]["iss"]
        cands = [t for t in by_iss.get(iss, []) if t["start"] <= rows[0]["filed_at"] and t["key"] not in matched]
        if not cands:
            continue
        iss_date = rows[0]["issue_date"]
        pick = next((t for t in cands if any(i[3]["cancel_date"] == iss_date for i in t["items"] if i[1] == "DECISION")), None) or cands[0]
        matched.add(pick["key"])
        f = con.execute("SELECT * FROM filing WHERE filing_id=?", (fid,)).fetchone()
        pick["items"].append((rows[0]["filed_at"], "LISTING", f, rows))
    # 취득 후 소각형: 같은 날 취득결정(소각 목적)
    for t in th.values():
        dec = [i for i in t["items"] if i[1] == "DECISION"][0][3]
        if dec["type"] == "ACQUIRE":
            for f in con.execute("""SELECT f.*, s.issuer_id AS iss FROM filing f JOIN security s USING(security_id) WHERE f.src='KIND' AND f.title='자기주식 취득 결정'
                                    AND s.issuer_id=? AND f.body_path IS NOT NULL AND f.filed_date BETWEEN ? AND date(?, '+3 day')""", (t["issuer_id"], t["start_date"], t["start_date"])):
                t["items"].append((f["filed_at"], "ACQUIRE_DECISION", f, parse_acquire(text_of(f))))
    for t in th.values():
        t["items"].sort(key=lambda x: x[0])


def replay(con, t, asof, lag):
    key = t["key"]
    ev = con.execute("SELECT event_id FROM event WHERE thread_key=?", (key,)).fetchone()
    if ev:
        eid = ev[0]
        con.execute("DELETE FROM event_date WHERE event_id=?", (eid,))
        con.execute("DELETE FROM event_filing WHERE event_id=?", (eid,))
    else:
        eid = con.execute("""INSERT INTO event(issuer_id,security_id,event_type,status,title,created_at,updated_at,thread_key)
                             VALUES (?,?,'TREASURY_CANCELLATION','confirmed','자기주식 소각',?,?,?)""", (t["issuer_id"], t["security_id"], NOW(), NOW(), key)).lastrowid
    S = {"amendments": [], "sources": [], "acquire": None, "listing": None}
    prev, first = None, True
    for at, kind, f, p in t["items"]:
        fid = f["filing_id"]
        con.execute("INSERT OR IGNORE INTO event_filing VALUES (?,?,?)", (eid, fid, "initial" if (kind == "DECISION" and first) else ("amend" if kind == "DECISION" else "follow")))
        S["sources"].append({"filing": fid, "at": f["filed_at"], "title": f["title"]})
        if kind == "DECISION":
            d = p
            if first:
                set_slot(con, eid, "RESOLUTION", d["amend_of"] or d["board_date"] or f["filed_date"], 0, fid)
            set_slot(con, eid, "ACQ_START", d["acq_start"], 0, fid)
            set_slot(con, eid, "ACQ_END", d["acq_end"], 0, fid)
            set_slot(con, eid, "CANCEL_DATE", d["cancel_date"], 0, fid)
            if prev:
                ch = {k: [prev.get(k), d.get(k)] for k in ("qty_common", "qty_pref", "amount", "cancel_date", "acq_start", "acq_end") if prev.get(k) != d.get(k)}
                S["amendments"].append({"filing": fid, "at": f["filed_at"], "note": d["amend_note"], "changes": ch})
            S["decision"] = d
            prev, first = d, False
        elif kind == "ACQUIRE_DECISION":
            S["acquire"] = {"filing": fid, **p}
        elif kind == "LISTING":
            rows = p
            S["listing"] = {"filing": fid, "notice_date": f["filed_date"], "listing_date": rows[0]["effective_date"], "cancel_date": rows[0]["issue_date"],
                            "rows": [{"security_id": r["security_id"], "sec_type": r["sec_type"], "delta": r["delta_shares"], "before": r["shares_before"], "after": r["shares_after"]} for r in rows]}
            set_slot(con, eid, "CANCEL_DATE", rows[0]["issue_date"], 0, fid)
            set_slot(con, eid, "CHANGE_LISTING_NOTICE", f["filed_date"], 0, fid)
            set_slot(con, eid, "CHANGE_LISTING", rows[0]["effective_date"], 0, fid)
            for r in rows:
                con.execute("UPDATE share_ledger SET event_id=? WHERE ledger_id=?", (eid, r["ledger_id"]))
    # 변경상장일 추정(공시 전): 소각일 + 관측 간격(범위)
    cur = {r["role"]: r["the_date"] for r in con.execute("SELECT role, the_date FROM event_date WHERE event_id=? AND superseded_by IS NULL", (eid,))}
    S["estimate"] = None
    if "CHANGE_LISTING" not in cur and cur.get("CANCEL_DATE") and lag:
        lo, hi, med = lag["cancel_to_listing"]["min"], lag["cancel_to_listing"]["max"], lag["cancel_to_listing"]["median"]
        e_med = nth_trading(con, cur["CANCEL_DATE"], int(round(med)))
        S["estimate"] = {"lo": nth_trading(con, cur["CANCEL_DATE"], lo), "hi": nth_trading(con, cur["CANCEL_DATE"], hi), "mid": e_med, "basis": f"소각일 + {lo}~{hi}영업일(관측 {lag['n']}건, 중앙 {med})"}
        set_slot(con, eid, "CHANGE_LISTING", e_med, 1, S["sources"][0]["filing"])
    return eid, S


def finalize(con, t, eid, S, asof):
    d = S["decision"]
    cur = {r["role"]: r for r in con.execute("SELECT * FROM event_date WHERE event_id=? AND superseded_by IS NULL", (eid,))}
    iss_row = con.execute("SELECT name FROM issuer WHERE issuer_id=?", (t["issuer_id"],)).fetchone()
    out = {"type": d["type"], "qty_common": d["qty_common"], "qty_pref": d["qty_pref"], "pre_common": d["pre_common"], "pre_pref": d["pre_pref"],
           "pct_common": round(d["qty_common"] / d["pre_common"] * 100, 2) if d["pre_common"] and d["qty_common"] else None,
           "pct_pref": round(d["qty_pref"] / d["pre_pref"] * 100, 2) if d["pre_pref"] and d["qty_pref"] else None,
           "amount": d["amount"], "acq_method": d["acq_method"], "broker": d["broker"], "acq_start": d["acq_start"], "acq_end": d["acq_end"],
           "acquire": S["acquire"], "related": d["related"], "amendments": S["amendments"], "listing": S["listing"], "estimate": S["estimate"],
           "sources": S["sources"], "issuer": iss_row[0]}
    lst = cur.get("CHANGE_LISTING")
    out["no_listing_expected"] = False
    if S["estimate"] and not S["listing"] and asof > nth_trading(con, S["estimate"]["mid"], 10):
        # 추정 중앙값(+10영업일)을 한참 넘겼는데 변경상장 공시가 없다 → 비상장 종류주식(예: 상장폐지된 제1우선주) 소각으로 보고 지수 영향 없음 처리
        out["no_listing_expected"] = True
        set_slot(con, eid, "CHANGE_LISTING", None, 0, S["sources"][0]["filing"])
        S["estimate"] = None
        out["estimate"] = None
        lst = None
    done = bool(S["listing"]) and lst and lst["the_date"] <= asof
    out["status_text"] = "소각 완료 · 변경상장 공시 없음(비상장 종류주식 소각으로 추정 — 지수 영향 없음)" if out["no_listing_expected"] else "완료(변경상장)" if done else ("변경상장 공시 후 변경상장일 대기" if S["listing"] else ("취득 중" if d["type"] == "ACQUIRE" and d["acq_start"] and d["acq_start"] <= asof else "소각 대기"))
    con.execute("UPDATE event SET status=?, detail_json=?, updated_at=?, title=? WHERE event_id=?",
                ("done" if (done or out["no_listing_expected"]) else "confirmed", json.dumps(out, ensure_ascii=False, default=str), NOW(), f"자기주식 소각({d['type']})", eid))
    for it in t["items"]:
        if it[1] == "DECISION":
            con.execute("UPDATE filing SET parse_status='parsed', skip_reason=NULL WHERE filing_id=? AND parse_status IN ('new','review','failed')", (it[2]["filing_id"],))
    return out


def run(con, asof=None):
    asof = asof or dt.date.today().isoformat()
    th = load(con)
    attach(con, th)
    lag = lag_stats(con)
    prune(con, "CXL:", set(th))
    res = {}
    for key, t in th.items():
        eid, S = replay(con, t, asof, lag)
        res[key] = (eid, finalize(con, t, eid, S, asof))
    con.commit()
    return res, lag


if __name__ == "__main__":
    con = db.connect()
    asof = sys.argv[sys.argv.index("--asof") + 1] if "--asof" in sys.argv else None
    r, lag = run(con, asof)
    print("lag", lag)
    for k, (eid, o) in r.items():
        print(k, eid, o["issuer"], o["type"], o["qty_common"], o["qty_pref"], o["status_text"], (o["estimate"] or {}).get("mid"))
