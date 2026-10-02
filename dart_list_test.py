"""Open DART 공시검색(list.json) 테스트.

확인 사항
  1) corp_code 없이 특정일(bgn_de=end_de)의 전체 공시를 페이지네이션으로 모두 가져올 수 있는가
  2) 그 결과에서 원하는 종목(종목코드 6자리)만 걸러낼 수 있는가
     - (a) 전체 목록에서 stock_code로 클라이언트 필터
     - (b) corpCode.xml로 stock_code -> corp_code 변환 후 corp_code 지정 조회

사용법:
  export DART_API_KEY=발급키
  python dart_list_test.py 20251001 005930
"""
import io
import os
import sys
import xml.etree.ElementTree as ET
import zipfile

import requests

BASE = "https://opendart.fss.or.kr/api"
def _load_key():
    """DART_API_KEY: 환경변수 우선, 없으면 레포 루트의 .env(git 제외)에서 읽는다."""
    k = os.environ.get("DART_API_KEY")
    if k:
        return k
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env):
        for line in open(env, encoding="utf-8"):
            if line.strip().startswith("DART_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    raise KeyError("DART_API_KEY 환경변수가 없습니다 (환경 설정 또는 .env)")


KEY = _load_key()


def list_page(**params):
    r = requests.get(f"{BASE}/list.json", params={"crtfc_key": KEY, **params}, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_all(bgn_de, end_de, **extra):
    """페이지네이션 전체 수집. status 013 = 조회된 데이터 없음."""
    rows, page = [], 1
    while True:
        j = list_page(bgn_de=bgn_de, end_de=end_de, page_no=page, page_count=100, **extra)
        if j["status"] == "013":
            break
        if j["status"] != "000":
            raise RuntimeError(f"DART error {j['status']}: {j.get('message')}")
        rows += j["list"]
        if page >= j["total_page"]:
            break
        page += 1
    return rows


def stock_to_corp_code(stock_code):
    r = requests.get(f"{BASE}/corpCode.xml", params={"crtfc_key": KEY}, timeout=60)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        root = ET.fromstring(z.read(z.namelist()[0]))
    for e in root.iter("list"):
        if (e.findtext("stock_code") or "").strip() == stock_code:
            return e.findtext("corp_code")
    return None


if __name__ == "__main__":
    day, stock = sys.argv[1], sys.argv[2]

    # 1) 특정일 전체 공시 (corp_code 없음)
    first = list_page(bgn_de=day, end_de=day, page_count=100)
    print(f"[1] {day} status={first['status']} total_count={first.get('total_count')} "
          f"total_page={first.get('total_page')}")
    allrows = fetch_all(day, day)
    print(f"    수집 건수: {len(allrows)}")
    if allrows:
        print("    샘플 필드:", sorted(allrows[0].keys()))

    # 2a) 클라이언트 필터
    mine = [r for r in allrows if r.get("stock_code") == stock]
    print(f"[2a] stock_code={stock} (전체목록 필터): {len(mine)}건")
    for r in mine:
        print("    ", r["rcept_dt"], r["report_nm"], r["rcept_no"])

    # 2b) corp_code로 서버 필터
    cc = stock_to_corp_code(stock)
    print(f"[2b] corp_code={cc}")
    if cc:
        rows = fetch_all(day, day, corp_code=cc)
        print(f"     corp_code 지정 조회: {len(rows)}건 (2a와 일치: {len(rows) == len(mine)})")

    # 부가: 기간 제한 확인 (corp_code 없이 3개월 초과 시 에러 기대)
    j = list_page(bgn_de="20250101", end_de="20251001", page_count=1)
    print(f"[3] corp_code 없이 9개월 조회: status={j['status']} message={j.get('message')}")
