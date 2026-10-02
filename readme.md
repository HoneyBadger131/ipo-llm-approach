# ipo-llm-approach

DART 공시를 수집하고 LLM으로 중요도를 판단·심화 분석해, 종목별 대시보드와 통합 브리프(PDF), 인덱싱용 MD를 만드는 파이프라인 실험.

**다른 대화에서 이어 작업한다면 먼저 [`docs/HANDOFF.md`](docs/HANDOFF.md)를 읽으세요.** (목표, 현재 상태, 실행 절차, 확정된 규칙·편집 기준, 데이터 기준일 정책, 알려진 한계, 토큰 소모 실측, 후속 작업)

## 파이프라인
1. `dart_prep_day.py <YYYYMMDD>` — 하루치 공시 조회 → 종목 리스트(`kospi_list_clean.md`) 필터 → 규칙 필터(`dart_rules.py`) → 본문 수집(`dart_body.py`) → 판단용 digest
2. `judge_rules.md` — 중요도 판단 규칙(가/부 + 태그). 판단은 대화에서 Claude가 수행 → `trial_case/<날짜>/judgments.json`
3. 심화 분석 — 회사 단위 에이전트가 OpenProxyMCP(재무·가치평가·컨센서스·수주)와 뉴스로 보강. 지침: `report_v2/AGENT_SPEC.md`
4. `report_v2/render.js` — 대시보드 JSON → HTML/PDF(A4 1쪽) + 인덱싱용 MD(`disclosure_md/`)
5. `report_v2/render_summary.js` — 통합 브리프 PDF(중요도 상위 5건 + 표)

## 메모
- 주식수 변동은 DART가 아니라 KIND 크롤링으로 별도 처리 필요(미구현, TODO). 공시 간 유사·연결 모듈도 후속 작업.
- API 키는 환경 변수 `DART_API_KEY`로만 사용(파일에 저장하지 않음).
