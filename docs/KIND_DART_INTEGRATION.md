# KIND ↔ DART 통합 — 초안 (2026-10-11, 2차 작업용)

상태: **1단계(A) 구현·가동 테스트 완료(2026-10-11, 미푸시)**, 2단계(B)는 미착수. 구현 결과는 7절. 아래 1~6절은 초안 원문(감사에서 고친 부분은 7절에 정리). 현재 상태·결정 로그는 [`KIND_HANDOFF.md`](KIND_HANDOFF.md)(KIND), [`HANDOFF.md`](HANDOFF.md)(DART).

## 1. 현황 (코드로 확인한 것)
| | DART 축 | KIND 축 |
|---|---|---|
| 하는 일 | 공시 중요도 판단(가/부) → 회사별 심화 분석 에이전트 → 대시보드·브리프·번들 → 메일 | 주식수 변동·일정 추적 → 영업일 단위 HTML 4탭 리포트 |
| 실행 | `run_daily.py`(launchd, 월~금 04:00, 직전 영업일 기준) → `send_report.py` Gmail | 수동 일일 루틴(HANDOFF 3절), 자동화 없음 |
| 종목 | `kospi_list_clean.md` 290(우선주 제외) | 시총 상위 300 = `kind/universe/prices_*.csv` ∪ `kospi_list_clean.md` − `exclude.txt` |
| 저장 | 파일(`trial_case/<날짜>/`, `disclosure_md/`) | SQLite `kind/data/kind.db`(git 제외) |
| 공시 ID | DART `rcept_no` | KIND 접수번호 (`KIND:<번호>`; DART 접두 `DART:` 도 스키마상 허용) |

**실측 발견**: KIND 접수번호와 DART `rcept_no` 는 **서로 다른 번호 체계**다. DART 공시 457건과 KIND 공시 4,339건을 번호로 대조하면 겹침이 1건뿐. → 같은 공시를 번호로 연결할 수 없고 **(종목코드, 공시일, 유형)** 으로 연결해야 한다.
**겹치는 영역**: 유상증자·무상증자·자기주식 취득/소각·합병·분할·CB/BW·액면분할·주식배당. DART 는 이를 일반 공시처럼 심화 분석(에이전트)하고, KIND 는 같은 이벤트의 *지수 주식수 영향·일정*을 구조화해 갖고 있다 — 서로 보완이지만 현재 연결이 없다.

## 2. 통합 수준 (제안: 1단계는 느슨한 결합)
| 안 | 내용 | 평가 |
|---|---|---|
| A. 느슨한 결합 (권장 1단계) | 일일 실행에 KIND 단계를 격리해 추가, 산출물(HTML + 요약 JSON)을 DART 메일/번들에 *섹션*으로 합침. 유니버스 한 곳으로 | 위험 낮음, KIND 장애가 DART 메일을 막지 않음 |
| B. 이벤트 연계 | A + DART 대시보드의 주식수 관련 공시에 KIND 사실(지수 반영일·변동 주식수·시총 변동)을 칩으로 주입, 에이전트 입력에 KIND 구조화 사실 제공 | 에이전트 환각·토큰 감소 기대, 매칭 규칙 필요 |
| C. 저장소 통합 | DART 공시를 `filing`(`DART:`) 에 적재, 한 DB | 가치 대비 비용 큼 — 보류 |

## 3. 1단계(A) 설계
1. **유니버스 단일화**: `kind/universe/` 를 소스로 하는 작은 로더(`universe.py`)를 두고 DART 의 `dart_watchlist_filings.load_watchlist` 가 이를 쓰도록(또는 둘이 같은 코드 집합인지 검증하는 테스트만). DART 290 ⊂ KIND 300 인지 먼저 대조한다. *변경 시 DART 판단 대상이 늘어나므로 사용자 확인.*
2. **KIND 일일 작업 `kind/run_kind_daily.py`** (HANDOFF 3절 루틴을 코드로): 마지막 스캔일+1 ~ 기준일 `scan_range.py` → `buyback_exec.py` → `backfill_orphans.py` → `status_flags.py` → `m1_parser` → `m2_*` 5종 → `m2_cbbw.py`(온라인) → `html_report.py <기준일>`. 각 단계는 멱등이라 재실행 안전. 기준일은 `dart_calendar` 와 같은 영업일 판정(직전 영업일) 사용. 종가 갱신(MCP)은 사람이 주 1회 — 자동화 제외, 최신 prices 가 없으면 시총 '-' 로 표기하고 노트에 기록.
3. **요약 JSON** `kind/reports/kind_daily_<기준일>.json`: ★ 중요 이벤트 상위 N(지수 반영일 임박·시총 변동 큰 순), 신규 발생 이벤트(어제 이후), 오늘~5영업일 내 지수 반영일. 이 파일이 메일 본문 섹션의 입력이다.
4. **`run_daily.py` 연결**: DART 단계와 병렬이 아니라 *DART 준비 직후 별도 격리 호출*(`sh()` 로 실패 시 로그·노트만 남기고 계속). 통과 공시 0건이어도 KIND 이벤트가 있으면 메일을 보낼지는 **사용자 결정 필요**(현재: 통과 0건이면 메일 없이 종료).
5. **`send_report.py`**: 본문에 'KIND 지수 주식수 변동' 표(요약 JSON), 첨부에 KIND HTML. 비고 박스에 KIND 단계 실패/지연 표기.
6. **온라인 호출 절제**: 하루 ≈ 5~10콜 + 신규 회사명 해석. KIND 방화벽 403 시 백오프 후 해당 일은 다음 날 재시도(스캔은 `마지막 스캔일+1` 부터 이어 받으므로 자연 복구).

