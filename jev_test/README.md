# jev_test 코드 지도
상세 가이드: [`../docs/DISCLOSURE_TRIAGE.md`](../docs/DISCLOSURE_TRIAGE.md).

**운영(현행)**: `rules_core.py`(하드 규칙), `questions_v3.py`(동결 질문 = 현행), `triage.py`(판정), `triage_day.py`(일일 실행), `lib.py`, `test_rules.py`.
**평가·라벨링**: `eval_hybrid.py`(현행 평가), `policy_relabel.py`, `apply_review.py`, `build_*`, `run_jev.py`, `score_run.py`, `eval_final.py`, `validate_report.py`.
**이력(참고용)**: `questions.py`(v0·v1·v2·v2b 등록), `questions_v2.py`, `eval_v2.py`, `compare_runs.py`. (`analyze_week.py`·`collect_week.py` 는 `../dep/jev_history/` 로 이동)
**데이터**: `cases/`(라벨), `runs/`(Jev 원응답·리포트), `review/`(사람 검토 CSV), `data/bodies/`(본문, git 무시).
