#!/bin/bash
# DB 전체 재생성 (원천 본문은 kind/data/raw 캐시를 쓰므로 네트워크는 목록 조회 정도만 필요)
set -e
cd "$(dirname "$0")/.."
PY=.venv/bin/python
rm -f kind/data/kind.db kind/data/kind.db-wal kind/data/kind.db-shm
$PY kind/build_calendar.py
$PY kind/seed_master.py
FROM=${1:-2025-10-09}; TO=${2:-$(date +%F)}
$PY kind/collector.py --from "$FROM" --to "$TO"
$PY kind/etf_parser.py
$PY kind/m1_parser.py
$PY kind/m3_parser.py
$PY kind/daily_report.py
