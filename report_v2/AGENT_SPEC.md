# V2 대시보드 에이전트 작성 지침 (확정본)

공시 1건당 한 장짜리 대시보드 JSON을 만들고 `report_v2/render.js`로 HTML·PDF·MD를 생성한다.
형식 예시: `report_v2/sample.json`, `trial_case/20260910/reports/*_v2.json`.

## 데이터 기준일 (미래 데이터 혼입 금지)
- 대상 공시일을 **기준일**로 본다(이번 실행: 2026-09-30). 기준일 이후에 생긴 데이터는 쓰지 않는다. 오늘 날짜는 더 뒤라서 도구가 최신값을 줄 수 있다.
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
corp_name, stock_code, disclosure_date, disclosure_title, rcept_no, dart_url(`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=<접수번호>`), tag, sentiment{label,reason}, headline(45자 내외), impact_summary, event_type, keywords[5~8], themes[2~3], related_ids[], kpis[3~4]{label,value,sub}, financials{basis,years["2023","2024","2025"],rows[{label,values[{v,d}]}]}(rows[0]은 막대차트 대상이라 양수 지표), valuation{items[2~4],note:""}|null, consensus|null, points[], news[], sources_note, **brief**, **importance**, **importance_reason**.

### 통합 리포트용 필드
- `brief`: 통합 리포트에 들어갈 설명. **두 줄 이내(공백 포함 90자 이내)**, 무엇이(핵심 수치) + 투자자에게 의미.
- `importance`: 1~5 정수. 같은 날 다른 종목과 상대 비교하는 척도이므로 기준을 엄격히 적용한다.
  - 5: 매출·자기자본의 10% 이상이거나 사업·지배구조·자본구조의 근본적 변화(대형 분할·합병·대규모 증자 등)
  - 4: 5~10%이거나 신사업 진출·대형 계약·대규모 주주환원
  - 3: 1~5%의 의미 있는 결정
  - 2: 1% 미만이나 알아둘 만한 이슈
  - 1: 참고
- `importance_reason`: 한 문장.

## 실행·검증
- 파일: `trial_case/<공시일>/reports/<종목코드>_<접수번호>_v2.json` (같은 이름의 html·pdf와 `disclosure_md/<공시일>/…md`가 생성됨)
- `cd /home/user/ipo-llm-approach && node report_v2/render.js <json 경로>` (render.js, to_md.js는 수정 금지. 결함은 보고)
- `pdfinfo`로 1쪽 확인, `pdftoppm -png -r 80`으로 이미지를 만들어 Read로 한글·겹침·넘침 확인(스크래치패드 사용, 파일명에 종목·접수번호를 넣을 것).
- 도구는 deferred: ToolSearch로 스키마를 먼저 로드(예: `select:mcp__OpenProxyMCP__financial_metrics,mcp__OpenProxyMCP__price_multiple_data,mcp__OpenProxyMCP__forward_estimates_data`).
- 원문 본문은 레포의 `trial_case/<공시일>/<종목코드>_<접수번호>.txt`에 있다. 긴 본문은 한 줄이 매우 길 수 있으니 python으로 구간을 잘라 읽는다.
- git 명령은 쓰지 않는다(커밋은 호출자가 한다). `DART_API_KEY`는 값을 출력·저장하지 않는다.

## 최종 응답 (간결)
산출물 경로, 공시별 impact_summary·투심·importance, 사용한 MCP 도구·호출 횟수, 기준일 규칙으로 뺀 항목, 렌더러 이슈, 확인되지 않은 항목, 가장 출력이 컸던 호출 한 줄.
