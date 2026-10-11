# KIND 축 인수인계 (새 세션용) — 2026-10-11 (오버뷰·리팩터링 반영)

사용자는 한국어로 소통한다. **이 문서가 KIND 축의 단일 진입점**이다(세부는 아래 링크). DART 축 인수인계는 [`HANDOFF.md`](HANDOFF.md).
브랜치 `claude/open-dart-api-disclosure-test-482bxk`. 커밋은 로컬 `git log` 확인 — **푸시는 사용자가 렌더링된 리포트를 확인한 뒤**에 한다.

## 1. 목표 (한 문단)
프로젝트 두 번째 축 = **Index expert(가칭)**: KRX KIND(거래소 공시)로 *주식수 변동·일정·조치*를 영업일 단위로 추적해 리포트. 벤치마크는 **KOSPI 시총 상위 300(보통주)**. 핵심 질문 하나 — **"지수 주식수가 언제, 얼마나 바뀌는가"**. 설계 [`KIND_DESIGN.md`](KIND_DESIGN.md), 지수 규칙 [`KIND_INDEX_METHOD.md`](KIND_INDEX_METHOD.md), 리포트 사양 [`KIND_REPORT.md`](KIND_REPORT.md), M2 이벤트 스레드 [`KIND_M2.md`](KIND_M2.md), 파일 지도 [`../kind/README.md`](../kind/README.md).

## 2. 현재 상태
| 모듈 | 상태 | 코드 · 문서 |
|---|---|---|
| 메인 캘린더(영업일, 휴장 보정, 2015~2040) | ✅ | `build_calendar.py`, 설계서 6.1 |
| 수집(종목별 `collector.py` · **날짜 단위 `scan_range.py`**)·본문 캐시·오프라인 재생성 | ✅ | `kind_client.py`, `rebuild_all.sh`, [`KIND_DESIGN.md`](KIND_DESIGN.md) 3절 |
| M5 ETF 설정/해지(대표 8종) | ✅ | `etf_parser.py`, `etf_report.py` |
| M1 시장조치 → 주식수 원장·기준가·정지 | ✅ | `m1_parser.py`, [`KIND_M1_M3.md`](KIND_M1_M3.md) |
| M3 투자경고·공매도·거래정지 기간 | ✅(투자위험·단기과열 서식 미관측) | `m3_parser.py` |
| M2 유상증자(주주배정=권리락일, 제3자·공모=신주 상장일) | ✅ | `m2_rights_issue.py`, [`KIND_M2.md`](KIND_M2.md) 1절 |
| M2 자기주식 소각(변경상장일; 취득 프로그램 단위) | ✅ | `m2_cancel.py`, [`KIND_M2.md`](KIND_M2.md) 2절 |
| M2 CB/BW(전환·행사 상장 + 잔여 희석) | ✅ | `m2_cbbw.py` |
| M2 인적분할(신설법인 자동 등록, 계산→재상장 공시 덮어쓰기) | ✅ | `m2_split.py`, [`KIND_M2.md`](KIND_M2.md) 4절 |
| M2 무상증자·주식배당·액면분할·합병(+소멸회사 상장폐지 추적) | ✅ | `m2_corp_actions.py`, [`KIND_M2.md`](KIND_M2.md) 5절 |
| 종목 확장(시총 상위 300, 292종목 등록) | ✅ | `scan_range.py`, `kind/universe/` |
| 누락 최초 공시 보충 · 관리종목 표지 · 자기주식 취득 진행 | ✅ | `backfill_orphans.py`, `status_flags.py`, `buyback.py` |
| 자기주식 *실제* 취득 진행(체결내역 누적금액·속도·예상 소진일) → 소각 변경상장 예정일 보정 | ✅ | `buyback_exec.py`(`buyback_exec` 테이블), `buyback.progress/projection` |
| HTML 리포트(4탭) | ✅ 사용자 확인·푸시 완료(마크다운 리포트는 폐지) | `html_report.py` + `html_report_template.html`, [`KIND_REPORT.md`](KIND_REPORT.md) |
| 유/무상감자 · 물적분할 · 주식병합 · M4 대량매매 | ⏳ 미구현 | 설계서 M4 |

