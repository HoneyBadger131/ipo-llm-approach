# 프로젝트 인수인계 문서 (다른 Claude Code 대화에서 이어 작업하기 위한 맥락)

작성 기준: 2026-10-02 / 브랜치 `claude/open-dart-api-disclosure-test-482bxk` (레포 `honeybadger131/ipo-llm-approach`, PR 없음)
사용자는 한국어로 소통한다. 답변·산출물도 한국어.

---

## 1. 프로젝트 목표

DART(전자공시) 공시를 매일 수집해 **중요한 공시만 골라 → 종목별 한 장짜리 대시보드(PDF/HTML)와 인덱싱용 MD로 만들고 → 전체를 요약한 통합 브리프(PDF)** 를 만드는 파이프라인 실험.

- 독자: **바쁜 투자자**. 장 전에 받아보는 것이 최종 목표(→ 주가 변동 정보는 넣지 않는다).
- 대상 종목: 코스피 290개(`kospi_list_clean.md`).
- 심화 분석은 **Claude 에이전트 + OpenProxyMCP 커넥터**(재무·가치평가·컨센서스·수주 등)로 수행.
- 후속 목표: 생성된 MD들 사이의 **유사도·연관 관계**를 찾아 새 공시 요약/핵심 포인트에 활용, 주식수 변동은 **KIND 크롤링**으로 별도 처리.

## 2. 현재 상태 (한눈에)

| 항목 | 상태 |
|---|---|
| DART 조회·종목 필터·규칙 필터·본문 수집 | 완료 (`dart_prep_day.py`) |
| 중요도 판단(가/부 + 태그) | 완료. **이 대화(Claude)가 직접 판단** — 규칙은 `judge_rules.md` |
| 심화 분석 대시보드(JSON→HTML→PDF+MD) | 완료. 회사 단위 에이전트 병렬 실행 — 지침 `report_v2/AGENT_SPEC.md` |
| 통합 브리프 PDF(TOP 5 + 표) | 완료 (`report_v2/render_summary.js`) |
| 실행 완료 날짜 | 2026-09-10(샘플 5종목), **2026-09-30(본 실행 14건)**, 2026-10-01(진행 — 상태는 §12) |
| 공시 간 연결(유사도) 모듈 | **미구현**(후속, §11) |
| KIND 크롤링(주식수 변동) | **미구현**(후속, §11) |

## 3. 레포 구조

```
readme.md                  프로젝트 개요(이 문서로 연결)
docs/HANDOFF.md            이 문서
judge_rules.md             중요도 판단 규칙 (가/부 + 태그 + 중요도 기준표)
kospi_list_clean.md        대상 종목 290개 (| 순번 | `종목코드` | 종목명 |)
dart_list_test.py          DART list.json 조회 (fetch_all: 날짜 범위 전체 페이지네이션)
dart_watchlist_filings.py  종목 리스트 로더(load_watchlist) + 단독 실행 시 CSV 저장
dart_rules.py              공시명 규칙 필터: exclude / separate / review
dart_body.py               document.xml(zip) 다운로드 → text body 정리
dart_prep_day.py           하루치 준비 단계 일괄(조회·분류·본문 저장·digest 출력)
dart_trial_case.py         (초기 시험용) 종목 여러 개의 특정일 공시 분류·본문 저장
dart_company_filings.py, dart_hd_test.py, dart_filings_20260910.csv   (초기 시험용 산출물/스크립트)
report_v2/
  AGENT_SPEC.md            에이전트 작성 지침(확정본) ← 심화 분석의 단일 기준
  render.js                대시보드 JSON → HTML/PDF(A4 1쪽) + MD 생성
  to_md.js                 JSON → 인덱싱용 MD (frontmatter + 섹션)
  render_summary.js        통합 브리프 렌더러 (TOP 5 카드 + 표)
  sample.json              JSON 형식 예시
trial_case/<YYYYMMDD>/
  prep.json                (dart_prep_day.py 산출) 단계별 건수·review 목록
  judgments.json           판정 결과(전 건, 사유 포함)
  <종목>_<접수번호>.txt    통과 공시 + 관련 공시 본문 (에이전트가 읽음)
  reports/*_v2.{json,html,pdf}   공시별 대시보드
  summary_meta.json        통합 브리프 메타(funnel, top_order)
  summary_<YYYY-MM-DD>.{html,pdf}  통합 브리프
disclosure_md/<YYYY-MM-DD>/<종목>_<접수번호>.md   인덱싱용 MD (유사도 모듈의 입력)
bodies/<YYYYMMDD>/         review 공시 전체 본문 (git 제외)
```
`trial_case/20260910/`에는 초기 V1(긴 보고서 .md/.pdf)과 V2가 함께 있다. 이후 기준은 V2(`*_v2.*`).

