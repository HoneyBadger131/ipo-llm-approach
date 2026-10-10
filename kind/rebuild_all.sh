#!/bin/bash
# DB 전체 재생성 (원천 본문은 kind/data/raw 캐시를 쓰므로 네트워크는 목록 조회 정도만 필요)
#   사용: ./kind/rebuild_all.sh [종목 시작일=2025-01-01] [종료일=오늘] [ETF 시작일=2025-10-09]
#   네트워크 없이(캐시만): KIND_OFFLINE=1 ./kind/rebuild_all.sh   (목록·본문·유형코드·종목해석 캐시 필요)
set -e
cd "$(dirname "$0")/.."
PY=.venv/bin/python
rm -f kind/data/kind.db kind/data/kind.db-wal kind/data/kind.db-shm
$PY kind/build_calendar.py
$PY kind/seed_master.py
FROM=${1:-2025-01-01}; TO=${2:-$(date +%F)}; EFROM=${3:-2025-10-09}
$PY kind/collector.py --from "$FROM" --to "$TO" --watch phase1
$PY kind/collector.py --from 2024-01-01 --to "$TO" --watch phase1 --only 352820,066970,457190,000880   # CB/BW 종목은 발행결정(2024)부터
$PY kind/collector.py --from "$EFROM" --to "$TO" --watch etf_core
$PY kind/etf_parser.py
$PY kind/m1_parser.py
$PY kind/m3_parser.py
$PY kind/m2_rights_issue.py
$PY kind/m2_cancel.py
$PY kind/m2_cbbw.py
$PY kind/daily_report.py