## 3. 파이프라인과 운영
**재생성**(처음부터, 모두 멱등): `./kind/rebuild_all.sh <FROM=2025-01-01> <TO>` — 캘린더 → 시드 → 종목별 수집(phase1·시범) → 신설·소멸 법인 등록·수집 → **유니버스 등록 + 날짜 스캔(2025-07-01~)** → **자기주식 체결내역(2026-06-01~)** → 누락 원본 보충 → 관리종목 상태 → ETF → m1 → m3 → m2_rights_issue → m2_cancel → m2_cbbw → m2_split → m2_corp_actions → html_report.
- `KIND_OFFLINE=1` — 네트워크 없이 캐시(kind/data/cache·raw)만으로 동일 재생성. **`TO` 를 명시해야 한다**(기본값 '오늘'이라 날짜가 바뀌면 캐시 키가 달라져 실패). 마지막 온라인 실행 `TO`=2026-10-10.
- `m2_cbbw.py` 의 전환·행사 현황 조회(KIND 신고사항)는 '오늘'이 구간에 들어가 오프라인 재현이 안 된다 → 재생성 후 **온라인으로 `m2_cbbw.py` 한 번** 더(없으면 해당 스레드는 리포트에서 빠진다).
- 환경: 레포 `.venv`(requests, exchange_calendars, holidays, pypdf), 항상 `.venv/bin/python`. Playwright 는 `node_modules`(리포트 렌더 확인용).

**일일 운영 루틴** (1~4단계는 `kind/run_kind_daily.py` 로 자동화됨 — DART 일일 실행(`run_daily.py`)이 백그라운드로 호출, 수동 실행: `.venv/bin/python kind/run_kind_daily.py --asof <영업일>`; 설계·테스트는 [`KIND_DART_INTEGRATION.md`](KIND_DART_INTEGRATION.md) 7절)
1. (주 1회) 종가 갱신(+ 삼성전자·SK하이닉스 일별 시세 `kind/universe/bb_quotes.json` 최근 10거래일 — MCP `trading_data(scope=quote, company=…, as_of=YYYYMMDD)`): MCP `trading_data(scope=universe, universe='코스피 시총 상위 300', format=md)` → 결과를 `kind/universe/save_prices.py` 에 표준입력으로 → `prices_<기준일>.csv` 누적(기록 겸용).
2. `scan_range.py --from <마지막 스캔일+1> --to <어제>` (하루 ~5콜, 거래일 1일 ≈ 5~10초) → `buyback_exec.py --from <마지막+1> --to <어제>`(자기주식 체결내역, 하루 1건 ≈ 1콜).
3. `backfill_orphans.py` → `status_flags.py --to <어제>`
4. `m1_parser.py` → `m2_*` 5개 → (온라인) `m2_cbbw.py` → `html_report.py <날짜>`
5. 상위 이벤트의 '왜'·뉴스·리스크·메모를 `kind/news.json` 에 사람이 추가(기준일 이하 게재 기사, 날짜·매체 확인).
6. 사용자 확인 후 커밋·푸시.