## 4. 실행 절차 (새 날짜 N에 대해)

환경: `DART_API_KEY` 환경변수 필요(§9). 작업 디렉터리는 레포 루트.

1. **준비**: `python dart_prep_day.py N` (예: `20261001`)
   - 전체 공시 → 종목 리스트 필터 → `dart_rules.classify` → `trial_case/N/prep.json`, `bodies/N/*.txt`, 판단용 digest 출력.
   - 소요 약 2~4분(공시 목록 11~12페이지 + 본문 수십 건). 도구 타임아웃에 걸리면 백그라운드로 실행.
2. **판단(Claude가 직접)**: digest를 읽고 `judge_rules.md` 규칙으로 가/부·태그 판단 → `trial_case/N/judgments.json` 작성(스키마는 기존 파일 참고: rcept_no, stock_code, corp_name, report_nm, proceed, tag, rules, reason, borderline?). 긴 본문은 digest만으로 부족할 수 있으니 필요하면 해당 구간을 직접 읽는다.
3. **에이전트 입력 준비**: 통과 공시 + 같은 날 관련 공시 본문을 `bodies/N/` → `trial_case/N/`로 복사(에이전트 환경에는 DART 키가 없다).
4. **심화 분석 에이전트**: **회사 단위**로 `Agent`(general-purpose) 1개씩, 6개씩 병렬. 프롬프트는 짧게: "`report_v2/AGENT_SPEC.md`를 읽고 따를 것. 기준일=N, 대상=…, 원문 경로, 판정 경로, 산출 경로, 관련 공시". 같은 회사 여러 공시는 한 에이전트가 MCP를 한 번만 조회해 JSON 여러 개를 쓴다. 에이전트는 JSON 작성 후 `node report_v2/render.js <json>`로 HTML/PDF/MD 생성·검증(1쪽, 한글).
5. **통합 브리프**: `trial_case/N/summary_meta.json`(funnel, top_order) 작성 후 `node report_v2/render_summary.js trial_case/N/reports YYYY-MM-DD trial_case/N/summary_meta.json` → `trial_case/N/summary_YYYY-MM-DD.pdf`. TOP 5는 `importance` 내림차순, 같은 회사 중복은 한 건만, 수동 순서는 `top_order`.
6. **커밋·푸시**: 이 환경은 stop-hook이 미커밋 파일을 막는다. 에이전트는 git 금지, 호출자(메인)가 커밋.

참고 사례(9/30): `trial_case/20260930/summary_2026-09-30.pdf`, `reports/`, `judgments.json`.

## 5. 규칙 필터 (`dart_rules.py`) — 확정 사항

`classify(report_nm)` → `exclude` / `separate` / `review`

- **exclude**: 투자설명서, 일괄신고추가서류, 증권발행실적보고서, IR 개최, 대량보유상황보고서, 임원·주요주주 소유상황보고서, 최대주주등 소유주식변동신고서, 계열회사 거래, 신탁계약 관련, 의결권대리행사권유참고서류, **주주총회 관련 전부(공시명에 "주주총회" 포함)**, **채무증권 신고서**, **정정 공시(`[기재정정]`·`[첨부정정]` 접두)**.
  - 정정 공시는 사용자 결정으로 일괄 제외(신규 정보가 아님). 중요한 정정이 누락될 수 있다는 단점은 인지된 상태.
  - 주주명부폐쇄·기준일 설정은 제외하지 않았다(배당 기준일일 수 있어서). 판단 단계에서 대부분 "부".
