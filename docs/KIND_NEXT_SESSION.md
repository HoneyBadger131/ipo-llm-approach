# 다음 세션 — KIND 축 오버뷰(중복·통합·분리) 제안

## 왜 새 세션인가
이번 세션은 설계 → M1~M3 → M2(유상증자·소각·CB/BW·분할·무상·배당·액면·합병) → 종목 확장 → 리포트까지 한 흐름으로 길게 이어져 컨텍스트가 많이 찼다. 오버뷰는 *코드와 문서 전체를 다시 읽고 구조를 판단*하는 일이라 **새 세션(깨끗한 컨텍스트)에서 `docs/KIND_HANDOFF.md` 하나만 읽고 시작**하는 편이 정확하고 싸다. 또 오버뷰 중 큰 리팩터링(스레드 엔진 통합 등)은 회귀 기준이 확실히 있어야 하는데, 지금 회귀 수치가 문서에 고정돼 있다([`KIND_HANDOFF.md`](KIND_HANDOFF.md) 3절).

## 시작 프롬프트 (복사해서 새 세션에 붙여넣기)
```
KIND 축 작업을 이어서 한다. 먼저 docs/KIND_HANDOFF.md 를 읽고(그 안의 링크는 필요할 때만), 프로젝트 메모리의 kind 항목을 참고해.
이번 세션의 목표는 "전반 오버뷰": 기능 변경 없이 KIND 코드·문서의 중복/불필요한 부분을 찾아 (1) 통합 가능한 부분 (2) 분리가 권장되는 부분 (3) 그대로 둘 부분으로 나누어 제안하는 것. docs/KIND_NEXT_SESSION.md 의 '초기 후보 목록'을 출발점으로 삼되 직접 코드를 읽어 검증해줘.
진행 방식: 먼저 읽기 전용으로 현황 지도(모듈별 줄 수·역할·상호 의존, 중복 로직 위치)를 만들고 표로 보고 → 내가 항목을 고르면 그것만 리팩터링 → 매번 오프라인 재생성(KIND_OFFLINE=1 ./kind/rebuild_all.sh 2025-01-01 2026-10-10 후 온라인 m2_cbbw.py)으로 HANDOFF 3절의 회귀 수치와 대조(원장 체인 불일치 0, M2 반복 실행 시 행 수 불변)하고, 달라지면 되돌리거나 이유를 설명.
제약: KIND 호출 최소화(캐시 우선), DART 쪽 미커밋 파일은 건드리지 않기, 커밋은 KIND 파일만(git add kind docs/KIND_*.md), 푸시는 내가 리포트를 확인한 뒤에만. 문서도 같이 정리(중복 문서 통합 포함)하고 HANDOFF 를 최신으로 유지해.
```

## 세션 순서 제안
1. **읽기 전용 지도**(30분): `wc -l kind/*.py`, 모듈 간 import 그래프, 함수 중복(`cal`/`tdiff`/`set_slot`/`prune`/`ex_from_record` 등 공용 함수 위치), 스레드 구현 5종의 공통 골격 비교.
2. **후보별 판정표**(통합 / 분리 / 유지 + 위험도 + 회귀 확인 방법) → 사용자 선택.
3. **한 번에 하나씩** 리팩터링 + 회귀 확인 + 커밋.
4. 문서 통합(M2 문서 5종, README/HANDOFF 중복) 마지막.

## 초기 후보 목록 (이번 세션에서 관찰한 중복·불필요 — 검증 필요)
**통합 후보**
- 스레드 5종(`m2_rights_issue`·`m2_cancel`·`m2_cbbw`·`m2_split`·`m2_corp_actions`)이 같은 골격(load → attach → replay(slot·filing·adj) → finalize → prune)을 각자 구현. 공용 스레드 엔진 + 유형별 파서/규칙 플러그인으로 추출 가능. 공용 함수(`cal`·`tdiff`·`set_slot`·`prune`·`ex_from_record`)가 `m2_rights_issue.py` 안에 있어 다른 모듈이 거기서 import — `common.py` 로 분리.
- 수집 경로 두 개: 종목별 `collector.py`(+`seed_master` 워치리스트 phase1·k200_pilot·merger_extinct)와 날짜 단위 `scan_range.py`(universe). 삽입·본문 수신·skip 규칙 중복. 워치리스트 의미(phase1/k200_pilot/universe/merger_extinct/etf_core)도 정리 필요.
- 표현 계층 중복: `m2_report.py`(마크다운 카드)·`daily_report.py`(마크다운) vs `html_report.py`(`facts`·`schedule`·`index_of`) — 같은 이벤트를 세 번 표현. 이벤트 → 구조화 dict 한 곳 + 렌더러(HTML/MD)로.
- 스레드 키 날짜(접수번호 날짜)·정정 헤더 판별·결정 공시 서식 시작 위치 선택 로직이 여러 파서에 반복.
- 상장 공시 서식 정규식(`m1_parser.parse_listing`)이 특수 사례로 계속 늘어남 → 표 기반 파서.
- `kind/universe/kospi_list_clean.md`(루트 파일 사본)와 `prices_*.csv` 의 유니버스 정의 이중화.
- 문서: `KIND_M2_*` 5종(유상증자·라운드2·분할·무상등·스캔테스트)과 HANDOFF/README/REPORT_OUTLINE 사이 중복·낡은 서술(스레드 키 변경 전 내용).

**분리 권장 후보**
- `html_report.py`: 데이터 구성(탭 판정·정렬·추정)과 파일 입출력 분리, 탭 판정 규칙을 설정 가능하게.
- `m1_parser.py`(대형): 상장/기준가/거래정지 파서를 모듈로 분리.
- `rebuild_all.sh`: 단계별 체크포인트(수집 단계 vs 파싱 단계) — 파싱만 재실행하는 경로(수집은 변경 없음).
- 시드/수동 입력 파일(`news.json`·`exclude.txt`·`prices_*.csv`)의 위치·스키마 문서화.

**불필요 가능성(삭제·git 제외 검토)**
- 생성 산출물이 git 에 있음: `kind/reports/*.md|html` — 재생성 가능(gitignore 후보) 또는 최신 1개만 유지.
- `daily_report.py` 마크다운이 HTML 로 대체되었는지, 아직 쓰는 절은 무엇인지.
- `watchlist_phase1.json`(3종목 시범 설명, 현재 `seed_master` 가 실제 소스).
- `m2_report.py` 의 오래된 카드 중 HTML 에서 안 쓰는 것.

**개선 과제(오버뷰와 별도)**
- 오프라인 재생성 캐시 키가 '오늘' 날짜에 묶임(`m2_cbbw` 신고사항 조회 등) → 기준일 고정 옵션.
- 신규 종목 상장주식수 시드(300종목) · 법인별 소각 간격 추정 · 합산 소각 변경상장 복잡 사례 · 유/무상감자·물적분할·주식병합·M4 대량매매 미구현 · 카카오 분할 신규칙.

## 체크리스트(리팩터링마다)
- 오프라인 재생성 성공(`rebuild_all.sh 2025-01-01 2026-10-10`) → 온라인 `m2_cbbw.py` → `html_report.py 2026-10-09` 로 탭별 건수(확정 8·미확정 19·CB/BW 6·취득진행 26·종결 2 @ 2026-10-08) 대조.
- `sqlite3 kind/data/kind.db "pragma foreign_key_check; pragma integrity_check"` ok, m1 chain_problems 0건.
- M2 5개를 두 번 연속 실행해도 `event/event_date/share_ledger/index_share_adj` 행 수 불변.
