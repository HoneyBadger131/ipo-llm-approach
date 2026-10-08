# 풀버전 대시보드 에이전트 작성 지침 (최근 3년 실적·가치평가·컨센서스 포함, 토큰 비교용)

현행 V3(`AGENT_SPEC.md`)에 **최근 3년 실적·가치평가/추정치·컨센서스 카드를 더한 버전**이다. `report_version`은 **2**로 둔다. 출력 위치는 작업 정의의 `output`(trial_case_full/…)을 따르고, 렌더는 `MD_DIR=disclosure_md_full node report_v2/render.js <json>`로 한다.

## 0. 작업 정의 읽는 법
호출 프롬프트는 "작업 정의는 `trial_case/<날짜>/agent_tasks.json` 의 stock_code=<코드[, 코드…]> 항목"이라고만 알려 준다. 그 항목을 읽어라. **종목이 여럿이면 종목별로 차례로 처리**한다(MCP 조회·뉴스 검색은 종목마다 따로, ToolSearch 스키마 로드는 한 번만). 한 종목을 끝내고 JSON·렌더를 마친 뒤 다음 종목으로 간다. 종목끼리 내용을 섞지 않는다.
- `base_date`: 기준일(= 공시일). §데이터 기준일의 모든 기준은 이 날짜.
- `filings[]`: 대시보드를 만들 공시. 각각 `body`(원문 text 경로), `reason`(판정 사유), `tag`, `note`(추가 지시), `related_with`(다른 회사의 관련 공시 접수번호), `output`(JSON 저장 경로).
- `same_day_other_filings[]`: 같은 날 같은 회사의 다른 공시(판정 "부"). 본문(`body`)이 있으면 읽고 맥락·`related_ids`에 활용(자기 자신 제외, 같은 회사 통과 공시끼리는 서로 related_ids로 연결).
- 같은 회사의 `filings`가 여러 개면 MCP 조회(재무·가치평가·컨센서스)는 한 번만 하고 JSON 여러 개를 쓴다.
- 공시명이 "(자회사의 주요경영사항)"으로 끝나면 **상장 자회사가 없어 모회사가 대신 낸 것**(자회사가 비상장)이다. 대시보드 주체는 제출자(모회사)로 하되 핵심 포인트에 어느 자회사의 일인지 밝히고, 모회사 연결 기준 영향으로 쓴다.
- DART 원문이 더 필요하면 `from dart_body import fetch_body_text`(레포 루트에서, 키는 환경변수 또는 `.env`에서 자동 로드; 값을 출력·저장하지 말 것).

## 필수 조회·검색 (생략 금지)
- `price_multiple_data`는 `as_of=<기준일 YYYYMMDD>`.
- `forward_estimates_data(bundle=revision)`는 반드시 호출. 컨센서스는 **넣을 수 있는 만큼만** 넣고 나머지는 비워 둔다(사용자 결정).
  - 커버리지가 없거나, 응답의 "현재" 스냅샷이 기준일 이후여서 기준일 이하 스냅샷이 2개 미만이면 `consensus: null`.
  - 기준일 이하 스냅샷이 2개 이상이면 그 점들만으로 series를 만든다(없는 점을 환산·보간해 채우지 않는다).
  - 영업이익 변화가 없어 의미가 없으면 EPS 등 다른 지표를 쓰고 `metric`에 명시.
- 뉴스는 WebSearch를 질의를 바꿔 **최소 2회**. 게재일이 기준일 이하로 확인되는 기사만(URL 날짜·검색 결과 날짜·WebFetch로 확인), 최대 3건. 확인되는 기사가 없으면 빈 배열.

공시 1건당 한 장짜리 대시보드 JSON을 만들고 `report_v2/render.js`로 HTML·PDF·MD를 생성한다.
형식 예시: `report_v2/sample.json`, `trial_case/20260910/reports/*_v2.json`.