**회귀 도구 `kind/regress.py`**(리팩터링 전후 비교의 정본): `snap <이름> [DB경로]` 로 전 테이블 내용 해시(시각 컬럼·event_date/designation id 제외)를 `kind/data/regress/<이름>.json` 에 저장, `diff <이름>` 으로 현재 DB 와 비교(다른 행 표시, 종료코드 1), `html <파일>` 은 `generated` 시각을 뺀 HTML 해시. 기준선은 `data/` 에 있어 새 환경엔 없다 — 첫 재생성 직후 `snap base2` 로 만든 뒤 변경 후 `diff base2`. **현재 기준선 `base2`**(2026-10-11, 신설·소멸 법인 자동 등록 반영 재생성) HTML 해시(기준일 10-08) `1d7832848262582d`. 주의: 보조 키(`security_id`·`event_id`)는 등록 순서에 따라 달라져 *증분(일일 작업) DB 와 재생성 DB 는 내용이 같아도 해시가 다르다* — 비교는 같은 경로끼리(재생성↔재생성).
**회귀 기준(2026-10-11, 재생성 base2)**: filing 4,377 · share_ledger 436(활성 434) · event 542 · event_date 1,625 · event_filing 932 · designation 76 · index_share_adj 31 · etf_unit_change 54,454 · security 1,225 · status_flag 1 · buyback_exec 3,780행(88거래일) · review/failed 1(키움증권 주식의종류변경) · FK/무결성 OK · 원장 체인 불일치 0 · M2 모듈 반복 실행 시 행 수 불변. 워치리스트: etf_core 8 · phase1 15 · k200_pilot 6 · merger_extinct **6**(신규 대한항공←아시아나·HD현대중공업←HD현대미포·한일시멘트←한일현대시멘트 소멸회사) · **universe 291**. *이전 재생성은 합병 소멸회사 등록이 유니버스 스캔보다 앞서 일부를 놓쳤다 → 등록 블록을 스캔 뒤에 한 번 더 둠.*
`kind/data/`(DB·캐시·본문, 약 200MB)는 git 제외. 처음 클론한 환경은 온라인 재생성 1회 필요 — **이때 요청이 많으니 천천히**(5절).

## 4. 설계 대원칙 (원칙만 지킨다)
1. 날짜는 전부 `calendar_day`(휴장 반영) FK. 영업일 연산은 조인(`tseq`)으로만.
2. 종목 PK = 대리키 `security_id`, 코드는 `security_code` 이력. 법인(`issuer`)과 증권 분리. **우선주는 다루지 않는다**(리포트·시총·소각 수량에서 제외).
3. 공시 PK = `filing_id` = `KIND:<접수번호>` / `DART:<접수번호>`. 파생 사실은 모두 근거 `filing_id`.
4. 스레드는 시간순 *replay* 로 매번 재구성(`thread_key` 로 같은 event_id 유지, 안 쓰는 스레드 `prune`). **같은 법인·같은 방식·같은 최초 결정일의 후속(정정·재결정) 공시는 가장 최근 공시가 앞 값을 덮어쓴다.** 정정 이력은 diff 로만 남긴다.
5. **실제 주식수 반영은 변경상장·추가상장·재상장 공시가 뜰 때만**(원장 `share_ledger`). 공시 전 값은 `index_share_adj`(PLANNED)로 선반영하고, 상장 공시가 원장에 들어오면 원장이 대체한다. 계산값(신설법인 주식수 등)은 상장 공시 수치가 나오면 덮어쓴다.
6. 모든 적재 단계는 멱등. 스키마 변경은 마이그레이션 대신 DB 재생성.
7. 스레드 키 날짜 = **접수번호의 날짜**(시간외 접수는 KIND 목록 일시가 다음 영업일이라 `filed_date` 와 다르다).
8. 주의력은 한정 자원 — 리포트에는 지수 주식수에 직접 닿는 것만. 나머지는 DB 에만(리포트 사양 [`KIND_REPORT.md`](KIND_REPORT.md)).

