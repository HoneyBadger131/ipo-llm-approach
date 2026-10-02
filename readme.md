# ipo-llm-approach

DART 공시를 수집하고 LLM으로 중요도를 판단·심화 분석하는 파이프라인 실험.

## 파이프라인
1. `dart_watchlist_filings.py` — 종목 리스트(`kospi_list_clean.md`) 기준 특정일 공시 목록 조회
2. `dart_rules.py` — 공시명 규칙 필터 (`exclude` / `separate` / `review`)
3. `dart_body.py` — 원문 다운로드 후 text body 정리
4. `judge_rules.md` — 중요도 판단 규칙 (가/부 + 태그)
5. 심화 분석 — 통과 공시를 에이전트가 OpenProxyMCP 재무 + 뉴스로 보강해 PDF 보고서 작성 (`trial_case/`)

## 메모
- **주식수 변동은 DART가 아니라 KIND 크롤링으로 별도 처리해야 함 (미구현, TODO).**
- DART 공시 기준 태그는 `사업 변동`, `기타 사항` 두 가지.
- 채무증권 신고서(회사채 등)는 판단 기준에서 제외.
- API 키는 환경 변수 `DART_API_KEY`로만 사용 (파일에 저장하지 않음).