## 데이터 기준일 (미래 데이터 혼입 금지)
- 대상 공시일을 **기준일**로 본다(작업 정의의 `base_date`). 기준일 이후에 생긴 데이터는 쓰지 않는다. 오늘 날짜는 더 뒤라서 도구가 최신값을 줄 수 있다.
  - **기준일 이후 스냅샷에서 나온 값은 어느 항목에도 쓰지 않는다**: 컨센서스뿐 아니라 `valuation`의 "2026E 영업이익 전망"·예상 PER, 그 값에서 파생한 비율, "변화율이 0%라 기준일 값과 같다"는 식의 추정도 금지(과거에 삼성생명·대웅제약에서 발생해 삭제함).
  - `price_multiple_data`의 주가·PER·PBR이 기준일 이후 종가 기준이면 **해당 항목을 삭제**한다(스키마에 기준일 옵션이 있고 기준일 이전 값을 받을 수 있으면 사용). `forward_estimates_data`의 스냅샷·예상 PER이 기준일 이전이면 사용 가능.
  - `order_contracts`는 계약일/공시일이 기준일 이하인 건만 집계한다. 구분이 안 되면 "올해 수주" 같은 누계 KPI를 **삭제**한다.
  - 뉴스는 **기준일 이하(당일 포함)에 게재된 것만**. 게재일이 확인되지 않거나 기준일 이후면 쓰지 않는다. 링크 날짜는 URL·검색 결과로 확인된 것만 쓴다.
  - 컨센서스는 기준일 이하의 스냅샷만 쓴다.

## 편집 기준
- 바쁜 투자자용. 수치는 반올림(예: 약 3,100억), 키 데이터 위주, 글은 짧고 쉽게(법률 용어는 풀어쓴다).
- 군더더기 주석 금지: "도구 이력이 ~뿐", "시장 추정이며 공시가 아님", "(계산)" 같은 표기를 쓰지 않는다. `valuation.note`, `consensus.note`는 "". `sources_note`는 "출처: DART 공시 원문, OpenProxyMCP(재무·가치평가·컨센서스), 뉴스 링크." (필요한 사실 보충은 한 문장까지).
- 주가·주가 변동은 넣지 않는다(장 전 제공 목표). 밸류에이션 배수는 위 기준일 규칙 안에서 사용 가능.
- 컨센서스는 4주: `{"metric","window":"최근 4주","window_label":"4주 전 대비","series":[{"label":"4주 전","v","d"},{"label":"1주 전",...},{"label":"현재",...}],"note":"","meta":"4주 전 값은 도구가 제공한 변화율로 환산한 값(주 1회 스냅샷, 제공 이력 약 4주)."}`. 환산 값이 아니면 meta 생략. 커버리지가 없으면 `consensus: null`.
- 데이터는 OpenProxyMCP 응답에 있는 값만. 없으면 항목을 뺀다(지어내지 않는다).
- 직접 계산한 비율은 표기 없이 써도 되지만 근거가 응답·공시 값이어야 한다.
- 투심 태그 `sentiment.label`: 긍정적 / 부정적 / 혼재됨 / 알수 없음 + `reason` 한 문장(40자 내외). 공시 태그 `tag`: 사업 변동 / 기타 사항 (주식수 변동은 KIND 단계에서 다룬다).
- 핵심 포인트 3~4개(type: pos/neg/unk), `impact_summary` 한 줄(45자 내외).
- 뉴스는 최대 3개: outlet, date, 짧은 title, url만. 실제 확인한 URL만.
- 같은 날 같은 회사·관계사의 직접 관련 공시는 `related_ids`에 접수번호 문자열로 넣는다.