## 5. 사용자 결정 로그 (시간순, 뒤집지 말 것)
| 일자 | 결정 |
|---|---|
| 10-10 | 지수 규칙 3원칙(신규상장일·권리락일·변경상장일) + 분할: 존속 변경상장일 감소, 신설은 별개 종목(재상장일, 워치리스트 자동 추가). 신설법인 주식수는 계산 후 재상장 공시로 덮어쓰기. 물적분할은 범위 밖. 소량 규칙(1천주 이하 무시·10만주 이하 경미)은 CB/BW 에만. |
| 10-10 | 합병 소멸회사(상장사)는 상장폐지까지 추적하되 리포트에 별도 이벤트로 두지 않는다(상장폐지일 = 신주 상장일, 2/2 관측). 권리락/배당락 시점 수량(as-of) 보존은 복잡해지면 하지 않는다. |
| 10-10 | 시총 변동은 상장주식수 기준(유동비율 미적용·참고도 아님). 우선주 무시. 시총 변동 '추정' 표기 OK(정확할 필요 없음). 종가는 MCP 로 받아 주간 기록. |
| 10-11 | 벤치마크 = KOSPI 시총 상위 300(`kospi_list_clean.md`/MCP universe). 상대방(신설·소멸 법인) 자동 추가. 종목 확장은 날짜 단위 스캔. |
| 10-11 | 고려아연형(최초 공시가 스캔 구간 밖) → 그 종목·그 하루만 보충(전체 구간 확대 X). 한솔테크닉스형 → 최근 공시 덮어쓰기 원칙. 분기 반복 취득·소각 → 프로그램 단위 통합 + 변경상장 합산 적용. 상호변경 공시 무시. 달력·CB 일정에 민감하지 않음. 신규 종목 상장주식수 시드는 비우고 잠재 시총만. |
| 10-11 | 카카오 분할은 개정 방법론 문서 없이 현행 규칙으로 진행(공시는 나왔고 문서가 첨부로 안 돎) — 상세에 메모, 신규칙 적용 여부는 사용자 확인. 제3자배정은 일반주주에 권리락 없음(상장일 앵커). |
| 10-11 | 리포트 4탭(일정 확정 / 일정 미확정 / 자기주식 취득 진행 / 최근 종결), 앵커·정렬 규칙, 관리종목 표지, 유상증자 태그 세분(주주배정/3자배정/공모), 이슈·리스크 태그, 하나금융처럼 법인 고유 간격이 분명하면 법인별 추정 사용(관측 3건 이상). 태영건설(009410) 유니버스 제외. 푸시는 사용자의 최종 렌더링 확인 후. |
| 10-11 | 자기주식 취득 진행을 시간 비례 추정이 아니라 KIND '자기주식매매 체결내역'(하루 1건 전 종목)의 누적 체결금액으로 보정(삼성전자·SK하이닉스처럼 규모가 크고 시장이 민감한 종목 — 실제로 삼성전자는 15조원 계획이 10/06 소진). 소진 예상일은 소각 변경상장 예정일 추정에도 반영. |
| 10-11 | 리포트 사용자 최종 확인 완료·푸시. 대한항공 ← 아시아나항공 합병은 소규모합병이 맞음(확정). 금양 상장폐지 효력정지 가처분은 **결과를 추적하지 않는다** — 이슈가 있다는 사실(리스크 태그)만 알린다. |
| 10-11 | 전반 오버뷰: 마크다운 리포트(`daily_report`·`m2_report`)는 없애도 됨(이력만 git 에 남김), `prices_*.csv` 는 git 추적(`.gitignore` 예외), 세부 진행은 위임 + 독립 조언자 에이전트 감사를 거쳐 진행. 결과는 10절. |

