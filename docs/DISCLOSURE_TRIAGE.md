# 공시 분류 단계 (Jev 하이브리드) — 가이드

> 다른 대화·에이전트가 이 단계를 이어받을 때 가장 먼저 읽는 문서. 상세 근거는 `jev_test/공시판단_기본원칙.md`(정책), `jev_test/실험설계.md`(실험), `jev_test/종합문서.md`(결과 종합).

## 1. 목적과 범위
KOSPI-290(`kospi_list_clean.md`) 공시 각각을 **다음 단계(심층 분석 에이전트)로 넘길지 버릴지** 분류한다. Jev(TypeSafe System One)는 분류자일 뿐이며 분석은 하지 않는다. 비용은 제약이 아니다.

## 2. 파이프라인
```
DART 공시 → dart_rules.classify (제목 규칙 필터) → dart_subsidiary (자회사 중복 제거)
          → jev_test/rules_core.hard_rule (하드 규칙, 확정 시 Jev 생략)
          → Jev v3 (Noul `proceed` + Choice `triage`, 시총 구간별 임계값) → 라벨
```
임계값(`triage.THRESH`): 시총 상위 30(large) pass≥0.3 / gray≥0.1, 그 외 0.5 / 0.2. gray 구간은 HOLD(검토 플래그를 달고 진행).

## 3. 라벨
| 라벨 | 의미 |
|---|---|
| PASS | 다음 단계로 통과 |
| PASS_CHECK | 통과 + 다음 단계가 계산·비교·검증해야 함 |
| NOTIFY | 알림만(대표이사 변경 등), 심층 분석 없음 |
| HOLD | Jev 회색 지대. 운영에서는 검토 플래그 달고 진행 |
| DROP | 버림 |

노출(SURF)=PASS·PASS_CHECK·NOTIFY·HOLD, 분석(ANALYZE)=PASS·PASS_CHECK·HOLD.

## 4. 하드 규칙 (`rules_core.py`, 적용 순서)
| ID | 내용 | 라벨 |
|---|---|---|
| R-CORR-* | 정정: 형식 변경 DROP / 계약 해지·종료 또는 금액 변동 ≥200억 & ≥1% → PASS_CHECK / 그 외 DROP | |
| R-HALT, R-EFFECT | 매매거래정지·해제, 효력발생안내 | DROP |
| R-SUB-COPY | 본문 머리 "자회사/종속회사인 X의 주요경영사항"이며 X가 상장 목록 내 타사 | DROP |
| R-UNFAITHFUL | 불성실공시 | PASS |
| R-ACCIDENT | 중대재해 | PASS_CHECK |
| R-CEO | 대표이사 변경 | NOTIFY |
| R-RUMOR | 풍문·조회공시: 시총 30위 이내·분쟁 종목만 PASS_CHECK(재공시·미확정 반복은 DROP), 그 외 DROP | |
| R-MERGER-PROC | 합병 종료보고·사채권자집회·소규모합병 | DROP |
| R-LOCKUP | 보호예수 해제 | PASS_CHECK |
| R-FINTRANS / R-TRUST / R-FIN / R-REIT | 약관 금융거래·신탁해지·금융사 일상거래·리츠 차입: ≥1,000억 PASS_CHECK, 아니면 DROP | |

금액 상수: `BIG_WON=1000억`, `CORR_WON=200억`, `CORR_PCT=1%`, `LARGE_CAP_N=30`. 분쟁 종목은 `watchlists/dispute_watchlist.json`(규칙 필터가 주총 등 일정 공시를 review로 돌림).

## 5. 정책 결정 기록 (사용자, 2026-10-08)
- Q1 정례 우선, 단 ≥1,000억은 PASS_CHECK / Q2 연장·대환 DROP, 신규만, 증권·은행·보험 일상업무 DROP / Q3 풍문·"확정된 바 없다" DROP / Q4 보호예수 해제 PASS_CHECK / Q5 애매→DROP, 모름→PASS_CHECK / Q6 정정은 해지 또는 큰 금액 변동만 / Q7 바이오 임상 PASS / Q8 중대재해 PASS_CHECK, 불성실공시 PASS / Q11 분쟁 목록 / Q12 규칙 필터 조정.
- N3 대표이사 변경 NOTIFY / N4 시총 상위 30 민감, 나머지 낮음 / N5 전망·밸류업 변경 ≥15%만, 아니면 DROP / N6 합병 절차 공시 DROP / N7 임원 거래계획 DROP(지배구조 영향 시 PASS) / N8 금융사 하이브리드 발행·타법인 취득 유지 / N9 신규 구간 Claude 판정 승인.