## 4. 2단계(B) 후보 — 1단계 가동 후
- **매칭 키**: 같은 `stock_code` + 공시일(±1영업일) + 유형군(예: 'PCI'↔`유상증자결정`). 정확도 검증용으로 최근 30영업일의 DART 통과 공시 ↔ KIND 이벤트를 대조해 매칭률·오매칭을 먼저 측정한다.
- **주입**: 매칭 시 DART 대시보드(`report_v2/render.js`)에 '지수 영향' 칩(변동 주식수·%·반영일·시총 변동 추정), 에이전트 프롬프트에 KIND `detail_json` 요약 제공 → 신주 수·일정 재계산/검색 생략.
- **중복 판단**: DART 가 이미 '부'로 거른 공시라도 KIND 가 지수 영향을 잡으면 KIND 섹션에는 남는다(두 축 판단 독립).

## 5. 검증·가동 테스트 계획
1. 회귀: 통합 코드 추가 후 `kind/regress.py diff base_db` 전 표 동일(KIND 코어 미변경 확인), `rebuild_all.sh` 오프라인 재생성 수치 동일.
2. 단위: 유니버스 로더(DART 290 ⊂ 300, 제외 종목), 요약 JSON 생성(고정 기준일 2026-10-08 → 탭 건수 확정 8·미확정 19·CB/BW 6·취득진행 26·종결 2 와 일치).
3. 스모크: `.venv/bin/python run_daily.py --date 20261008 --no-agents --no-send` — KIND 단계 포함, 메일 `.eml` 드라이런(`send_report.py` 드라이런)으로 섹션 렌더 확인. 에이전트 호출 없음(비용 0).
4. 장애 주입: KIND 단계가 예외/403 이어도 DART 번들·메일이 정상 생성되고 비고 박스에 표시되는지.
5. launchd: 실제 plist 는 건드리지 않는다(사용자 환경). 변경 사항은 문서로 안내하고 사용자가 적용.

## 6. 사용자 확인이 필요한 결정
1. 통과 공시 0건인 날에도 KIND 변동이 있으면 메일을 보낼지.
2. DART 판단 대상 종목을 KIND 300 으로 넓힐지(290 유지 가능).
3. 1단계 범위: A 만 / A+B.
4. KIND 일일 작업을 `run_daily.py` 안에 넣을지(권장) 별도 launchd 로 분리할지.

## 7. 1단계(A) 구현 결과 (2026-10-11)
**독립 조언자(Opus) 감사 2회**(초안 → 구현 diff)를 거쳐 초안을 고쳤다. 초안에서 바뀐 것:
- *사실 정정*: DART 290 ⊄ KIND 291 — 리츠·인프라 8종목은 DART 명단에 있지만 KIND 에서 해석이 안 돼 빠진다. 명단 순번은 DART 판단 규칙(N4, `jev_test/rules_core.py`)이 시총 순위로 쓰므로 **로더를 교체하지 않는다**(유니버스 통합은 보류, 두 명단이 같은지 확인만). 하루 호출은 5~10콜이 아니라 `status_flags`(약 17초)·`m2_*` 온디맨드 조회까지 포함.
- *배치*: "DART 준비 직후 `sh()`" → **prep 직후 백그라운드 `Popen`**(`kind_hook.start`), 메일 직전 `collect`(마감 1200초). 번들(`render_bundle.js`)에는 넣지 않고 **메일 본문 표 + KIND HTML 별도 첨부**(번들 실패가 `fail()` 로 DART 메일까지 죽이는 경로를 피함).
- *격리*: 모든 예외 흡수, 타임아웃 시 프로세스 그룹 kill, 결과 파일은 이번 실행의 mtime 만 인정, KIND 섹션 렌더 오류는 무시하고 DART 메일 발송, 첫 발송 시도가 실패하면 KIND 없이 재시도.
- *오프라인/차단*: `m2_cbbw`·`m2_rights_issue` 는 replay 가 네트워크 조회 결과(전환·행사 현황, 투자설명서 증서 일정)를 다시 쓰므로 오프라인이면 **건너뛰어 이전 결과 보존**(실행하면 해당 슬롯이 사라짐 — 실측). 차단(`KindBlocked`) 감지 시 이후 단계는 `KIND_OFFLINE=1`.
- *진행 기록*: `meta.last_scan_date` 를 하루 스캔 성공마다 갱신(실패 지점에서 중단, 다음 실행이 이어 받음). 재생성(`rebuild_all.sh`)은 `kind/data/.rebuilding` 마커, 일일 작업은 `.daily.lock` 으로 서로 피한다.
- *과거 날짜 재실행*: `run_daily.py --date <과거>` 는 KIND DB 를 과거 기준으로 되돌리므로 KIND 를 **기본 비활성**(`--with-kind` 로 켜고 `--no-kind` 로 끔).