- **separate**: 사업보고서·반기보고서·분기보고서·감사보고서, 지분증권·합병·분할 증권신고서. 사용자 방침: "사업보고서처럼 중요하고 큰 문서는 **별도 처리**". 별도 처리 파이프라인은 **미구현**(예: 9/30 코스모신소재 반기보고서 1건이 대기 중).
- **review**: 그 외 전부(보수적으로 제외하지 않음).

## 6. 판단 규칙 (`judge_rules.md` 요약)

1. 절대 금액이 있으면: **30억 원 이상**이거나 **자기자본·매출 1% 이상(공시 본문에 있는 값 기준)** 이면 중요.
2. 금액이 없으면: 중요한 경영 판단 또는 미래 사업에 영향을 줄 요소.
3. 정례적·비특이 공시는 제외(재공시, 부속·중복 공시 등). 투자자 판단에 영향이 클 때만 통과.
4. 주식수 변동(0.1%↑)은 **DART가 아니라 KIND 크롤링**으로 처리(미구현). DART 단계 태그는 `사업 변동` / `기타 사항` 두 가지뿐(유상증자·자사주 소각도 DART 단계에서는 `기타 사항`).
- 사용자 결정: 30억 원 기준을 충족하는 **소규모 경계 사례도 통과**시킨다(예: LF 자사주 50억 → 중요도 1로 통과).
- `borderline: true` 로 경계 판단을 표시해 둔다(예: 중대재해 사망 1명 → 부, 지배력 상실 확인 공시 → 부).

### 중요도(importance) 기준표 (에이전트가 1~5로 기입, 통합 브리프 정렬에 사용)
5: 매출·자기자본 10%↑ 또는 사업·지배·자본구조의 근본 변화 / 4: 5~10%, 신사업·대형 계약·대규모 주주환원 / 3: 1~5% / 2: 1% 미만이나 알아둘 이슈 / 1: 참고.
같은 날 종목 간 상대 비교 척도이므로 엄격히 적용한다.

## 7. 대시보드 편집 기준 (확정, `report_v2/AGENT_SPEC.md`에 상세)

- 한 장짜리 대시보드: 헤더(종목·공시일·태그·투심) → KPI 3~4 → **핵심 포인트(한줄 영향 + 3~4개)** → 3년 실적(막대+표) | 가치평가 → 컨센서스 추이(4주) → 뉴스 링크 → 출처.
- 수치는 반올림(약 8,300억), 키 데이터만, 글은 짧고 쉽게. **뉴스는 링크만**(최대 3, 기사 요약 금지).
- **투심 태그**: 긍정적 / 부정적 / 혼재됨 / 알수 없음(색+기호로 구분).
- **넣지 않는 것**: 주가·주가 변동(장 전 제공 목표), "(계산)" 표기, "도구 이력이 ~뿐"·"시장 추정이며 공시가 아님" 같은 군더더기 주석. `valuation.note`·`consensus.note`는 빈 문자열.
- **컨센서스는 4주 기준**(§8). 커버리지가 없거나 비어 있으면 그대로 두는 것이 사용자 방침("어쩔 수 없다").
- 같은 날 합산 표현은 "금일 공시 총 투자액"처럼 명확한 기준으로.
- 통합 브리프 필드: `brief`(두 줄 이내, 90자 이내), `importance`(1~5), `importance_reason`.
- **핵심 포인트에 다른 공시와의 연계**를 넣는 것은 후속 작업(공시 연결 모듈 이후)으로 보류.

## 8. 데이터 기준일 정책 (미래 데이터 혼입 방지)

