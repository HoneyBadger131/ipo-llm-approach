"""ETF 금액 환산용 가격 수집 (네이버 증권). 후보 ETF 만 일봉을 받는다.

  .venv/bin/python kind/etf_prices.py [--asof YYYY-MM-DD] [--top 40] [--offline]
1) etfItemList 한 번 호출 → etf_snapshot (전 ETF 현재가·NAV·시총·3개월수익률)
2) 후보 = 대표 8종 ∪ (1일·7일·3개월 창별 |순증감 × 스냅샷가| 상위 --top) ∪ 최근 3개월 신규 설정(증감전 0)
3) 후보별 fchart 일봉(최근 ~140영업일) → etf_price (멱등, 같은 날짜는 덮어씀)
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

UA = {"User-Agent": "Mozilla/5.0"}


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read()


def code_map(con):
    """SHORT 코드 → security_id (ETF 만)"""
    return {r[0]: r[1] for r in con.execute("""SELECT c.code, s.security_id FROM security s JOIN security_code c USING(security_id)
                                               WHERE s.sec_type='ETF' AND c.code_type='SHORT'""")}


def snapshot(con, today):
    cm = code_map(con)
    try:  # 기존 DB 이전(컬럼 추가)
        con.execute("ALTER TABLE etf_snapshot ADD COLUMN tab_code INTEGER")
    except Exception:
        pass
    items = json.loads(get("https://finance.naver.com/api/sise/etfItemList.nhn").decode("cp949", "ignore"))["result"]["etfItemList"]
    n = 0
    for it in items:
        sid = cm.get(it["itemcode"])
        if sid is None:
            continue
        con.execute("""INSERT OR REPLACE INTO etf_snapshot VALUES (?,?,?,?,?,?,?)""",
                    (sid, today, it.get("nowVal"), it.get("nav"), it.get("marketSum"), it.get("threeMonthEarnRate"), it.get("etfTabCode")))
        n += 1
    con.commit()
    return n, len(items)


def candidates(con, asof, top):
    L = con.execute("SELECT max(create_date) FROM etf_unit_change WHERE report_date<=? AND create_date<=?", (asof, asof)).fetchone()[0]
    d = dt.date.fromisoformat(L)
    y, m = d.year, d.month - 3
    if m < 1:
        m += 12; y -= 1
    lo = {"1d": L, "7d": (d - dt.timedelta(days=6)).isoformat(), "3m": dt.date(y, m, min(d.day, 28)).isoformat()}
    cand = {r[0] for r in con.execute("SELECT security_id FROM watchlist WHERE watch_name='etf_core'")}
    for k, lo_d in lo.items():
        rows = con.execute("""SELECT e.security_id, sum(e.net_change)*coalesce(s.close,0) v FROM etf_unit_change e
                              LEFT JOIN etf_snapshot s USING(security_id)
                              WHERE e.superseded_by IS NULL AND e.report_date<=? AND e.create_date BETWEEN ? AND ?
                              GROUP BY e.security_id""", (asof, lo_d, L)).fetchall()
        by = sorted(rows, key=lambda r: r[1])
        cand |= {r[0] for r in by[:top]} | {r[0] for r in by[-top:]}
    cand |= {r[0] for r in con.execute("""SELECT DISTINCT security_id FROM etf_unit_change WHERE units_before=0 AND report_date<=? AND create_date>=?""", (asof, lo["3m"]))}
    return cand, L


def prices(con, sid, code, count=140):
    t = get(f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={count}&requestType=0").decode("euc-kr", "ignore")
    rows = [(sid, f"{a[:4]}-{a[4:6]}-{a[6:]}", int(c)) for a, c in re.findall(r'data="(\d{8})\|\d+\|\d+\|\d+\|(\d+)\|', t) if int(c) > 0]
    con.executemany("INSERT OR REPLACE INTO etf_price VALUES (?,?,?)", rows)
    con.commit()
    return len(rows)


def top10(con, sid, code, today):
    d = json.loads(get(f"https://m.stock.naver.com/api/stock/{code}/etfAnalysis"))
    con.execute("DELETE FROM etf_top10 WHERE security_id=?", (sid,))
    n = 0
    for r in d.get("etfTop10MajorConstituentAssets") or []:
        try:
            w = float(str(r["etfWeight"]).replace("%", "").replace(",", ""))
        except ValueError:
            continue
        con.execute("INSERT OR REPLACE INTO etf_top10 VALUES (?,?,?,?,?,?)", (sid, r["seq"], r["itemCode"], r["itemName"], w, today))
        n += 1
    con.commit()
    return n


def stock_adv(con, code, asof, days=5):
    """종목 일봉(네이버) 최근 days 영업일(기준일 이하)의 거래량×종가 평균 = 거래대금 근사"""
    t = get(f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={days + 8}&requestType=0").decode("euc-kr", "ignore")
    rows = [(f"{a[:4]}-{a[4:6]}-{a[6:]}", int(c), int(v)) for a, c, v in re.findall(r'data="(\d{8})\|\d+\|\d+\|\d+\|(\d+)\|(\d+)"', t)]
    rows = [r for r in rows if r[0] <= asof][-days:]
    if len(rows) < days:
        return 0
    con.execute("INSERT OR REPLACE INTO stock_adv VALUES (?,?,?)", (code, asof, round(sum(c * v for _, c, v in rows) / days)))
    return 1


def main():
    a = sys.argv[1:]
    con = db.connect()
    db.apply_schema(con)
    asof = a[a.index("--asof") + 1] if "--asof" in a else dt.date.today().isoformat()
    top = int(a[a.index("--top") + 1]) if "--top" in a else 40
    n, tot = snapshot(con, asof)
    print(f"스냅샷 {n}/{tot} ETF")
    cand, L = candidates(con, asof, top)
    code = {v: k for k, v in code_map(con).items()}
    ok = fail = 0
    for sid in sorted(cand):
        try:
            prices(con, sid, code[sid]); ok += 1
        except Exception as e:  # 코드 미지원·일시 오류는 건너뜀(스냅샷가로 근사)
            fail += 1; print("  실패", code.get(sid), type(e).__name__)
        time.sleep(0.2)
    # 상위10 구성종목: 창별 순유입/유출 상위 국내 ETF 만(종목별 압력 추정용)
    import etf_flow
    d = etf_flow.build(con, asof)
    want = {sid for w in d["windows"].values() for sid in w["src_secs"]}   # 레버리지·인버스는 pressure() 가 거르므로 받아도 무해
    nt = 0
    for sid in sorted(want):
        try:
            nt += top10(con, sid, code[sid], asof) > 0
        except Exception as e:
            print("  top10 실패", code.get(sid), type(e).__name__)
        time.sleep(0.2)
    print(f"구성종목 {nt}/{len(want)} ETF")
    stocks = {o["code"] for w in etf_flow.build(con, asof, cand=True)["windows"].values() for o in w["pressure"]["cand"]}
    na = 0
    for c in sorted(stocks):
        try:
            na += stock_adv(con, c, asof)
        except Exception as e:
            print("  ADV 실패", c, type(e).__name__)
        time.sleep(0.15)
    con.commit()
    print(f"거래대금 {na}/{len(stocks)} 종목")
    print(f"후보 {len(cand)} (기준 최신 설정일 {L}) · 일봉 성공 {ok} 실패 {fail}")


if __name__ == "__main__":
    main()
