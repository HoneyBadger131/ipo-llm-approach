"""마스터 시드: 법인·증권·코드·워치리스트·filing_type + 주식수 시드(DART 반기보고서 기준).
멱등(재실행 안전). 주식수는 DART MCP(filing_section '주식의 총수 등')로 읽은 값을 SEED_SHARES 에 기록 — 값 갱신 시 이 파일과 근거(rcept_no)를 같이 고친다.

  .venv/bin/python kind/seed_master.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import kind_client as kc

NOW = dt.datetime.now().isoformat(timespec="seconds")

# (워치리스트, 종류, 이름, 단축코드, dart_corp_code, 운용사/비고)
STOCKS = [
    ("phase1", "COMMON", "삼성전자", "005930", "00126380", None),
    ("phase1", "PREFERRED", "삼성전자우", "005935", "00126380", None),
    ("phase1", "COMMON", "SK하이닉스", "000660", "00164779", None),
    ("phase1", "COMMON", "삼성바이오로직스", "207940", "00877059", None),
    # M2 유상증자 스레드 2번째 테스트 종목(사용자 지정). 시드 기준 동일(DART 반기 2026-06-30)
    ("phase1", "COMMON", "한화솔루션", "009830", "00162461", None),
    ("phase1", "PREFERRED", "한화솔루션우", "009835", "00162461", None),
    ("phase1", "COMMON", "SKC", "011790", "00139889", None),  # M2 유상증자 3번째 검토 종목(사용자 지정)
]
ETFS = [  # 사용자 확정 대표 8개 (코스피200 계열)
    ("KODEX 200", "069500", "삼성자산운용"), ("TIGER 200", "102110", "미래에셋자산운용"), ("RISE 200", "148020", "KB자산운용"),
    ("ACE 200", "105190", "한국투자신탁운용"), ("SOL 200TR", "295040", "신한자산운용"), ("PLUS 200", "152100", "한화자산운용"),
    ("TIME 코스피액티브", "385720", "타임폴리오자산운용"), ("HANARO 200", "293180", "NH-Amundi자산운용"),
]
# 주식수 시드: 기준 2026-06-30 '발행주식총수(Ⅳ=발행−감소)', 출처 DART 2026 반기보고서 'I.4 주식의 총수 등'. 자기주식 포함 수치(=상장주식수 근사).
SEED_SHARES = {
    "005930": (5_846_278_608, "20260814003699"),
    "005935": (802_371_203, "20260814003699"),
    "000660": (712_702_365, "20260814003509"),
    "207940": (46_290_951, "20260814003375"),
    "009830": (171_892_536, "20260814003076"),
    "009835": (2_575_349, "20260814003076"),
    "011790": (49_598_298, "20260814003336"),  # 2026-06-08 유상증자 신주 11,730,000주 상장분 포함
}
SEED_DATE = "2026-06-30"  # 영업일(화) — 반기말


def upsert_issuer(con, name, kind_isur=None, corp=None):
    if kind_isur:
        r = con.execute("SELECT issuer_id FROM issuer WHERE kind_isur_cd=?", (kind_isur,)).fetchone()
        if r:
            return r[0]
    if corp:
        r = con.execute("SELECT issuer_id FROM issuer WHERE dart_corp_code=?", (corp,)).fetchone()
        if r:
            return r[0]
    return con.execute("INSERT INTO issuer(name,kind_isur_cd,dart_corp_code) VALUES (?,?,?)", (name, kind_isur, corp)).lastrowid


def sec_by_code(con, code_type, code):
    r = con.execute("SELECT security_id FROM security_code WHERE code_type=? AND code=? AND valid_to='9999-12-31'", (code_type, code)).fetchone()
    return r[0] if r else None


def upsert_security(con, issuer_id, sec_type, name, short, isin=None, manager=None, market=None):
    sid = sec_by_code(con, "SHORT", short) or (sec_by_code(con, "ISIN", isin) if isin else None)
    if sid is None:
        sid = con.execute("INSERT INTO security(issuer_id,sec_type,name,manager,market) VALUES (?,?,?,?,?)",
                          (issuer_id, sec_type, name, manager, market)).lastrowid
        con.execute("INSERT INTO security_name_hist VALUES (?,?,?)", (sid, name, "1900-01-01"))
    for ct, c in (("SHORT", short), ("KIND_A", "A" + short), ("ISIN", isin)):
        if c:
            con.execute("INSERT OR IGNORE INTO security_code(security_id,code_type,code) VALUES (?,?,?)", (sid, ct, c))
    return sid


def isin_short(isin):
    return isin[3:9]  # KR7 + 6자리 단축코드 + 3자리 (ETF 알파뉴메릭 포함)


def pick(res, short):
    for x in res:
        if x["repisusrtcd"] == "A" + short:
            return x
    return None


def main():
    con = db.connect()
    db.apply_schema(con)
    # filing_type
    codes, majors = kc.filing_type_codes()
    for mj, lst in codes.items():
        for c, n in lst:
            con.execute("INSERT OR REPLACE INTO filing_type(cat_code,cat_major,name,module) VALUES (?,?,?,NULL)",
                        (f"{mj}.{c}", majors.get(mj, mj), n))
    # 종목
    for wl, st, name, short, corp, mgr in STOCKS:
        if st == "PREFERRED":  # KIND 자동완성은 우선주를 별도 항목으로 주지 않는다 → 법인은 보통주 것을 재사용, ISIN은 후속 공시(상장/기준가격)에서 채움
            iss = con.execute("SELECT issuer_id FROM issuer WHERE dart_corp_code=?", (corp,)).fetchone()[0]
            isin = None
        else:
            res = pick(kc.resolve_name(name), short)
            if not res:
                sys.exit(f"KIND에서 {name}({short}) 해석 실패")
            iss = upsert_issuer(con, name, res["isurcd"], corp)
            isin = res["repisucd"]
        sid = upsert_security(con, iss, st, name, short, isin, mgr, "KOSPI")
        con.execute("INSERT OR IGNORE INTO watchlist VALUES (?,?,?)", (wl, sid, NOW))
        if short in SEED_SHARES:
            n, rc = SEED_SHARES[short]
            fid = f"DART:{rc}"
            con.execute("""INSERT OR IGNORE INTO filing(filing_id,src,acpt_no,filed_at,filed_date,title,parse_status)
                           VALUES (?,?,?,?,?,?, 'skipped')""", (fid, "DART", rc, "2026-08-14 00:00", "2026-08-14", "반기보고서(2026.06) I.4 주식의 총수 등"))
            con.execute("INSERT OR IGNORE INTO share_ledger(security_id,effective_date,delta_shares,shares_after,reason,source_filing_id) VALUES (?,?,?,?,?,?)",
                        (sid, SEED_DATE, None, n, "SEED:DART반기보고서 발행주식총수(Ⅳ)", fid))
    # ETF
    for name, short, mgr in ETFS:
        res = pick(kc.resolve_name(name), short)
        if not res:
            sys.exit(f"KIND에서 {name}({short}) 해석 실패")
        iss = upsert_issuer(con, name, res["isurcd"])
        sid = upsert_security(con, iss, "ETF", name, short, res["repisucd"], mgr, "KOSPI")
        con.execute("INSERT OR IGNORE INTO watchlist VALUES ('etf_core',?,?)", (sid, NOW))
    con.commit()
    for t in ("issuer", "security", "security_code", "watchlist", "filing_type", "share_ledger"):
        print(t, con.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
    for r in con.execute("""SELECT w.watch_name, s.security_id, s.sec_type, s.name, s.manager,
        (SELECT code FROM security_code WHERE security_id=s.security_id AND code_type='SHORT') short,
        (SELECT code FROM security_code WHERE security_id=s.security_id AND code_type='ISIN') isin,
        (SELECT shares_after FROM share_ledger WHERE security_id=s.security_id) sh
        FROM watchlist w JOIN security s USING(security_id) ORDER BY 1,2"""):
        print(tuple(r))


if __name__ == "__main__":
    main()