대상 공시일을 기준일로 보고 그 이후 데이터는 쓰지 않는다. 사용자 결정: **혼입 항목은 삭제**.
- `price_multiple_data`: `as_of=YYYYMMDD` 옵션 지원(주간 스냅샷 값을 돌려줌, 예: 9/30 → 9/23 스냅샷). 주가 자체는 대시보드에 안 쓰고 PER/PBR만 사용.
- `forward_estimates_data(bundle=revision)`: 주 1회 스냅샷, **제공 이력이 약 4주뿐**(13주 롤링이 최근에 쌓이기 시작). 4주 전 값은 도구가 준 변화율로 환산한 값이라 JSON `consensus.meta`에 그 사실을 적고 MD에만 노출(대시보드엔 안 보임). 증권·소형주는 커버리지 자체가 없다.
- `order_contracts`: 계약일 ≤ 기준일만 집계(해지 건은 별도 표로 나오며 차감 여부가 불명확).
- 뉴스: 게재일이 기준일 이하로 **확인되는** 기사만. URL 날짜·검색 결과 날짜로 확인. 확인 불가면 제외 → 결과적으로 뉴스가 0건인 대시보드가 생길 수 있음(9/30: 현대건설·LS·한화솔루션).
- 실서비스(장 전)에서는 이 문제가 없다. 과거 날짜 재현에서만 필요.

## 9. 환경·비밀 정보 주의

- **DART API 키**: 환경변수 `DART_API_KEY`로만 사용. 파일·커밋·출력에 넣지 않는다. (대화 중 채팅에 노출된 적이 있으므로 DART 사이트에서 재발급 권장.) **에이전트 환경에는 이 변수가 없을 수 있다** → 본문은 메인이 미리 받아 `trial_case/N/`에 두고 에이전트가 파일로 읽게 한다.
- 이 클라우드 환경은 네트워크 허용 목록 기반. `opendart.fss.or.kr`이 허용돼 있어야 한다(초기에 403으로 막혀 있었다가 사용자가 개방).
- `corpCode.xml`(약 3.6MB)은 프록시 경유로 매우 느리다(몇 분) → **쓰지 않는다**. 전체 공시를 날짜로 받아 `stock_code`로 필터하는 방식이 빠르고 충분하다.
- PDF: Node 전역 playwright(`/opt/node22/lib/node_modules/playwright`) + `/opt/pw-browsers/chromium`, 한글 폰트 WenQuanYi Zen Hei. `playwright install` 실행 금지. 렌더 후 `pdfinfo`(1쪽)·`pdftoppm -png -r 80`으로 눈으로 확인.
- `pkill -f <스크립트명>`은 자기 셸까지 죽일 수 있다(실제로 exit 144). 백그라운드 작업 대기에는 sleep 대신 Monitor(until 루프)를 쓴다.
- 셸 cwd는 호출 사이에 리셋될 수 있으니 절대경로 또는 `cd`를 명령에 포함.

## 10. DART·MCP에서 확인한 사실

- `list.json`: `corp_code` 없이 **날짜(`bgn_de`=`end_de`)만으로 전체 공시 조회 가능**, `page_count` 최대 100, `total_page`로 페이지네이션. 응답에 `stock_code` 포함 → 종목 필터는 클라이언트 측. `corp_code` 없이 3개월 초과 조회는 status 100("검색기간은 3개월만"). status 013=데이터 없음.
- `document.xml`: zip(XML/HTML) 반환. `dart_body.html_to_text`가 스타일 제거·표 행 보존·태그 제거 처리. 일부 본문은 한 줄이 매우 길다.
- OpenProxyMCP 도구(모두 deferred → ToolSearch로 스키마 로드): `company`(이름 resolve가 실패하면 ticker로 재시도), `financial_metrics`(yearly/accounts), `price_multiple_data`(firm, `as_of`), `forward_estimates_data`(bundle=revision), `order_contracts`, `business_details`(revenue_breakdown/backlog), `dilutive_issuance`, `corporate_restructuring`, `filing_section`(일부 공시는 NO_VIEWER_NODES로 실패), 그 외 다수.
- 금액 단위: 도구가 조원 단위로 반올림해 주는 경우가 있어 비율은 근사다. 응답에 없는 값은 지어내지 않는다.

