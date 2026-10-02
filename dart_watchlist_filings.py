"""종목 리스트(kospi_list_clean.md) 기준 특정일 공시 목록 조회.

그날 전체 공시를 한 번에 받아(corp_code 없이 날짜 조회) stock_code로 필터한다.
결과는 표준출력과 CSV(dart_filings_<날짜>.csv)로 저장한다.

사용법:
  export DART_API_KEY=발급키
  python dart_watchlist_filings.py 20260910 [종목리스트.md]
"""
import csv
import re
import sys

from dart_list_test import fetch_all


def load_watchlist(path):
    """마크다운 표에서 `종목코드` | 종목명 행을 읽어 {종목코드: 종목명}으로 반환."""
    out = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\|\s*\d+\s*\|\s*`(\w{6})`\s*\|\s*(.+?)\s*\|", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


if __name__ == "__main__":
    day = sys.argv[1]
    path = sys.argv[2] if len(sys.argv) > 2 else "kospi_list_clean.md"
    watch = load_watchlist(path)
    allrows = fetch_all(day, day)
    rows = [r for r in allrows if r.get("stock_code") in watch]
    rows.sort(key=lambda r: (r["stock_code"], r["rcept_no"]))

    print(f"종목 리스트 {len(watch)}개 / {day} 전체 공시 {len(allrows)}건 -> 리스트 종목 공시 {len(rows)}건"
          f" ({len({r['stock_code'] for r in rows})}개 종목)")
    for r in rows:
        print(f"{r['stock_code']} {r['corp_name']} | {r['report_nm'].strip()} | {r['rcept_no']}")

    out = f"dart_filings_{day}.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["stock_code", "corp_name", "rcept_dt", "report_nm", "rcept_no", "flr_nm", "rm", "url"])
        for r in rows:
            w.writerow([r["stock_code"], r["corp_name"], r["rcept_dt"], r["report_nm"].strip(), r["rcept_no"],
                        r["flr_nm"], r["rm"], f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}"])
    print(f"저장: {out}")
