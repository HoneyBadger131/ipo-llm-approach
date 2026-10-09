# ipo-llm-approach

DART 공시를 수집하고 LLM으로 중요도를 판단·심화 분석해, 종목별 대시보드와 통합 브리프(PDF), 인덱싱용 MD를 만드는 파이프라인 실험.

**다른 대화에서 이어 작업한다면 먼저 [`docs/HANDOFF.md`](docs/HANDOFF.md)를 읽으세요.** (목표, 현재 상태, 실행 절차, 확정된 규칙·편집 기준, 데이터 기준일 정책, 알려진 한계, 토큰 소모 실측, 후속 작업)

## 파이프라인
0. `dart_day_pipeline.py stage|brief <YYYYMMDD>` — 에이전트 입력/한 줄 프롬프트 생성, 통합 브리프 생성·점검 (실행 절차는 HANDOFF §4)
1. `dart_prep_day.py <YYYYMMDD>` — 하루치 공시 조회 → 종목 리스트(`kospi_list_clean.md`) 필터 → 규칙 필터(`dart_rules.py`) → 본문 수집(`dart_body.py`) → 판단용 digest
2. `judge_rules.md` — 중요도 판단 규칙(가/부 + 태그). 판단은 대화에서 Claude가 수행 → `trial_case/<날짜>/judgments.json`
3. 심화 분석 — 회사 단위 에이전트가 OpenProxyMCP(재무·가치평가·컨센서스·수주)와 뉴스로 보강. 지침: `report_v2/AGENT_SPEC.md`
4. `report_v2/render.js` — 대시보드 JSON → HTML/PDF(A4 1쪽) + 인덱싱용 MD(`disclosure_md/`)
5. `report_v2/render_summary.js` — 통합 브리프 PDF(중요도 상위 5건 + 표)

## Jev 분류자 시험 (`jev_test/`)
**인수인계 가이드: [`docs/DISCLOSURE_TRIAGE.md`](docs/DISCLOSURE_TRIAGE.md)** · 코드 지도: [`jev_test/README.md`](jev_test/README.md)

공시가 "다음 단계로 넘길 만큼 중요한가"를 TypeSafe Jev로 분류하는 시험. 기준: [`jev_test/공시판단_기본원칙.md`](jev_test/공시판단_기본원칙.md), 실험 설계·결과: [`jev_test/실험설계.md`](jev_test/실험설계.md).

## 메모
- 주식수 변동은 DART가 아니라 KIND 크롤링으로 별도 처리 필요(미구현, TODO). 공시 간 유사·연결 모듈도 후속 작업.
- API 키는 환경 변수 `DART_API_KEY`(없으면 git 제외된 `.env`)로 사용. 레포가 public이라 키를 커밋하지 않는다.

## 로컬(맥) 실행
`npm i playwright && npx playwright install chromium`(렌더러·PDF 변환), `uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python requests pypdf`(`pypdf`는 `report_v2/merge_pdf.py` 번들 병합용), `.env`에 `DART_API_KEY` 작성. 렌더러는 로컬 playwright를 우선 쓰고 없으면 클라우드 전역 경로로 폴백한다. 한글 폰트는 Apple SD Gothic Neo 포함.