## 6. 반드시 알아야 할 함정
- **KIND 방화벽 403**: 요청이 짧은 시간에 많으면 간헐 차단. `KindBlocked` + 백오프 재시도. 403 HTML 을 "0건"으로 오해해 빈 결과가 캐시에 영구 저장될 뻔했음(수정됨). **스캔은 sleep, 불필요한 호출 금지.**
- **상세검색은 1년 초과 구간이면 오류 없이 0건** → 항상 ≤330일(`collector.windows`). 새 조회 코드에서도.
- 서버 필터: 수시공시 `disclosureType01`, 시장조치 `…02`, 시장 구분 `marketType=1`(유가증권). 값은 `code|code|`(끝에 `|`). 대분류 01 수시·02 시장조치·04 신고사항·07 발행공시.
- KIND 회사명 ≠ 명단 표기(LS ELECTRIC ↔ **엘에스일렉트릭**, HD현대 ↔ 에이치디현대). **이름이 아니라 종목 검색으로 얻은 단축코드로 대조**(`scan_day.code_of`). 영문 표기로는 검색 0건.
- 정정공시 뷰어는 *기공시 본문 + 해당 본문* 나열 → `selected` 본문만. 정정 전문은 마지막 "…결정 / 1. …" 이후. 인용문('1. 신주의 종류와 수')이 본문에 섞여 있어 서식 시작은 *항목 수가 가장 많은 후보*로 잡는다. 정정 헤더 두 종류(`정 정 신 고 (보고)`+최초제출일 / `정정신고(보고)` 만).
- **같은 날 서로 다른 증자가 같은 '최초제출일'로 정정**되는 경우(한솔테크닉스) → 방식(R/T/P)을 스레드 키에 포함.
- 같은 날 `주식분할 결정` 재공시(LS ELECTRIC 오기재 → 정정) → 뒤 건이 최신.
- 취득 후 소각은 **변경상장 한 건이 여러 소각 결정을 합산 처리**하는 법인이 있다(KB금융·하나금융) → 취득 시작일 단위 프로그램 스레드, 소각일이 같은 프로그램 모두에 같은 변경상장을 붙인다.
- 합병 결정 공시는 **존속·소멸 양쪽이 각각** 낸다 → 소멸회사가 낸 건은 건너뜀. 서식에 따라 `합병비율` 항목이 없고 '주주가치에 미치는 영향' 문장에 비율이 있다(대한항공 0.2736432).
- DART `발행주식총수`는 발행일 기준, 우리 원장은 상장일 기준 — 시드는 `m1_parser.seed_adjust` 로 보정. 신규 종목은 시드 없이 결정 공시의 증자 전 발행주식수로 대체.
- 달력: `exchange_calendars` XKRX 가 놓친 휴장은 `calendar_override`. 연말 휴장(12/31) 때문에 기준일이 휴장이면 권리락일 = 직전 영업일의 직전 영업일(`ex_from_record`).
- 우선주 종류가 여러 개(한화 1우 상장폐지, 3우B). 관리종목 지정 중 우선주만 해당하는 건(한화·삼성중공업)은 보통주 표지에서 제외.
- 오프라인 재생성은 `TO` 고정 필수(캐시 키에 날짜 포함), `m2_cbbw` 네트워크 단계는 온라인.
- DART MCP(`filing_section`)는 출력이 매우 길다 — `find=` 로 좁힌다.

## 7. 지수 규칙 요약
① 신규상장일 증가(일반공모·제3자배정·CB/BW 전환·행사·합병신주) ② 주주배정 유상증자·무상증자는 권리락일(주식배당은 배당락일) ③ 자사주 소각은 변경상장일 감소 ④ 인적분할 존속 = 변경상장일, 신설 = 별개 종목(재상장일) ⑤ 실권은 신주 상장일에 −실권 ⑥ 액면분할 = 변경상장일 ×비율 ⑦ 합병 = 합병신주 상장일 +신주(소멸회사 상장폐지일과 동일). 2026-11 방법론 개정(현금 처리 폐지 등)은 근거 문서 수령 후 `index_rules.py` 에 version 추가 — 첫 사례 카카오 분할. 표 [`KIND_INDEX_METHOD.md`](KIND_INDEX_METHOD.md), 코드 `index_rules.py`.

## 8. 알려진 한계 · 검토 큐
- 소각 변경상장 *예정일*은 임시 추정(소각일 + 중앙 약 11영업일 / 취득 종료일 + 과거 간격). 법인별 간격은 관측 3건 이상일 때만(하나 92일·JB 24일·BNK 38일), 나머지는 전체 중앙 36일. 변경상장 공시가 나오면 확정.
- 취득 후 소각 중 변경상장과 매칭이 끝내 안 되는 스레드는 `unmatched_stale`(완료 처리·리포트 제외) — 합산 소각 공시 추정. 복잡 사례는 사람이 확인.
- 자기주식 취득 진행률 = 계획 시작일부터의 누적 체결금액 ÷ 취득 예정금액(체결내역 일별 합산). **한도는 금액** — 신고수량(주식수)은 초과해도 금액이 남으면 계속 산다(삼성전자 106.7%). 체결내역이 없는 종목만 기간 경과 비례 추정. 신탁은 일별 체결만 있어 계약 시작일부터 합산. 마지막 체결이 오래된 프로그램은 '최근 체결 없음'으로 표시.
- 신규 종목은 상장주식수 시드가 없다(CB/BW '상장 대비 %'가 비는 이유). 잠재 시총만 표기.
- 리츠·인프라펀드 8종목은 KIND 종목 해석 대상 아님(제외). 태영건설(009410)은 `kind/universe/exclude.txt` 로 제외.
- 금양: 상장폐지 결정(2026-05-20) 후 효력정지 가처분 — 이슈 사실만 표기(리스크 태그), 결과는 추적하지 않기로 함(사용자 지침). 13,000,000주 제3자배정 상장(2027-01-21 예정) 무산 가능.
- SK이노베이션 ← SK아이이테크놀로지 합병: 금감원 정정명령(9/4)·주주간담회 — 일정 변경 가능('리스크' 태그).
- m1 review 1건(키움증권 `추가상장(주식의종류변경)` 서식).
- 카카오 분할 신규칙 적용 여부 — 사용자 확인.

