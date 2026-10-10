"""M1 파서: 시장조치 공시 → share_ledger(주식수 원장) / event(+event_date).

처리 서식 (제목 기준)
  변경상장(…) / 추가상장(…)           → share_ledger  (변경상장일 = effective_date, 발행·소각일 = issue_date)
  … 기준가격 안내 (권리락/배당락/액면/분할) → event (EX_DATE, 기준가격은 detail_json)
  매매거래정지(및정지해제)(…)          → event HALT (HALT_START / HALT_END, 해제일이 '변경상장일' 같은 조건이면 condition_note)
그 외 시장조치(투자경고·공매도과열 등)는 M3 대상이라 여기서는 건드리지 않고 미처리 목록으로만 보고한다.
정지해제 조건 해소: 변경상장 본문의 '매매거래정지가 해제됨' → 같은 종목의 열린 HALT 의 HALT_END 를 변경상장일로 확정.

  .venv/bin/python kind/m1_parser.py [--all]
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import kind_client as kc

NOW = lambda: dt.datetime.now().isoformat(timespec="seconds")
TODAY = dt.date.today().isoformat()


def text_of(f):
    return kc._html_to_text(open(os.path.join(db.HERE, f["body_path"]), encoding="utf-8").read())


def kdate(s):
    m = re.search(r"(\d{4})\D{0,2}(\d{1,2})\D{0,2}(\d{1,2})", s or "")
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def num(s):
    return int(s.replace(",", ""))


def cls_of(label):
    return "PREFERRED" if "우" in label else "COMMON"


def sec_by_short(con, short):
    r = con.execute("SELECT security_id FROM security_code WHERE code_type='SHORT' AND code=?", (short,)).fetchone()
    return r[0] if r else None


def sibling(con, issuer_id, sec_type):
    r = con.execute("SELECT security_id FROM security WHERE issuer_id=? AND sec_type=?", (issuer_id, sec_type)).fetchone()
    return r[0] if r else None


def ensure_isin(con, sid, isin):
    if isin and not con.execute("SELECT 1 FROM security_code WHERE code_type='ISIN' AND code=?", (isin,)).fetchone():
        con.execute("INSERT INTO security_code(security_id,code_type,code) VALUES (?,?,?)", (sid, "ISIN", isin))


# ───────────── 변경상장 / 추가상장 ─────────────
def parse_listing(con, f, text):
    kind = "추가상장" if (f["title"].startswith("추가상장") or f["title"].startswith("상장안내(보통주 추가상장")) else "변경상장"
    reason = f["title"]
    eff = kdate(re.search(r"(?:변경)?상장일\s*:\s*([^\n]+)", text).group(1)) if re.search(r"(?:변경)?상장일\s*:", text) else None
    iss = re.search(r"발행일[^:\n]*:\s*([^\n]+)", text)
    issue = kdate(iss.group(1)) if iss else None
    if not issue:  # 발행일이 여러 줄('- 2026년08월03일 : 35주' …)로 나열되는 서식(BW 행사 등): 가장 이른 날짜
        m = re.search(r"발행일[^\n]*\n((?:\s*-\s*\d{4}년\s*\d{1,2}월\s*\d{1,2}일[^\n]*\n?)+)", text)
        if m:
            ds = sorted(kdate(x) for x in re.findall(r"(\d{4}년\s*\d{1,2}월\s*\d{1,2}일)", m.group(1)))
            issue = ds[0] if ds else None
    if not issue:  # '발행일' 아래 ▶ 줄에 날짜가 오는 서식
        m = re.search(r"발행일\s*\n\s*▶[^\n]*?(\d{4}년\s*\d{1,2}월\s*\d{1,2}일)", text)
        issue = kdate(m.group(1)) if m else None
    detail = None
    mb = re.search(r"③\s*발행일[^\n]*\n(.*?)(?=\n\s*④)", text, re.S)
    if mb:  # 발행일별 수량: '- 2026년08월03일 : 35주' 또는 '2025년10월27일(15,595주)'
        pairs = re.findall(r"(\d{4}년\s*\d{1,2}월\s*\d{1,2}일)\s*(?::\s*|\(\s*)([\d,]+)주", mb.group(1))
        detail = [[kdate(a_), num(b_)] for a_, b_ in pairs] or None
        if detail and not issue:
            issue = min(d_[0] for d_ in detail)
    # 표준코드: '▶ [보통주|1우선주] 표준코드 : KR7... (단축코드:A....)' 또는 단일 '▶ 표준코드 : …'
    codes = re.findall(r"(?:▶\s*([^\n▶]*?)\s*)?표준코드\s*:\s*(KR7\w{9})\s*\(단축코드:A(\w{6})\)", text)
    rows = []
    if kind == "변경상장":
        for m in re.finditer(r"기명식\s*(\S*주)\s*([\d,]+)주\s*(?:→|->)\s*([\d,]+)주\s*(?:\([^)]*\))?\s*\n\s*▶\s*변경주식수\s*:\s*(-?[\d,]+)주", text):
            rows.append(dict(cls=cls_of(m.group(1)), label=m.group(1), before=num(m.group(2)), after=num(m.group(3)), delta=num(m.group(4))))
    else:
        for m in re.finditer(r"주식의 종류와 수\s*:\s*기명식\s*(\S*주)\s*(?:총\s*)?([\d,]+)주", text):
            rows.append(dict(cls=cls_of(m.group(1)), label=m.group(1), before=None, after=None, delta=num(m.group(2))))
    if kind == "추가상장" and not rows:  # 회차별 여러 줄('-기명식 보통주 6,202주 (제92회)' …, 스톡옵션 행사 등): 종류별 합산
        mm = re.search(r"주식의 종류와 수\s*\n((?:\s*-\s*기명식[^\n]*\n?)+)", text)
        if mm:
            tot = {}
            for lab, n_ in re.findall(r"기명식\s*(\S*주)\s*([\d,]+)주", mm.group(1)):
                tot[lab] = tot.get(lab, 0) + num(n_)
            rows = [dict(cls=cls_of(l_), label=l_, before=None, after=None, delta=v_) for l_, v_ in tot.items()]
    if not (eff and rows):
        return "review", f"listing_fields eff={eff} rows={len(rows)}"
    # 종류별 코드 해석: 코드가 1개면 그 코드, 2개 이상이면 라벨(우선주 여부)로
    by_cls, by_label = {}, {}
    for lab, isin, short in codes:
        by_cls[cls_of(lab) if len(codes) > 1 else None] = (isin, short)
        key = re.sub(r"\s+|표준코드|▶", "", lab or "")
        if key:
            by_label[key] = (isin, short)  # '보통주' / '1우선주' / '3우선주' 처럼 우선주 종류가 여러 개인 공시를 구분
    done = 0
    for r in rows:
        lk = re.sub(r"\s+", "", r["label"])
        isin, short = by_label.get(lk) or by_cls.get(r["cls"]) or by_cls.get(None) or (None, None)
        sid = sec_by_short(con, short) if short else None
        if sid is None:
            continue  # 워치리스트 밖 종목
        ensure_isin(con, sid, isin)
        con.execute("""INSERT OR IGNORE INTO share_ledger(security_id,effective_date,delta_shares,shares_before,shares_after,issue_date,reason,source_filing_id,issue_detail)
                       VALUES (?,?,?,?,?,?,?,?,?)""", (sid, eff, r["delta"], r["before"], r["after"], issue, reason, f["filing_id"], json.dumps(detail) if detail else None))
        done += 1
        if "매매거래정지가 해제" in text:  # 분할 변경상장일 해제 조건 해소
            close_halts(con, sid, eff, f["filing_id"])
    return ("parsed", None) if done else ("skipped", "not_in_watchlist")


def parse_merger_listing(con, f, text):
    """'상장안내(합병/상호변경)' = 추가상장(합병) + 변경상장(상호변경) 합본 서식 → 추가상장(합병) 행. 합병 후 총수는 변경상장 블록의 '주식의 종류와 수'."""
    m = re.search(r"추가상장.*?주식의 종류와 수\s*:\s*기명식\s*(\S*주)\s*([\d,]+)주.*?발행일\s*:\s*([^\n]+).*?상장일\s*:\s*([^\n]+).*?단축코드:A(\w{6})", text, re.S)
    if not m:
        return "review", "merger_listing_fields"
    sid = sec_by_short(con, m.group(5))
    if sid is None:
        return "skipped", "not_in_watchlist"
    tot = re.search(r"변경상장.*?주식의 종류와 수\s*\n?\s*-?\s*기명식\s*\S*주\s*([\d,]+)주", text, re.S)
    delta, aft = num(m.group(2)), (num(tot.group(1)) if tot else None)
    con.execute("""INSERT OR IGNORE INTO share_ledger(security_id,effective_date,delta_shares,shares_before,shares_after,issue_date,reason,source_filing_id)
                   VALUES (?,?,?,?,?,?,'추가상장(합병)',?)""", (sid, kdate(m.group(4)), delta, (aft - delta) if aft else None, aft, kdate(m.group(3)), f["filing_id"]))
    return "parsed", None


def close_halts(con, sid, eff, src):
    """조건부 해제일(예: '변경상장일')이 걸린 HALT 의 HALT_END 를 확정일로 대체한다. 기존 값은 superseded_by 로 이력 보존."""
    for (eid,) in con.execute("""SELECT e.event_id FROM event e JOIN event_date d ON d.event_id=e.event_id AND d.role='HALT_END' AND d.superseded_by IS NULL
                                 WHERE e.security_id=? AND e.event_type='HALT' AND d.condition_note IS NOT NULL""", (sid,)).fetchall():
        old = con.execute("SELECT event_date_id FROM event_date WHERE event_id=? AND role='HALT_END' AND superseded_by IS NULL", (eid,)).fetchone()[0]
        new = con.execute("INSERT INTO event_date(event_id,role,the_date,is_estimated,source_filing_id) VALUES (?,?,?,0,?)", (eid, "HALT_END_NEW", eff, src)).lastrowid
        con.execute("UPDATE event_date SET superseded_by=? WHERE event_date_id=?", (new, old))
        con.execute("UPDATE event_date SET role='HALT_END' WHERE event_date_id=?", (new,))
        con.execute("UPDATE event SET status='done', updated_at=? WHERE event_id=?", (NOW(), eid))
        con.execute("INSERT OR IGNORE INTO event_filing VALUES (?,?,?)", (eid, src, "follow"))


# ───────────── 기준가격 안내 ─────────────
EVENT_BY_REASON = [("권배락", "RIGHTS_EX"), ("주식배당", "DIVIDEND_EX"), ("권리락", "RIGHTS_EX"), ("배당락", "DIVIDEND_EX"), ("액면", "PAR_VALUE_CHANGE"), ("분할", "SPLIT_RELIST_PRICE"),
                   ("병합", "PAR_VALUE_CHANGE"), ("감자", "CAPITAL_REDUCTION_PRICE"), ("합병", "MERGER_PRICE")]


def sections(text):
    """'1. 회사명 | …' 처럼 번호로 시작하는 항목 → {번호: (라벨, 본문)}"""
    parts = re.split(r"\n\s*(?=\d\.\s*\S)", "\n" + text)
    out = {}
    for p in parts:
        m = re.match(r"(\d)\.\s*([^|\n]*)", p.strip())
        if m:
            out[int(m.group(1))] = (m.group(2).strip(), p.strip()[m.end():])
    return out


def clean_vals(body):
    return [x.strip() for x in re.split(r"[|\n]", body) if x.strip()]


def parse_ref_price(con, f, text):
    sec = sections(text)
    by_label = {lab: body for lab, body in sec.values()}
    reason = next((clean_vals(b)[0] for l, b in by_label.items() if l.startswith("사유")), None)
    adate = next((kdate(b) for l, b in by_label.items() if l.startswith("적용일")), None)
    price_body = next((b for l, b in by_label.items() if l.startswith(("주권종류", "주식의 종류"))), "")
    vals = clean_vals(price_body)
    prices = []  # [(종류, [값…])] — '보통주식 1,418,000' / 분할은 평가가격·최고·최저 3개
    cur = None
    HEAD = ("주권종류", "기준가격(원)", "평가가격(원)", "최고호가(원)", "최저호가(원)")
    for v in vals:
        if re.fullmatch(r"[\d,]+", v):
            if cur:
                cur[1].append(num(v))
        elif v not in HEAD:
            cur = [v, []]
            prices.append(cur)
    if not (reason and adate and prices):
        return "review", f"refprice_fields reason={reason} date={adate} prices={len(prices)}"
    etype = next((t for k, t in EVENT_BY_REASON if k in reason), "REF_PRICE")
    # 대상 증권: 제목의 (…우) 표기 또는 주권종류에 우선주만 있으면 우선주
    base = f["security_id"]
    iss = con.execute("SELECT issuer_id FROM security WHERE security_id=?", (base,)).fetchone()[0]
    sid = base
    if re.search(r"우\)\s*$", f["title"]) or all("우" in p[0] for p in prices):
        sid = sibling(con, iss, "PREFERRED") or base
    detail = json.dumps({"reason": reason, "prices": [{"class": p[0], "values": p[1]} for p in prices]}, ensure_ascii=False)
    status = "done" if adate <= TODAY else "confirmed"
    if con.execute("SELECT 1 FROM event_filing WHERE filing_id=?", (f["filing_id"],)).fetchone():
        return "parsed", None
    eid = con.execute("""INSERT INTO event(issuer_id,security_id,event_type,status,title,detail_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)""",
                      (iss, sid, etype, status, f["title"], detail, NOW(), NOW())).lastrowid
    con.execute("INSERT INTO event_date(event_id,role,the_date,is_estimated,source_filing_id) VALUES (?,?,?,0,?)", (eid, "EX_DATE", adate, f["filing_id"]))
    con.execute("INSERT INTO event_filing VALUES (?,?,?)", (eid, f["filing_id"], "initial"))
    return "parsed", None


# ───────────── 매매거래정지 및 정지해제 ─────────────
def parse_halt(con, f, text):
    flat = re.sub(r"\s+", " ", text)
    st = re.search(r"매매거래정지일\s*\|?\s*([^|]*?)\s*\|", flat)
    en = re.search(r"매매거래정지해제일\s*\|?\s*([^|]*?)\s*\|", flat)
    why = re.search(r"매매거래정지\(해제\)사유\s*\|?\s*(.*?)\s*5\.", flat)
    start = kdate(st.group(1)) if st else None
    end_raw = en.group(1).strip() if en else None
    end = kdate(end_raw) if end_raw else None
    intraday = None
    if not start:  # 장중 정지 서식(중요내용공시 등): '3. 매매거래정지 일시 | 2025-05-22 | 07:45' / '4. 매매거래정지 해제일시 | … | 09:30'
        a_ = re.search(r"매매거래정지 일시\s*\|?\s*(\d{4}-\d{2}-\d{2})\s*\|?\s*(\d{2}:\d{2})", flat)
        b_ = re.search(r"매매거래정지 해제일시\s*\|?\s*(\d{4}-\d{2}-\d{2})\s*\|?\s*(\d{2}:\d{2})", flat)
        if a_ and b_:  # 공시 시각 ~ 다음 날 장개시(예: 2025-07-01 15:34 ~ 07-02 09:00)도 포함
            start, end, end_raw = a_.group(1), b_.group(1), None
            intraday = f"{a_.group(2)}~{b_.group(2)}" if a_.group(1) == b_.group(1) else f"{a_.group(1)} {a_.group(2)}~{b_.group(1)} {b_.group(2)}"
            why = re.search(r"매매거래정지 사유\s*\|?\s*(.*?)\s*6\.", flat)
    if not start:  # 코스닥식 서식: '3.정지기간 가.정지일시 | 2023-12-18 | - | 나.만료일시 | -' (사유: '2.정지사유 | …')
        k_ = re.search(r"정지일시\s*\|?\s*(\d{4}-\d{2}-\d{2})", flat)
        if k_:
            start, end, end_raw = k_.group(1), None, "별도 공시(만료일시 미정)"
            why = re.search(r"정지사유\s*\|?\s*(.*?)\s*3\.", flat)
    if not start:
        return "review", "halt_start_missing"
    if con.execute("SELECT 1 FROM event_filing WHERE filing_id=?", (f["filing_id"],)).fetchone():
        return "parsed", None
    iss = con.execute("SELECT issuer_id FROM security WHERE security_id=?", (f["security_id"],)).fetchone()[0]
    detail = json.dumps({"reason": why.group(1).strip(" -|") if why else None, "end_raw": end_raw, "intraday": intraday}, ensure_ascii=False)
    eid = con.execute("""INSERT INTO event(issuer_id,security_id,event_type,status,title,detail_json,created_at,updated_at) VALUES (?,?,'HALT',?,?,?,?,?)""",
                      (iss, f["security_id"], "done" if (end and end <= TODAY) else "confirmed", f["title"], detail, NOW(), NOW())).lastrowid
    con.execute("INSERT INTO event_date(event_id,role,the_date,is_estimated,source_filing_id) VALUES (?,?,?,0,?)", (eid, "HALT_START", start, f["filing_id"]))
    if end:
        con.execute("INSERT INTO event_date(event_id,role,the_date,is_estimated,source_filing_id) VALUES (?,?,?,0,?)", (eid, "HALT_END", end, f["filing_id"]))
    elif end_raw:  # 조건부 해제일 ('변경상장일' …) — 날짜는 시작일로 두고 조건 표기, 후속 공시로 확정
        con.execute("INSERT INTO event_date(event_id,role,the_date,is_estimated,condition_note,source_filing_id) VALUES (?,?,?,1,?,?)",
                    (eid, "HALT_END", start, end_raw, f["filing_id"]))
    con.execute("INSERT INTO event_filing VALUES (?,?,?)", (eid, f["filing_id"], "initial"))
    return "parsed", None


HANDLERS = [
    (re.compile(r"^(변경상장|추가상장)\(|^상장안내\(보통주 추가상장"), parse_listing),
    (re.compile(r"^상장안내\(합병"), parse_merger_listing),
    (re.compile(r"기준가격"), parse_ref_price),
    (re.compile(r"^(주권)?매매거래정지"), parse_halt),
]


def seed_adjust(con, sid):
    """시드(DART 반기 '발행주식총수')는 *발행일* 기준이라, 시드일까지 발행됐지만 시드일 이후에 상장되는 주식이 이미 포함돼 있다
    (예: 엘앤에프 BW 행사 7/9·7/20 상장분이 6/30 발행주식총수에 포함). 원장은 *상장일* 기준이므로 그만큼 뺀 값을 시드의 상장주식수로 쓴다."""
    s = con.execute("SELECT * FROM share_ledger WHERE security_id=? AND reason LIKE 'SEED:%' ORDER BY ledger_id LIMIT 1", (sid,)).fetchone()
    if not s:
        return
    meta = json.loads(s["issue_detail"]) if s["issue_detail"] else {}
    dart = meta.get("dart", s["shares_after"])
    adj = 0
    for r in con.execute("SELECT delta_shares, issue_date, issue_detail FROM share_ledger WHERE security_id=? AND superseded_by IS NULL AND effective_date>? AND reason NOT LIKE 'SEED:%' AND delta_shares>0",
                         (sid, s["effective_date"])):
        if r["issue_detail"]:
            adj += sum(q for d_, q in json.loads(r["issue_detail"]) if d_ <= s["effective_date"])
        elif r["issue_date"] and r["issue_date"] <= s["effective_date"]:
            adj += r["delta_shares"]
    con.execute("UPDATE share_ledger SET shares_after=?, issue_detail=? WHERE ledger_id=?",
                (dart - adj, json.dumps({"dart": dart, "issued_not_listed": adj}), s["ledger_id"]))


def fill_chain(con):
    """원장 체인 완성: 공시에 before/after 가 없는 행(추가상장)은 직전 잔고에서 계산. 반환: 불일치 목록."""
    problems = []
    for (sid,) in con.execute("SELECT DISTINCT security_id FROM share_ledger").fetchall():
        # 계산으로 채웠던 값은 매번 처음부터 다시 계산(새 공시가 추가돼도 이전 계산값이 남지 않게)
        con.execute("UPDATE share_ledger SET shares_before=NULL, shares_after=NULL, is_computed=0 WHERE security_id=? AND is_computed=1", (sid,))
        # 같은 변경상장(소각 등)을 날짜·수량 그대로 다시 공시한 경우(오기재 재공시) → 앞 건을 뒤 건이 대체
        con.execute("""UPDATE share_ledger SET superseded_by=(SELECT b.ledger_id FROM share_ledger b WHERE b.security_id=share_ledger.security_id AND b.effective_date=share_ledger.effective_date
                         AND b.reason=share_ledger.reason AND b.delta_shares=share_ledger.delta_shares AND b.shares_before IS share_ledger.shares_before AND b.shares_after IS share_ledger.shares_after
                         AND b.source_filing_id<>share_ledger.source_filing_id AND b.ledger_id>share_ledger.ledger_id AND b.superseded_by IS NULL)
                       WHERE security_id=? AND superseded_by IS NULL AND reason LIKE '변경상장%' AND EXISTS (SELECT 1 FROM share_ledger b WHERE b.security_id=share_ledger.security_id AND b.effective_date=share_ledger.effective_date
                         AND b.reason=share_ledger.reason AND b.delta_shares=share_ledger.delta_shares AND b.shares_before IS share_ledger.shares_before AND b.shares_after IS share_ledger.shares_after
                         AND b.source_filing_id<>share_ledger.source_filing_id AND b.ledger_id>share_ledger.ledger_id AND b.superseded_by IS NULL)""", (sid,))
        seed_adjust(con, sid)
        rows = con.execute("SELECT * FROM share_ledger WHERE security_id=? AND superseded_by IS NULL ORDER BY effective_date, ledger_id", (sid,)).fetchall()
        bal = None
        for r in rows:
            if r["reason"].startswith("SEED:"):
                if bal is not None and bal != r["shares_after"]:
                    problems.append((sid, r["effective_date"], "seed_mismatch", bal, r["shares_after"]))
                bal = r["shares_after"]
                continue
            before, after, comp = r["shares_before"], r["shares_after"], r["is_computed"]
            if before is None and bal is not None:
                before, comp = bal, 1
            if after is None and before is not None and r["delta_shares"] is not None:
                after, comp = before + r["delta_shares"], 1
            if bal is not None and r["shares_before"] is not None and r["shares_before"] != bal:
                problems.append((sid, r["effective_date"], "chain_break", bal, r["shares_before"]))
            if (before, after, comp) != (r["shares_before"], r["shares_after"], r["is_computed"]):
                con.execute("UPDATE share_ledger SET shares_before=?, shares_after=?, is_computed=? WHERE ledger_id=?", (before, after, comp, r["ledger_id"]))
            bal = after if after is not None else bal
        # 역방향 보완: 시드(또는 뒤쪽 행) 잔고가 알려진 경우, 앞쪽의 잔고 미상 행을 증감에서 거꾸로 계산 (예: 시드 이전의 추가상장)
        rows = con.execute("SELECT * FROM share_ledger WHERE security_id=? AND superseded_by IS NULL ORDER BY effective_date, ledger_id", (sid,)).fetchall()
        nxt = None
        for r in reversed(rows):
            if r["reason"].startswith("SEED:"):
                nxt = r["shares_after"]
                continue
            after, before, comp = r["shares_after"], r["shares_before"], r["is_computed"]
            if after is None and nxt is not None and r["delta_shares"] is not None:
                after, comp = nxt, 1
            if before is None and after is not None and r["delta_shares"] is not None:
                before, comp = after - r["delta_shares"], 1
            if (before, after, comp) != (r["shares_before"], r["shares_after"], r["is_computed"]):
                con.execute("UPDATE share_ledger SET shares_before=?, shares_after=?, is_computed=? WHERE ledger_id=?", (before, after, comp, r["ledger_id"]))
            nxt = before if before is not None else nxt
    return problems


def run(con, only_new=True):
    q = """SELECT * FROM filing WHERE src='KIND' AND cat_major='시장조치' AND body_path IS NOT NULL"""
    if only_new:
        q += " AND parse_status IN ('new','failed','review')"
    stats = {"parsed": 0, "review": 0, "skipped": 0, "unhandled": []}
    for f in con.execute(q + " ORDER BY filed_at").fetchall():
        h = next((fn for rx, fn in HANDLERS if rx.search(f["title"])), None)
        if h is None:
            stats["unhandled"].append((f["filed_date"], f["title"]))
            continue
        try:
            st, why = h(con, f, text_of(f))
        except Exception as e:  # 파서 오류는 review 로 남기고 계속
            st, why = "failed", f"{type(e).__name__}: {e}"
        con.execute("UPDATE filing SET parse_status=?, skip_reason=? WHERE filing_id=?", (st, why, f["filing_id"]))
        stats[st if st in stats else "review"] += 1
        con.commit()
    stats["chain_problems"] = fill_chain(con)
    con.commit()
    return stats


if __name__ == "__main__":
    con = db.connect()
    s = run(con, only_new="--all" not in sys.argv)
    print({k: (v if k not in ("unhandled", "chain_problems") else f"{len(v)}건") for k, v in s.items()})
    for u in s["unhandled"]:
        print("  미처리(M3 등):", u)
    for p in s["chain_problems"]:
        print("  ⚠", p)
