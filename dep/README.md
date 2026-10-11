# dep/ — 더 이상 운영 경로에 쓰이지 않는 파일 보관소 (deprecated)

배포·검수 때 읽을 코드를 줄이려고 **2026-10-11** 에 옮겼다. 삭제가 아니라 *이동*이며(이력 보존), 어디서도 import·실행되지 않음을 확인했다
(운영 진입점 `run_daily.py` · `send_report.py` · `kind_hook.py` · `dart_prep_day.py` · `dart_day_pipeline.py` · `jev_test/triage_day.py` 에서 출발한 참조 추적 + 문서 대조).
되돌리기: `git mv dep/<경로> <원래 경로>` (아래 표의 '원래 경로'). `git log --follow dep/<파일>` 로 이력 조회.

| dep/ 경로 | 원래 경로 | 무엇이었나 | 보관 이유 |
|---|---|---|---|
| `experiments/trial_case_full/` · `experiments/disclosure_md_full/` | `trial_case_full/` · `disclosure_md_full/` | 10/7~8 '풀버전'(재무·가치평가·컨센서스·뉴스 포함) 대시보드 시험 산출물 | 현행 기본 구성이 되어 비교용 사본만 남음. 비교 결과: `docs/비교_현재안_vs_풀버전.md` |
| `experiments/trial_case_haiku/` · `experiments/disclosure_md_haiku/` | `trial_case_haiku/` · `disclosure_md_haiku/` | Sonnet vs Haiku 심화 분석 모델 비교 산출물 | 결론: 기본 모델 Sonnet. 비교: `experiments/trial_case_haiku/비교_Sonnet_vs_Haiku.md` |
| `legacy_scripts/dart_trial_case.py` · `dart_company_filings.py` · `dart_hd_test.py` | 레포 루트 | 초기 시험용 DART 조회·분류 스크립트(HD현대중공업 시험 등) | `dart_prep_day.py` 로 대체됨(HANDOFF §3 '초기 시험용') |
| `legacy_scripts/Untitled14.ipynb` | 레포 루트 | 탐색용 노트북 | 사용처 없음 |
| `samples/render_fin_sample.js` · `samples/design/` | `report_v2/render_fin_sample.js` · `docs/design/` | 금융용 레이아웃 시안과 렌더러 | 채택 전 시안, 운영 렌더러(`render*.js`)는 이를 쓰지 않음 |
| `jev_history/analyze_week.py` · `collect_week.py` | `jev_test/` | 주간 데이터 수집·통계 초기 실험 | `jev_test/README.md` 에 '이력(참고용)'으로 분류돼 있었고 다른 스크립트가 import 하지 않음 |
| `local_only/` (git 제외) | 레포 루트 · `report_v2/` | 미추적 임시 산출물: `trial_case_rerun/`(재실행 시험), `#.html`·`#.pdf`(이름 없는 임시 출력), `sample_v3.html/.pdf`(샘플 렌더 결과; 원본 `sample_v3.json` 은 `report_v2/` 에 유지) | 재생성 가능한 산출물. 커밋되지 않으므로 필요 없으면 로컬에서 삭제해도 됨 |

**이동하지 않은 것(오해 방지)**: `jev_test/` 의 평가·라벨링 도구(`eval_final.py` 등)는 `eval_v2.py`·`compare_runs.py` 를 import 하는 현행 평가 체인이라 그대로 둔다. `trial_case/<날짜>/`·`disclosure_md/` 는 일일 산출물(유사도 모듈 입력)이다. `node_modules/`·`package*.json`(렌더러용 Playwright, 현재 미추적)은 운영에 필요하다.
`logs/`·`state/` 는 git 제외(실행 로그 `logs/<날짜>.log`, KIND `logs/kind_<날짜>.log`).