- **2026-10-08 추가 결정**: 제일기획(소각 연동 매매거래정지)은 사람 PASS 유지 → R-HALT는 소각·감자·분할·합병 연동 정지를 제외하고 Jev에 맡김 / 약관 금융거래(R-FINTRANS)는 금액 무관 DROP / 풍문·조회공시는 삼성전자·SK하이닉스·LG에너지솔루션만 PASS_CHECK(나머지 DROP, 분쟁 종목 포함) / Jev 회색 지대에서 Choice가 DROP이면 DROP(연장·대환 대응; 개발·검증 재현율 99%→96%) / 심화 분석 기본 모델은 Sonnet(Haiku 비교: `trial_case_haiku/비교_Sonnet_vs_Haiku.md`) / 건설·조선 국내 수주는 중요도 1단계, 국내 재건축·재개발은 2단계 하향(`report_v2/AGENT_SPEC.md`).

## 6. 결과 (저장된 응답 재채점, API 호출 없음)
| 구간 | 건수 | 노출 재현율 | 노출 정밀도 |
|---|---:|---|---|
| 개발·검증(9/1~9/11, 9/30~10/1) | 181 | 99% (1/109) | 78% |
| 새 구간 9/14~9/29, v3 동결 시점(진짜 표본 외) | 165 | 96% (4/111) | 73% |
| 새 구간, v3.1 규칙 패치 후 | 165 | 100% (0/111) | 82% |

**주의**: v3.1 패치(단위 인식 `max_won`, R-HALT/EFFECT/SUB-COPY, 최상위 풍문 재공시)는 새 구간 오류를 보고 만들었으므로 패치 후 수치는 엄밀한 표본 외가 아니다. 표본 외 수치는 96%/73%이다. 놓침 4건 중 3건은 금액 파싱 버그였다.

## 7. 실행
```
python3 -m unittest jev_test.test_rules            # 규칙 단위 시험 (API 불필요)
python3 jev_test/policy_relabel.py                 # 정책 라벨 재생성
python3 jev_test/eval_hybrid.py w_all_v3 [--include-dups]   # 저장 응답 재평가
python3 jev_test/triage_day.py <YYYYMMDD> [--write-judgments]  # 일일 운영 (TYPE_SAFE_AI_KEY 필요; trial_case/<day>/prep.json 선행)
```
키는 환경변수(`DART_API_KEY`, `TYPE_SAFE_AI_KEY`)로만 읽는다. 저장소는 공개이므로 파일에 쓰지 않는다.

## 8. 라벨 계층
Claude 기본 < 정책(`cases/labels_policy.json`, 하드 규칙 산출) < 사람 명시(`cases/labels_human.json`). 사람이 기본값 그대로 둔 행(`labels_human_default.json`)은 확정이 아니다.

## 9. 열린 문제
1. (해결 2026-10-08) 제일기획·한화솔루션·풍문 범위·연장/대환은 위 결정으로 정리됨.
5. 소액 소송 승소(KT&G) 같은 금액 하한 미정.
6. 후속 심층 분석 에이전트 연결은 별도 대화에서 설계. 인터페이스 제안: `triage.json`의 라벨 + `rule`/`reason` + HOLD 플래그를 입력으로 전달.
7. `triage_day.py`는 실제 일자로 아직 실행해 보지 않음(스모크 테스트 필요).

## 10. 인수인계 체크리스트
- [ ] 단위 시험 통과, 키 미노출 확인(`grep -r "API_KEY=" .`)
- [ ] 질문 v3(`questions_v3.py`)는 동결. 바꾸면 새 버전(v4)으로 추가하고 재검증
- [ ] 규칙 추가 시 `test_rules.py`에 시험 추가, `policy_relabel.py` 재실행
- [ ] 새 구간은 규칙 동결 후 블라인드 라벨링 → 실행 → 평가 순서 유지
