# kind/universe — 유니버스·종가

- `kospi_list_clean.md` — DART 모듈의 종목 명단(우선주 제외, 시총순). KIND 확장 유니버스의 기준(= KOSPI 시총 상위 300 벤치마크).
- `prices_<YYYYMMDD>.csv` — 주간 종가(code,close). **주 1회**, MCP `trading_data(scope=universe, universe='코스피 시총 상위 300')` 결과를 `save_prices.py` 에 넘겨 저장한다(기준일 = 그 주 마지막 거래일). 리포트(`html_report.py`)는 *기준일 이하 가장 최근* 파일로 시총 변동(변동 주식수 × 종가)을 계산한다. 파일이 쌓이는 것 자체가 주간 기록이다.
- 순위 변동 기록이 필요하면 같은 호출 결과의 순위 열을 함께 저장하도록 `save_prices.py` 를 확장.
