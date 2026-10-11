# kind/ — KIND(거래소 공시) 축

진입점: [`../docs/KIND_HANDOFF.md`](../docs/KIND_HANDOFF.md) (상태·운영·결정 로그·함정). 설계 [`../docs/KIND_DESIGN.md`](../docs/KIND_DESIGN.md) · 지수 규칙 [`../docs/KIND_INDEX_METHOD.md`](../docs/KIND_INDEX_METHOD.md) · 리포트 [`../docs/KIND_REPORT.md`](../docs/KIND_REPORT.md).
환경: 레포 `.venv`(requests, exchange_calendars, holidays, pypdf) — 항상 `.venv/bin/python`. 로그인 불필요. `data/`(DB·캐시·본문 ≈200MB)는 git 제외·재생성 가능.

## 전체 재생성 (멱등)
```
./kind/rebuild_all.sh 2025-01-01 2026-10-10          # 온라인(처음, 천천히 — KIND 방화벽). TO 는 반드시 명시
KIND_OFFLINE=1 ./kind/rebuild_all.sh 2025-01-01 2026-10-10   # 캐시만으로 동일 결과(재현성 확인)
.venv/bin/python kind/m2_cbbw.py                     # 재생성 후 온라인으로 한 번(전환·행사 현황은 '오늘'이 구간에 들어감)
.venv/bin/python kind/html_report.py 2026-10-09      # → reports/kind_report_2026-10-08.html
```
`rebuild_all.sh` 단계: 캘린더 → 시드 → 종목별 수집(phase1·k200_pilot) → 신설·소멸 법인 등록·수집 → 유니버스 등록 + 날짜 스캔 → 누락 원본 보충 → 관리종목 → ETF → m1 → m3 → m2_* → daily_report → html_report.

## 파일 지도
**기반**
| 파일 | 역할 |
|---|---|
| `schema.sql`, `db.py` | 스키마 v1(날짜 PK=`calendar_day`, 종목 PK=`security_id`, 공시 PK=접수번호) · 연결/적용 |
| `build_calendar.py` | 메인 캘린더(2015~2040, 휴장 보정 `calendar_override`) |
| `kind_client.py` | KIND 목록·본문·종목 검색(캐시 `data/cache`·`data/raw`, `KIND_OFFLINE`, 403 백오프) |
| `seed_master.py` | 법인·증권·워치리스트(phase1·k200_pilot·etf_core)·주식수 시드(DART 반기) |

**수집**
| 파일 | 역할 |
|---|---|
| `collector.py` | 종목별 수집(수시공시 01 + 시장조치 02, 본문 필터 `--body-re`, `--bodies-only`) |
| `scan_day.py` | 하루치 이벤트 공시 스캔(서버 유형 필터 + `marketType=1`), 회사명→코드 해석 |
| `scan_range.py` | 유니버스 등록(`--register`) + 날짜 범위 스캔 적재. 유니버스 = `universe/prices_*.csv` ∪ `kospi_list_clean.md` − `universe/exclude.txt` |
| `backfill_orphans.py` | 정정 공시의 최초제출일에 원본이 없으면 그 종목·그 하루만 보충 |
| `status_flags.py` | 관리종목 상태(`status_flag` 테이블) |
| `etf_parser.py`, `etf_report.py` | ETF 일괄공시(설정/해지) |

**파싱·원장·이벤트**
| 파일 | 역할 |
|---|---|
| `m1_parser.py` | 변경·추가·재상장 → `share_ledger`, 기준가격 안내 → 이벤트, 거래정지 → HALT(+원장 체인 완성) |
| `m3_parser.py` | 투자경고·공매도 과열·거래정지 기간 → `designation` |
| `m2_decision.py` | 유상증자 결정 공시 파서·공용 토큰 함수 |
| `m2_rights_issue.py` | 유상증자 스레드(키 `PCI:<issuer>:<최초제출일>:<R|T|P>`) — **공용 함수 `cal`·`tdiff`·`set_slot`·`prune`·`ex_from_record` 도 여기** |
| `m2_cancel.py` | 자기주식 소각(취득 프로그램 스레드 `CXL:<issuer>:A<취득시작일>`, 변경상장 합산 적용, 변경상장 예정 추정) |
| `m2_cbbw.py` | CB/BW(발행 조건·전환·행사 상장·잔여 희석) |
| `m2_split.py` | 인적분할(신설법인 등록·재상장 원장·존속 감소) |
| `m2_corp_actions.py` | 무상증자·주식배당·액면분할·합병(+소멸회사 등록 `--register-extinct`) |
| `buyback.py` | 기준일 현재 취득 중인 자기주식 취득(직접·신탁) + 실적 진행(`progress`)·예상 소진일(`projection`, m2_cancel 이 변경상장 예정 추정에 사용) |
| `buyback_exec.py` | 자기주식 매매 체결내역(유가증권시장, 시장조치 0326 하루 1건) 적재 → `buyback_exec` 테이블(누적 체결금액·수량) |
| `index_rules.py`, `index_shares.py` | 지수 규칙표 · 지수 반영 주식수 산출(상장주식수 + 선반영) |

**리포트**
| 파일 | 역할 |
|---|---|
| `html_report.py`, `html_report_template.html` | HTML 4탭 리포트(데이터 구성 + 화면) |
| `daily_report.py`, `m2_report.py` | 마크다운 리포트·카드(이전 형식, `reports/*.md`) |
| `news.json` | 스레드 키별 '왜'·리스크·메모·태그·뉴스(사람이 추가) |
| `universe/` | `prices_<날짜>.csv`(주간 종가), `save_prices.py`, `bb_quotes.json`(삼성전자·SK하이닉스 일별 시세 — 취득 맥락), `exclude.txt`, `kospi_list_clean.md` |

## 명령 모음
```
.venv/bin/python kind/scan_range.py --register                          # 유니버스 등록
.venv/bin/python kind/scan_range.py --from 2026-10-09 --to 2026-10-16   # 날짜 스캔 적재(+본문)
.venv/bin/python kind/scan_day.py 2026-04-10 --market 1                 # 하루 스캔 미리보기(적재 없음)
.venv/bin/python kind/backfill_orphans.py                               # 누락 최초 공시 보충
.venv/bin/python kind/status_flags.py --to 2026-10-10                   # 관리종목 갱신
.venv/bin/python kind/m1_parser.py --all                                # 상장·기준가·정지 파싱
for m in m2_rights_issue m2_cancel m2_cbbw m2_split m2_corp_actions; do .venv/bin/python kind/$m.py; done
.venv/bin/python kind/buyback_exec.py --from 2026-06-01 --to 2026-10-09  # 자기주식 체결내역 적재(멱등)
.venv/bin/python kind/buyback_exec.py --show 000660 --from 2026-09-28    # 종목별 일별 체결
.venv/bin/python kind/buyback.py 2026-10-08                             # 자기주식 취득 진행 목록(실적·예상 소진일)
.venv/bin/python kind/index_shares.py 2026-10-08                        # 지수 반영 주식수
.venv/bin/python kind/universe/save_prices.py < mcp_result.md           # 주간 종가 저장
```
세부(수집 함정·서식 변형·사용자 결정 로그)는 HANDOFF 5~6절, 모듈별 설명은 `docs/KIND_M1_M3.md`·`KIND_M2_*.md`.
