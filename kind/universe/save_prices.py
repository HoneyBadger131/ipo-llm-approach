"""MCP `trading_data(scope=universe, universe='코스피 시총 상위 300', format=md)` 결과(md 표)를 주간 종가 CSV 로 저장한다.

  # MCP 결과 본문을 표준입력으로 넘긴다 (헤더의 '기준 YYYYMMDD' 로 파일명 결정)
  .venv/bin/python kind/universe/save_prices.py < mcp_result.md
저장: kind/universe/prices_<YYYYMMDD>.csv (code,close) — html_report 가 '기준일 이하 가장 최근' 파일을 쓴다. 주 1회(주 마지막 거래일 스냅샷)면 충분.
"""
import os
import re
import sys

text = sys.stdin.read()
m = re.search(r"기준\s*(\d{8})", text)
if not m:
    sys.exit("헤더의 '기준 YYYYMMDD' 를 찾지 못했다")
rows = re.findall(r"\|\s*\d+\s*\|[^|]*\|\s*`(\w+)`\s*\|[^|]*\|[^|]*\|\s*([\d,]+)원\s*\|", text)
if not rows:
    sys.exit("종목 행을 찾지 못했다")
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"prices_{m.group(1)}.csv")
with open(out, "w", encoding="utf-8") as f:
    f.write("code,close\n")
    for c, p in rows:
        f.write(f"{c},{p.replace(',', '')}\n")
print(out, len(rows), "종목")
