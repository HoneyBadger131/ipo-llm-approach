"""ETF 추가ㆍ변경상장신청서(수량변경)(일괄공시) 파서 → etf_unit_change.

표 행: 표준코드 | 종목약명 | 신청수량(순증감) | 증감전 | 증가 | 감소 | 증감후 | 사유(설정/환매) | 추가/변경상장 예정일 | 설정·환매일
무결성 검사: 증감전 + 순증감 == 증감후, 증가 + 감소 == 순증감, 상장예정일 == 설정일의 다음 영업일(캘린더). 위반은 parse_status='review' 로 표시.
ETF 보고일은 '보고일' 셀. 행의 ETF가 처음 보이면 security 를 자동 생성(sec_type=ETF, 운용사는 이 공시를 조회해 온 대표 ETF의 운용사).

  .venv/bin/python kind/etf_parser.py [--all]     # 기본: 아직 parsed 가 아닌 것만
"""
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
from seed_master import upsert_issuer, upsert_security, sec_by_code

NUM = re.compile(r"^-?[\d,]+$")


def num(s):
    return int(s.replace(",", ""))


def cells(h):
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
        yield [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", x))).strip() for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]


def parse(h):
    """→ (report_date, [row dict])"""
    rep, rows = None, []
    allrows = list(cells(h))
    for c in allrows:
        if c and c[0] == "보고일" and len(c) > 1:
            rep = c[1]
    if rep is None:  # 보고일이 다음 행/셀에 있는 서식
        for c in allrows:
            for x in c:
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", x):
                    rep = x
                    break
            if rep:
                break
    for c in allrows:
        if len(c) >= 10 and re.match(r"KR7[0-9A-Z]{9}$", c[0]) and all(NUM.match(x) for x in (c[2], c[3], c[4], c[5], c[6])):
            rows.append(dict(isin=c[0], name=c[1], net=num(c[2]), before=num(c[3]), added=num(c[4]), removed=num(c[5]), after=num(c[6]),
                             reason=c[7], listing=c[8], create=c[9]))
    return rep, rows


def supersede(con):
    """같은 ETF·설정일·사유에 공시가 둘 이상이면 접수시각이 가장 늦은 것만 유효(앞선 것은 superseded_by). 멱등. 예: WON 신규상장 2026-08-05 15:23 공시(증감전 0)를 18:17 공시가 정정."""
    n = 0
    groups = con.execute("""SELECT security_id, create_date, reason FROM etf_unit_change WHERE superseded_by IS NULL
                            GROUP BY 1,2,3 HAVING count(*) > 1""").fetchall()
    for g in groups:
        rows = con.execute("""SELECT e.filing_id FROM etf_unit_change e JOIN filing f USING(filing_id)
                              WHERE e.security_id=? AND e.create_date=? AND e.reason=? AND e.superseded_by IS NULL ORDER BY f.filed_at, e.filing_id""", tuple(g)).fetchall()
        last = rows[-1][0]
        for (fid,) in rows[:-1]:
            con.execute("UPDATE etf_unit_change SET superseded_by=? WHERE filing_id=? AND security_id=? AND create_date=? AND reason=?", (last, fid, *g))
            n += 1
    con.commit()
    return n


def process(con, only_new=True):
    q = """SELECT f.filing_id, f.body_path, f.filed_date FROM filing f
           WHERE f.src='KIND' AND f.cat_major='ETF' AND f.title LIKE '%상장신청서%' AND f.body_path IS NOT NULL"""
    if only_new:
        q += " AND f.parse_status NOT IN ('parsed','review')"
    stats = dict(filings=0, rows=0, review=0, newsec=0)
    for f in con.execute(q).fetchall():
        h = open(os.path.join(db.HERE, f["body_path"]), encoding="utf-8").read()
        rep, rows = parse(h)
        mgr = con.execute("""SELECT s.manager FROM filing_subject fs JOIN security s USING(security_id)
                             WHERE fs.filing_id=? AND s.manager IS NOT NULL LIMIT 1""", (f["filing_id"],)).fetchone()
        mgr = mgr[0] if mgr else None
        if mgr is None:  # etf_scan.py 가 날짜 스캔으로 넣은 공시: 제출인(운용사)을 meta 에 보관
            m = con.execute("SELECT value FROM meta WHERE key=?", ("etf_mgr:" + f["filing_id"],)).fetchone()
            mgr = m[0] if m else None
        problems = []
        if not rep or not rows:
            problems.append("no_rows_or_date")
        for r in rows:
            sid = sec_by_code(con, "ISIN", r["isin"]) or sec_by_code(con, "SHORT", r["isin"][3:9])
            if sid is None:
                iss = upsert_issuer(con, r["name"])
                sid = upsert_security(con, iss, "ETF", r["name"], r["isin"][3:9], r["isin"], mgr, "KOSPI")
                stats["newsec"] += 1
            else:
                nm = con.execute("SELECT name FROM security WHERE security_id=?", (sid,)).fetchone()[0]
                if nm != r["name"]:  # 개명 (최신값으로 갱신하되 이력 보존)
                    con.execute("UPDATE security SET name=? WHERE security_id=?", (r["name"], sid))
                    con.execute("INSERT OR IGNORE INTO security_name_hist VALUES (?,?,?)", (sid, r["name"], rep or f["filed_date"]))
                if r["isin"] and not sec_by_code(con, "ISIN", r["isin"]):
                    con.execute("INSERT OR IGNORE INTO security_code(security_id,code_type,code) VALUES (?,?,?)", (sid, "ISIN", r["isin"]))
            ok = True
            if r["before"] + r["net"] != r["after"] or r["added"] + r["removed"] != r["net"]:
                ok = False
                problems.append(f"arith:{r['isin']}")
            cal = con.execute("""SELECT (SELECT tseq FROM calendar_day WHERE cal_date=?) - (SELECT tseq FROM calendar_day WHERE cal_date=?)""",
                              (r["listing"], r["create"])).fetchone()[0]
            if cal != 1:
                problems.append(f"listing_offset:{r['isin']}:{cal}")
            con.execute("""INSERT OR REPLACE INTO etf_unit_change(filing_id,security_id,report_date,create_date,listing_date,reason,
                           units_before,units_added,units_removed,net_change,units_after) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (f["filing_id"], sid, rep, r["create"], r["listing"], r["reason"], r["before"], r["added"], r["removed"], r["net"], r["after"]))
            stats["rows"] += 1
        st = "review" if problems else "parsed"
        con.execute("UPDATE filing SET parse_status=?, skip_reason=? WHERE filing_id=?", (st, ";".join(problems[:5]) or None, f["filing_id"]))
        stats["filings"] += 1
        stats["review"] += st == "review"
        con.commit()
    stats["superseded"] = supersede(con)
    return stats


if __name__ == "__main__":
    con = db.connect()
    print(process(con, only_new="--all" not in sys.argv))
