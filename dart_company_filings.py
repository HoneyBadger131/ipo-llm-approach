"""특정일 전체 공시 조회 -> 특정 종목 필터 -> 공시 원문(document.xml) 출력.

사용법:
  export DART_API_KEY=발급키
  python dart_company_filings.py 20260910 329180
"""
import io
import os
import re
import sys
import zipfile

import requests

from dart_list_test import fetch_all, BASE, KEY


def fetch_document_text(rcept_no, max_chars=3000):
    """document.xml(zip) 다운로드 후 태그를 제거한 본문 텍스트 일부를 반환."""
    r = requests.get(f"{BASE}/document.xml", params={"crtfc_key": KEY, "rcept_no": rcept_no}, timeout=120)
    r.raise_for_status()
    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
    except zipfile.BadZipFile:  # 에러는 XML 본문으로 내려옴
        return r.content.decode("utf-8", "replace")[:500]
    raw = z.read(z.namelist()[0]).decode("utf-8", "replace")
    text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", text).strip()[:max_chars]


if __name__ == "__main__":
    day, stock = sys.argv[1], sys.argv[2]
    allrows = fetch_all(day, day)
    print(f"[1] {day} 전체 공시: {len(allrows)}건", flush=True)

    mine = [r for r in allrows if r.get("stock_code") == stock]
    print(f"[2] stock_code={stock} 공시: {len(mine)}건", flush=True)
    for r in mine:
        print(f"\n=== {r['corp_name']} | {r['rcept_dt']} | {r['report_nm'].strip()} | rcept_no={r['rcept_no']} | 제출인={r['flr_nm']}")
        print(f"    https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r['rcept_no']}")
        print("    ", fetch_document_text(r["rcept_no"]), flush=True)