## 9. 작업 방식(사용자 선호)
- 한국어. **가볍게 한 사이클 돌려 보고 → 점검 → 커밋 → 다음**. 세부 지침은 단계별로. 완벽 추구보다 핵심 날짜·수량을 명확히.
- 커밋은 사용자 요청 시 KIND 파일만(`git add kind docs/KIND_*.md`), DART 쪽 미커밋 변경(`disclosure_md`, `trial_case`, `node_modules`, `package*.json`, `report_v2/sample_v3.*`)은 건드리지 않는다. **푸시는 리포트 최종 확인 후.** 커밋 메시지 끝 `Co-Authored-By` 줄은 시스템 지침 따름.
- 사용자가 참조 문서를 주면 먼저 읽고 `KIND_INDEX_METHOD.md` 에 반영.
- 리팩터링은 항상 `regress.py` 로 전후 비교(건수만으로는 값 변화를 못 잡는다). 구조 변경 전에는 독립 조언자(읽기 전용 에이전트)에게 계획을 감사받는다 — 이번 세션에서 계획 오류 5건(유사 함수 오인·universe.csv 순서 위험 등)을 사전에 걸렀다.

## 10. 오버뷰·리팩터링 결과 (2026-10-11) 와 남은 과제
**완료(전부 `regress.py` 전 표 동일 + HTML 해시 동일 + M2 모듈 반복 실행 멱등 확인, 커밋 `33f027e`…)**
- `kind/regress.py` 신설(회귀 도구) · `kind/common.py` 신설(`cal`·`tdiff`·`ex_from_record`·`set_slot`·`prune`·`text_of`·`kdate`·`after`·`dday`·`link_filing` — 이전엔 `m2_rights_issue`/`m1_parser` 안에 있었고 다른 모듈이 거기서 import) · 5개 스레드 모듈의 `event_filing`+sources 중복 블록을 `link_filing` 으로.
- 마크다운 리포트 폐지: `daily_report.py`·`m2_report.py`·`kind/reports/*.md` 삭제(`git show 33f027e:kind/daily_report.py`). 원장 현황·변동 이력·시장경보(M3) 요약은 이제 DB 조회로만 본다.
- `prices_*.csv` git 추적(클론 환경에서 유니버스 300 재현), `watchlist_phase1.json` 삭제, K200 파일럿 목록 → `kind/pilot_targets.txt`(`rebuild_all.sh` 가 빈 파일이면 종료).
- 문서: `KIND_M2_*` 4종 → `KIND_M2.md`, `REPORT_OUTLINE`→`REPORT`, `SCAN_TEST`→`DESIGN` 3절, `NEXT_SESSION` 삭제.

**일부러 하지 않은 것(재검토 근거)**
- 스레드 엔진 통합/플러그인화: `finalize` 가 유형별로 크게 다르고, `mark_parsed`(rights 는 후속 공시까지, 나머지는 DECISION 만; corp_actions 는 `failed` 상태 제외)·`get_or_create_event`(rights 만 `index_share_adj` 삭제, split 은 `CAL_MARK` 원장 행 삭제, event 타입·title 상이) 차이가 있어 인자가 늘고 이득이 작다. 공통 골격(load→attach→replay→finalize→prune)은 문서화만.
- 같은 이름의 *다른* 함수는 합치지 않음: `num`(`m1_parser`/`etf_parser` int 전용 vs `m2_decision` float/None 허용), `after`(`m2_decision` 의 `stop` 인자판, `m2_split` 지역함수), `NOW`(`seed_master` 는 문자열 상수 — `scan_range` 가 바인딩), `won`(`html_report` 는 부호 포함 2자리).
- `html_report` 분리(`build()`가 데이터, `main()`이 템플릿 치환으로 이미 분리), `m1_parser` 파일 분할, `parse_listing` 표 기반 전환, `rebuild_all.sh` 의 `parse_all.sh` 분리(`--register` 류가 파싱 결과로 수집 대상을 만들어 수집/파싱이 섞여 있음 → 분리하려면 "DB 초기화 여부" 정의가 먼저).