## 11. 알려진 한계·후속 작업(TODO)

1. **공시 연결(유사도) 모듈** — `disclosure_md/`의 MD(frontmatter `keywords`·`themes`·`related_ids` + `검색용 요약`)를 입력으로, 공시 간 유사·상관(같은 테마, 계열사 연쇄, 반복 이슈)을 찾아 `related_ids`를 채우고 핵심 포인트에 연계 문장을 넣는다. 현재 `related_ids`는 같은 날·같은 회사 직접 관련만 수동 입력.
2. **KIND 크롤링**(주식수 변동·상장 주식수) — 미구현. 태그 `주식수 변동`은 이 단계에서 사용.
3. **separate 공시(사업보고서 등) 별도 처리** — 방식 미정(큰 문서라 `filing_section` 부분 읽기 후보).
4. **컨센서스 이력 4주 한계** — 이력이 쌓이면 자연히 길어짐. 현재 컨센서스가 비는 종목은 방치(사용자 방침).
5. **9/30 대시보드의 보완 여지**: 뉴스 0건(현대건설·LS·한화솔루션), 컨센서스 미조회(한화생명·제일기획·크래프톤·LS에코에너지 — 에이전트가 호출을 생략).
6. 정정 공시 일괄 제외로 중요한 정정이 누락될 수 있음. 긴 본문 판단 시 digest가 일부만 보여 놓치는 내용이 있을 수 있음(예: 현대모비스 "분할 후 매각").
7. DART 키 재발급, MD 중복 방지·재실행 시 덮어쓰기 정책 정리.

## 12. 토큰 소모 실측(참고)

| 작업 | 실측 |
|---|---|
| 에이전트 1개(회사 1개, MCP 3~4회 + 웹 검색 1~3회, 도구 호출 10~19회) | 6.3만~9.4만 토큰(평균 약 7.4만) |
| 9/30 본 실행: 에이전트 12개(14건) | 약 89만 |
| 9/30 판단 32건·지침·렌더러·검수(메인 대화) | 약 10만 추정 |
| 합계 | 약 100만 (사전 프로젝션 기준 시나리오 120만) |

판단 단계는 짧은 본문 약 2천 토큰/건, 긴 본문(1만 자↑) 약 8천~1만 토큰/건. 에이전트 비용의 대부분은 MCP 응답(`forward_estimates_data`, `order_contracts`, `financial_metrics` 표)과 웹 검색 결과.

## 13. 사용자 결정 이력(요약)

- 규칙 필터는 별도 파일로, 중요도 낮은 것 제외. 사업보고서류는 별도 처리.
- 주식수 변동은 KIND 크롤링(미구현). DART 태그 2종. 채무증권 신고서 제외.
- 심화 분석은 에이전트+OpenProxyMCP, 판단은 이 대화에서. V1 보고서 검수 후 **V2 대시보드**로 전환(HTML→PDF, 수치 간결, 투심 태그, 뉴스는 링크만).
- 군더더기 주석·"(계산)"·주가 변동 삭제, 컨센서스 4주, 핵심 포인트를 실적/가치평가보다 위로, 한줄 영향 요약 추가.
- 인덱싱용 MD 별도 생성(유사도 모듈 목적).
- 9/30 본 실행: 정정 공시 제외, 주주총회 관련 제외, 미래 데이터 혼입은 해당 항목 삭제, 통합 브리프(종목당 두 줄, 상위 5건 우선) PDF 생성. 소규모 경계 통과 유지. 공시 연결 모듈은 전체 보고서 생성 이후 후속.

## 14. 진행 로그

- 2026-09-10: HD현대중공업 2건, SK바이오팜 1건으로 샘플 시험(V1→V2).
- 2026-09-30: 본 실행 완료. 165건(70개 종목) → 판단 32건 → 통과 14건(12개 회사) → 대시보드 14개 + 통합 브리프.
- 2026-10-01: (아래에 진행 결과 기록)
