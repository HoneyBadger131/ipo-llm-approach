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
# 인적분할 신설법인: 결정 공시에서 이름을 읽어 KIND 해석 → 워치리스트 추가 → 그 법인의 공시(재상장 등) 수집
NEWCO=$($PY kind/m2_split.py --register | tail -1)
[ -n "$NEWCO" ] && $PY kind/collector.py --from 2025-01-01 --to "$TO" --watch phase1 --only "$NEWCO"
# K200 시범 종목(합병·무상증자·주식배당·액면분할): 종목별 구간. 본문은 관련 제목만 받는다(호출 절제)
PILOT_RE='합병|주식분할|액면분할|무상증자|주식배당|배당락|권배락|권리락|기준가격|매매거래정지.*(분할|합병)|^(변경상장|추가상장|상장안내)'
for x in "267270 2025-01-01" "096770 2024-01-01" "068270 2022-01-01" "185750 2024-10-01" "010120 2026-01-01" "000670 2024-10-01"; do
  set -- $x; $PY kind/collector.py --from "$2" --to "$TO" --watch k200_pilot --only "$1" --body-re "$PILOT_RE"
done
# 합병 소멸회사(상장사, 상장폐지 포함): 결정 공시에서 이름 해석 → 워치리스트(merger_extinct) → 거래정지·상장폐지 공시 수집
for x in $($PY kind/m2_corp_actions.py --register-extinct | tail -1 | tr ',' ' '); do
  $PY kind/collector.py --from "${x#*:}" --to "$TO" --watch merger_extinct --only "${x%%:*}" --body-re '합병|상장폐지|매매거래정지'
done
# 종목 확장: 시총 상위 300 유니버스 등록 + 날짜 단위 이벤트 스캔(이벤트 유형만 서버 필터, 유가증권시장) → 유니버스 종목 공시 적재
$PY kind/scan_range.py --register
$PY kind/scan_range.py --from 2025-07-01 --to "$TO"
# 자기주식 매매 체결내역(유가증권시장, 하루 1건 전 종목) → 취득 프로그램의 실제 진행(누적 체결금액)·예상 소진일
$PY kind/buyback_exec.py --from 2026-06-01 --to "$TO"
# 누락된 최초 결정 공시를 해당 종목에 한해 하루 조회로 보충(스캔 시작일 앞의 원본) + 종목 상태 표지(관리종목)
$PY kind/backfill_orphans.py
$PY kind/status_flags.py --to "$TO"
$PY kind/etf_parser.py
$PY kind/m1_parser.py
$PY kind/m3_parser.py
$PY kind/m2_rights_issue.py
$PY kind/m2_cancel.py
$PY kind/m2_cbbw.py
$PY kind/m2_split.py
$PY kind/m2_corp_actions.py
$PY kind/daily_report.py
$PY kind/html_report.py
