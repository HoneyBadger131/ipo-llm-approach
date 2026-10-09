"""KIND 공시 수집기: 워치리스트 종목의 수시공시·시장조치(+ETF 전용 목록) → filing 테이블 + 본문 캐시.

범위 규칙(설계서 §2): 일반 종목은 수시공시(01)+시장조치(02)만, 선물옵션·종속회사 건은 skip. ETF는 ETF 전용 목록 전체를 적재하고 '상장신청서(수량변경)' 본문만 받는다.
멱등: 이미 있는 filing_id 는 건너뛴다. 본문 캐시: kind/data/raw/YYYY/MM/<acpt>.html

  .venv/bin/python kind/collector.py --from 2025-10-09 --to 2026-10-09 [--watch phase1|etf_core] [--no-body]
"""
import argparse
import datetime as dt
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import kind_client as kc

RAW = os.path.join(db.HERE, "data", "raw")
SKIP_RULES = [("선물옵션", lambda t: "주식선물" in t or "선물ㆍ옵션" in t or "선물·옵션" in t),
              ("종속회사", lambda t: "종속회사의 주요경영사항" in t)]
BODY_ETF = lambda t: "상장신청서" in t


def skip_reason(title):
    for name, f in SKIP_RULES:
        if f(title):
            return name
    return None


def raw_path(acpt):
    y, m = acpt[:4], acpt[4:6]
    return os.path.join(RAW, y, m, f"{acpt}.html")


def fetch_body(con, fid, acpt):
    p = raw_path(acpt)
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        h = kc.body_html(acpt)
        with open(p, "w", encoding="utf-8") as f:
            f.write(h)
    data = open(p, "rb").read()
    con.execute("UPDATE filing SET body_path=?, body_sha1=?, fetched_at=? WHERE filing_id=?",
                (os.path.relpath(p, db.HERE), hashlib.sha1(data).hexdigest(), dt.datetime.now().isoformat(timespec="seconds"), fid))


def insert(con, r, issuer_id, security_id, cat_major, sk):
    fid = "KIND:" + r["acpt_no"]
    if con.execute("SELECT 1 FROM filing WHERE filing_id=?", (fid,)).fetchone():
        return fid, False
    con.execute("""INSERT INTO filing(filing_id,src,acpt_no,filed_at,filed_date,issuer_id,security_id,company_raw,title,cat_major,skip_reason,parse_status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fid, "KIND", r["acpt_no"], r["datetime"], r["datetime"][:10], issuer_id, security_id, r["company"], r["title"],
                 cat_major, sk, "skipped" if sk else "new"))
    return fid, True


def windows(frm, to, days=330):
    """상세검색은 종목 지정 시에도 1년을 넘는 기간을 거부하는 경우가 있어 330일 이하 구간으로 나눈다."""
    a, b = dt.date.fromisoformat(frm), dt.date.fromisoformat(to)
    while a <= b:
        e = min(a + dt.timedelta(days=days), b)
        yield a.isoformat(), e.isoformat()
        a = e + dt.timedelta(days=1)


def collect_stock(con, sec, frm, to, body=True):
    codes, mj_names = kc.filing_type_codes()
    code = con.execute("SELECT code FROM security_code WHERE security_id=? AND code_type='SHORT'", (sec["security_id"],)).fetchone()[0]
    new = 0
    for mj in ("01", "02"):
        sub = "|".join(c for c, _ in codes[mj]) + "|"
        rows = []
        for w0, w1 in windows(frm, to):
            rows += kc.list_filings(code=code, frm=w0, to=w1, **{f"disclosureType{mj}": sub, f"pDisclosureType{mj}": sub})
        for r in rows:
            fid, is_new = insert(con, r, sec["issuer_id"], sec["security_id"], mj_names.get(mj, mj), skip_reason(r["title"]))
            if is_new:
                new += 1
                if body and not skip_reason(r["title"]):
                    fetch_body(con, fid, r["acpt_no"])
                    con.commit()
        con.commit()
    return new


def collect_etf(con, sec, frm, to, body=True):
    code = con.execute("SELECT code FROM security_code WHERE security_id=? AND code_type='SHORT'", (sec["security_id"],)).fetchone()[0]
    new = 0
    for r in kc.list_etf_filings(code, sec["name"], frm, to):
        fid, is_new = insert(con, r, sec["issuer_id"], sec["security_id"], "ETF", None)
        # 일괄공시는 같은 접수번호가 여러 ETF 조회에 나온다 → 대상 연결은 filing_subject 로
        con.execute("INSERT OR IGNORE INTO filing_subject VALUES (?,?)", (fid, sec["security_id"]))
        if is_new:
            new += 1
            if body and BODY_ETF(r["title"]):
                fetch_body(con, fid, r["acpt_no"])
        con.commit()
    return new


def backfill_bodies(con, limit=None, shard=(0, 1)):
    """본문이 없는 대상 filing 의 본문을 받는다(스킵·ETF 비신청서 제외). 중단 후 재실행 가능."""
    rows = con.execute("""SELECT filing_id, acpt_no, title, cat_major FROM filing
                          WHERE src='KIND' AND body_path IS NULL AND parse_status<>'skipped' ORDER BY filed_at DESC""").fetchall()
    rows = [r for r in rows if r["cat_major"] != "ETF" or BODY_ETF(r["title"])]
    rows = [r for i, r in enumerate(rows) if i % shard[1] == shard[0]]
    for i, r in enumerate(rows[:limit], 1):
        try:
            fetch_body(con, r["filing_id"], r["acpt_no"])
            con.commit()
        except Exception as e:  # 개별 실패는 기록하고 계속
            print("FAIL", r["acpt_no"], e, flush=True)
        if i % 50 == 0:
            print(f"{i}/{len(rows)}", flush=True)
    print("done", len(rows), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm")
    ap.add_argument("--to")
    ap.add_argument("--bodies-only", action="store_true")
    ap.add_argument("--shard", default="0/1", help="i/n 병렬 분할")
    ap.add_argument("--watch", default="phase1,etf_core")
    ap.add_argument("--no-body", action="store_true")
    a = ap.parse_args()
    con = db.connect()
    if a.bodies_only:
        i, n = map(int, a.shard.split("/"))
        backfill_bodies(con, shard=(i, n))
        sys.exit(0)
    if not (a.frm and a.to):
        ap.error("--from/--to 필요")
    for wl in a.watch.split(","):
        for sec in con.execute("SELECT s.* FROM watchlist w JOIN security s USING(security_id) WHERE w.watch_name=? ORDER BY 1", (wl,)).fetchall():
            if sec["sec_type"] == "PREFERRED":
                continue  # 우선주 공시는 보통주 법인 검색에 같이 나온다
            if sec["sec_type"] == "ETF":
                n = collect_etf(con, sec, a.frm, a.to, not a.no_body)
            else:
                n = collect_stock(con, sec, a.frm, a.to, not a.no_body)
            print(f"{wl} {sec['name']}: 신규 {n}", flush=True)
