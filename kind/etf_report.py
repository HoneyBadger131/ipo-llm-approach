"""대표 ETF 8개 설정/환매 현황 + 수집 커버리지 점검 (콘솔).

  .venv/bin/python kind/etf_report.py [--days 60]
커버리지: 영업일 중 해당 ETF 가 등장한 일괄공시가 있는 날 수. 없는 날은 '변동 없음'일 수도, 수집 누락일 수도 있어 별도 표기.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=60)
a = ap.parse_args()
con = db.connect()
last = con.execute("SELECT max(create_date) FROM etf_unit_change").fetchone()[0]
first_t = con.execute("SELECT tseq FROM calendar_day WHERE cal_date=?", (last,)).fetchone()[0] - a.days + 1
start = con.execute("SELECT min(cal_date) FROM calendar_day WHERE is_trading=1 AND tseq>=?", (first_t,)).fetchone()[0]
print(f"기준: 설정/환매일 {start} ~ {last}  (최근 {a.days} 영업일)\n")
print(f"{'ETF':<20}{'운용사':<14}{'변동일수':>8}{'설정일':>6}{'환매일':>6}{'순증감(좌)':>16}{'최신좌수':>16}{'최신일':>12}")
for r in con.execute("""
  SELECT s.security_id, s.name, s.manager FROM watchlist w JOIN security s USING(security_id) WHERE w.watch_name='etf_core' ORDER BY s.security_id"""):
    d = con.execute("""SELECT count(DISTINCT create_date) days,
          count(DISTINCT CASE WHEN reason='설정' THEN create_date END) cr, count(DISTINCT CASE WHEN reason='환매' THEN create_date END) rd,
          coalesce(sum(net_change),0) net FROM etf_unit_change WHERE security_id=? AND superseded_by IS NULL AND create_date>=?""", (r["security_id"], start)).fetchone()
    lt = con.execute("SELECT units_after, create_date FROM etf_unit_change WHERE security_id=? ORDER BY create_date DESC, filing_id DESC LIMIT 1", (r["security_id"],)).fetchone()
    print(f"{r['name']:<20}{r['manager']:<14}{d['days']:>8}{d['cr']:>6}{d['rd']:>6}{d['net']:>16,}{(lt[0] if lt else 0):>16,}{(lt[1] if lt else '-'):>12}")
print("\n영업일 중 8개 ETF 모두 변동 공시가 없는 날(실제 무변동 또는 수집 누락 — 다른 ETF 일괄공시 존재 여부로 구분):")
miss = con.execute("""SELECT cal_date FROM calendar_day c WHERE is_trading=1 AND cal_date BETWEEN ? AND ?
                      AND NOT EXISTS (SELECT 1 FROM etf_unit_change e WHERE e.create_date=c.cal_date)""", (start, last)).fetchall()
print([m[0] for m in miss] or "없음")