## JSON 필드
report_version(**2 고정**), corp_name, stock_code, disclosure_date, disclosure_title, rcept_no, dart_url(`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=<접수번호>`), tag, sentiment{label,reason}, headline(45자 내외), impact_summary, event_type, keywords[5~8], themes[2~3], related_ids[], kpis[3~4]{label,value,sub}, financials{basis,years["2023","2024","2025"],rows[{label,values[{v,d}]}]}(**rows[0]=매출, rows[1]=영업이익**: 둘 다 막대로 각자 스케일로 그려진다. 영업이익이 음수면 v를 음수로 넣는다. 같은 단위(예: 조원)로 통일), valuation{items[2~4],note:""}|null, consensus|null, points[], news[], sources_note, **brief**, **importance**, **importance_reason**, **importance_score**.

### 통합 리포트용 필드
- `brief`: 통합 리포트에 들어갈 설명. **두 줄 이내(공백 포함 90자 이내)**, 무엇이(핵심 수치) + 투자자에게 의미.
- `importance`: 1~5 정수. 같은 날 다른 종목과 상대 비교하는 척도이므로 기준을 엄격히 적용한다.
  - 5: 매출·자기자본의 10% 이상이거나 사업·지배구조·자본구조의 근본적 변화(대형 분할·합병·대규모 증자 등)
  - 4: 5~10%이거나 신사업 진출·대형 계약·대규모 주주환원
  - 3: 1~5%의 의미 있는 결정
  - 2: 1% 미만이나 알아둘 만한 이슈
  - 1: 참고
  - **업종 보정(건설·조선)**: 건설·조선사의 수주는 금액이 커도 일상적인 영업이므로 낮게 매긴다. **국내 수주**는 1단계, **국내 재건축·재개발 정비사업의 시공사 선정·수주**는 2단계 낮춘다(확정 전이면 더 낮게). **해외 수주**(해외 발주처·선주)는 보정하지 않는다.
- `importance_reason`: 한 문장.
- `importance_score`: 0~100 정수. **같은 importance 안에서의 순서**를 정하는 세부 점수(규모 비율·시장 파급·불확실성·희소성 종합). 통합 브리프의 TOP 5 순서에 쓰인다. 같은 날 다른 종목과 상대 비교한다는 점을 염두에 두고 변별력 있게(예: 3점 안에서 50~85).

## 실행·검증
- 파일: `trial_case/<공시일>/reports/<종목코드>_<접수번호>_v2.json` (같은 이름의 html·pdf와 `disclosure_md/<공시일>/…md`가 생성됨)
- `cd /home/user/ipo-llm-approach && node report_v2/render.js <json 경로>` (render.js, to_md.js는 수정 금지. 결함은 보고)
- `pdfinfo`로 1쪽 확인, `pdftoppm -png -r 80`으로 이미지를 만들어 Read로 한글·겹침·넘침 확인(스크래치패드 사용, 파일명에 종목·접수번호를 넣을 것).
- 도구는 deferred: ToolSearch로 스키마를 먼저 로드(예: `select:mcp__OpenProxyMCP__financial_metrics,mcp__OpenProxyMCP__price_multiple_data,mcp__OpenProxyMCP__forward_estimates_data`).
- 원문 본문은 레포의 `trial_case/<공시일>/<종목코드>_<접수번호>.txt`에 있다. 긴 본문은 한 줄이 매우 길 수 있으니 python으로 구간을 잘라 읽는다.
- git 명령은 쓰지 않는다(커밋은 호출자가 한다). `DART_API_KEY`는 값을 출력·저장하지 않는다.

## 최종 응답 (10줄 이내, 호출자 컨텍스트 절약)
종목·접수번호별로 한 줄씩: impact_summary·투심·importance(score). 이어서 기준일 규칙으로 뺀 항목, 직접 계산·환산·역산한 수치(어느 값인지), 확인되지 않은 항목, 렌더러 이슈만 쓴다. 산출물 경로는 규칙(`reports/<종목>_<접수번호>_v2.*`)대로이므로 생략하고, MCP 호출 횟수·"가장 출력이 컸던 호출" 같은 부가 설명은 쓰지 않는다.