**남은 과제**: 오프라인 캐시 키가 '오늘'에 묶임(`m2_cbbw` 신고사항 조회) → 기준일 고정 옵션 · 신규 종목 상장주식수 시드 · 법인별 소각 간격 · 합산 소각 변경상장 복잡 사례 · 유/무상감자·물적분할·주식병합·M4 대량매매 · 카카오 분할 신규칙 · DART 모듈 통합(2차, 아래).
**DART 통합 1단계(느슨한 결합) 구현 완료·미푸시** — `kind/run_kind_daily.py`, `kind_hook.py`, `run_daily.py`/`send_report.py` 연결, 가동 테스트 결과와 운영 전 확인 사항은 [`KIND_DART_INTEGRATION.md`](KIND_DART_INTEGRATION.md) 7절. 2단계(DART 대시보드에 KIND 지수 영향 칩·에이전트 입력 주입)는 미착수.
**DART 통합 시 참고**: `kospi_list_clean.md`(DART 명단 사본)·`prices_*.csv`·`exclude.txt` 가 유니버스의 단일 소스이므로 DART 쪽 명단과 공유할 지점은 `kind/universe/`. 공시 PK(`filing_id` = `KIND:`/`DART:` 접두)와 `security_id` 대리키는 이미 DART 공시를 받을 수 있게 설계돼 있다(원칙 2·3).

## 11. 통합 1.5단계(2026-10-11, 미푸시→푸시 예정)와 다음 세션 메모
**추가 완료**: 메일 통합(영업일마다 한 통: DART 번들 + KIND 섹션·첨부, DART 통과 0건이면 'DART 중요 공시 없음' + KIND 요약만 — 실제 테스트 발송 2통 확인) · 신설·소멸 법인 **자동 등록·수집**(`run_kind_daily.py` collect_new, 마지막 수집일 `meta.collect:<코드>`; 신규 단축코드는 영문 포함 `0126Z0`) · KIND 를 DART prep **이전**에 시작 · `rebuild_all.sh` 는 일일 작업 중(`.daily.lock`)이면 거부 · `dart_calendar` 2027 휴장일 + 범위 밖 경고 · 구 버전 파일 `dep/` 정리(`dep/README.md`).
**종가(prices_*.csv) 자동 갱신 방안**(미구현 — 사용자 환경에서 MCP 인증 확인 후): ① *권장* `run_daily.py` 가 이미 `claude -p`(헤드리스, 허용 도구에 `mcp__claude_ai_OpenProxyMCP` 포함)로 에이전트를 돌리므로, 최신 prices 가 기준일보다 5일 넘게 낡았을 때 같은 방식으로 한 줄 프롬프트(“`trading_data(scope=universe, universe='코스피 시총 상위 300', format=md)` 결과를 `kind/universe/save_prices.py` 표준입력으로 저장”) 실행 — 모델 Haiku 로 충분, 검증은 새 파일 행수 ≥ 290. ② KRX 정보데이터시스템 직접 호출은 약관·차단 위험으로 비권장. 낡으면 지금도 비고 경고가 붙는다.
**다음 세션 (사용자 계획)**: ⓐ 액면분할 등 세부 이벤트 보강 — 가온전선 건 포함 ⓑ **ETF 설정·해지(`etf_unit_change`, 대표 8종 54,454행)에 따른 영향도**를 KIND 인덱스 리포트에 통합. 그 밖의 남은 과제는 10절.