**신규/변경 파일**: `kind/run_kind_daily.py`(일일 작업 + 요약 JSON) · `kind_hook.py`(루트, run_daily 훅; `KIND_DAILY_CMD` 로 명령 교체=장애 주입) · `run_daily.py`(+7줄, KIND 시작·수집·메일 인자) · `send_report.py`(`--kind-json`: 본문 표 3개 + 첨부) · `kind/db.py`(`KIND_DB` 환경변수=테스트용 DB 경로) · `kind/html_report.py`(`write_report()` 분리, `KIND_REPORT_DIR`) · `kind/rebuild_all.sh`(.rebuilding 마커) · `kind/regress.py`(designation id 제외).
출력: `kind/reports/kind_report_<기준일>.html`, `kind/reports/kind_daily_<기준일>.json`(단계 결과·경고·요약), `logs/kind_<날짜>.log`.

**가동 테스트(전부 복사본 DB 또는 패치 하네스 — 운영 DB·메일 무영향)**
| 테스트 | 결과 |
|---|---|
| 오프라인 실행(`--asof 2026-10-08 --offline`) | 0.8초, `regress diff base_db` 전 표 동일, HTML 해시 `11431d2e9fd1ee2c` 동일, 요약 탭 건수 8·19·6·26·2 |
| 온라인 실행(복사본) | 18.8초(`status_flags` 17초가 대부분), DB·HTML 동일 |
| 스캔 루프(`last_scan_date`=10-05 → 10-06~08 스캔) | 3일 성공, 마지막 스캔일 갱신, DB 동일(meta 키만 추가) |
| `send_report` 드라이런(`--kind-json`) | 본문에 'KIND · 지수 주식수 변동' 표 3개, 첨부 `kind_report_2026-10-08.html` |
| 훅 장애 주입(`false`/`sleep 30`+3초 마감/없는 명령/결과 파일 미생성) | 모두 `ok=False` + 한 줄 비고, 예외 없음; 낡은 JSON 오인 없음 |
| `run_daily.main` 하네스(DART 단계 패치): 정상 / KIND 실패 주입 / `--date` 단독 | 메일 명령에 `--kind-json` 포함 / `--note` 만 / KIND 비활성, 모두 DART 흐름 완주 |
| 운영 DB 오프라인 재생성 | 전 표 동일, 탭 건수 동일 |
**실행하지 않은 것**: 실제 `run_daily.py` 전체(DART API·TypeSafe Jev 호출·비용 발생), 메일 실제 발송, launchd 적용 — 사용자 환경에서 확인할 것.

**운영 전 사용자 확인/조치**
1. 첫 정규 실행 전에 한 번 수동 확인 권장: `.venv/bin/python kind/run_kind_daily.py --asof <직전 영업일>` 후 `kind/reports/kind_daily_*.json` 의 `warnings` 확인(온라인, 호출 소량). 기존 DB 는 마지막 스캔이 2026-10-10 까지라 첫 실행에서 그 이후 영업일을 이어 받는다.
2. 종가(`prices_*.csv`) 주간 갱신은 여전히 사람이 한다 — 7일 넘게 낡으면 비고에 경고가 붙는다. 시총 변동 '-' 표기가 아니라 낡은 값이 쓰이므로 갱신 누락에 주의.
3. `news.json`('왜' 한 줄·뉴스)은 수동이라 메일의 KIND 섹션에는 없다(HTML 첨부에는 있는 것만).
4. 분할 신설법인·합병 소멸회사 자동 등록·수집(`m2_split.py --register`, `m2_corp_actions.py --register-extinct`)은 일일 작업에 넣지 않았다 — 새 분할/합병 결정이 나오면 `rebuild_all.sh` 또는 수동 실행 필요(카카오 분할 재상장은 2027-01).
5. 통과 0건인 날 메일 없음(기본값 유지) — KIND 변동만 있는 날 알림을 원하면 결정 필요. 아직 남은 낮은 위험: DART 실패(`fail()`)일에는 KIND 가 시작되지 않을 수 있고, `rebuild_all.sh` 는 `.daily.lock` 을 확인하지 않는다(일일 작업 중 재생성 금지), `dart_calendar` 에 2027년 휴장일이 없다.
