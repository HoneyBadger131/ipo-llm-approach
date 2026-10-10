# kind/ — KIND(거래소 공시) 축

목표 설계도: [`../docs/KIND_DESIGN.md`](../docs/KIND_DESIGN.md)

- `kind_client.py` — 목록 조회(`list_filings`) + 본문 텍스트(`body_text`). 로그인 불필요, `requests`만 사용(`.venv/bin/python`).
- `watchlist_phase1.json` — 1단계 대상 3종목(삼성전자·SK하이닉스·삼성바이오로직스).

```
.venv/bin/python kind/kind_client.py list 000660 2026-06-01 2026-10-08 0321,0303
.venv/bin/python kind/kind_client.py body 20260724000133
```

## DB
- `schema.sql` — 스키마 v1(날짜 PK = `calendar_day`, 종목 PK = 대리키 `security_id`, 공시 PK = 접수번호). 원칙은 설계서 §6.
- `db.py` — 연결/스키마 적용. `build_calendar.py` — 메인 캘린더 빌드(멱등): `.venv/bin/python kind/build_calendar.py`
- `data/kind.db` 는 재생성 가능한 산출물이라 git 제외.

## 실행 순서 (재생성 가능, 모두 멱등)
```
.venv/bin/python kind/build_calendar.py                     # 메인 캘린더
.venv/bin/python kind/seed_master.py                        # 법인·증권·워치리스트·주식수 시드
.venv/bin/python kind/collector.py --from 2025-10-09 --to 2026-10-09 --no-body   # 목록
.venv/bin/python kind/collector.py --bodies-only [--shard 0/4]                   # 본문 캐시(병렬 가능)
.venv/bin/python kind/etf_parser.py [--all]                 # ETF 일괄공시 → etf_unit_change
.venv/bin/python kind/etf_report.py --days 60               # 대표 ETF 현황·누락 점검
```

## M1 (시장조치 → 주식수 원장/이벤트)
```
.venv/bin/python kind/m1_parser.py [--all]     # 변경·추가상장 / 기준가격 안내 / 거래정지
.venv/bin/python kind/daily_report.py [YYYY-MM-DD]  # kind/reports/m1_<기준일>.md
./kind/rebuild_all.sh                          # 전체 재생성(캘린더→시드→수집→ETF→M1→리포트)
```

## M2 (유상증자 스레드)
```
.venv/bin/python kind/m2_rights_issue.py [--asof YYYY-MM-DD] [--no-network]   # 스레드 재구성(멱등). 증서 거래기간이 없을 때만 투자설명서 온디맨드 조회
.venv/bin/python kind/m2_report.py [YYYY-MM-DD]                               # kind/reports/m2_rights_issue_<기준일>.md
```
설명: `docs/KIND_M2_RIGHTS_ISSUE.md`

## M2 라운드 2 (소각 · CB/BW)
```
.venv/bin/python kind/m2_cancel.py [--asof YYYY-MM-DD]     # 자기주식 소각 스레드(변경상장일 = 지수 감소일, 변경상장일 추정)
.venv/bin/python kind/m2_cbbw.py   [--asof ...] [--no-network]   # 전환사채·신주인수권부사채: 발행 조건 + 전환·행사 상장 이력 + 잔여 희석분
```
지수 규칙표 `index_rules.py`, 설명 `docs/KIND_INDEX_METHOD.md`, 라운드 정리 `docs/KIND_M2_ROUND2.md`
