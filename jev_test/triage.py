"""공시 분류 운영 모듈 — 하이브리드: ① 하드 규칙(rules_core) → ② Jev v3(Noul + Choice) → ③ 시총 구간별 임계값.

라이브러리:  from triage import triage_case
CLI(1건):    python jev_test/triage.py <접수번호> <YYYYMMDD> <종목코드> <회사명> "<공시명>"   (본문은 jev_test/data/bodies/ 또는 bodies/ 에서 찾는다)
일 단위:     python jev_test/triage_day.py <YYYYMMDD>

라벨 5종: PASS(통과) / PASS_CHECK(통과·확인) / NOTIFY(알림만) / HOLD(보류=사람 검토) / DROP(탈락)
  "분석으로 진행" = PASS·PASS_CHECK·HOLD(검수 표시)   |   NOTIFY = 브리프에 한 줄 알림만, 심화 분석 없음

Jev 경로의 라벨 결정 (Noul p, 시총 구간별 임계값 (pass, gray))
  large(시총 상위 30 또는 분쟁 리스트): (0.3, 0.1)   other: (0.5, 0.2)
  p ≥ pass : Choice 가 PASS/PASS_CHECK/NOTIFY 면 그대로, 아니면 PASS_CHECK(둘이 어긋나면 확인)
  gray ≤ p < pass : Choice 가 NOTIFY 면 NOTIFY, DROP 이면 DROP, 아니면 HOLD (진행 + 검수 표시)
  p < gray : Choice 가 NOTIFY 면 NOTIFY, 아니면 DROP
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import build_state, call_jev  # noqa: E402
from questions import QUESTIONS  # noqa: E402
from rules_core import dispute_names, hard_rule, is_large_cap  # noqa: E402

VERSION = "v3"
LANG = "en"
THRESH = {"large": (0.3, 0.1), "other": (0.5, 0.2)}      # (진행, 회색) — 사용자 N4 '상위 30은 민감하게'를 임계값으로 구현
ANALYZE = {"PASS", "PASS_CHECK", "HOLD"}                  # 심화 분석으로 가는 라벨


def tier(case):
    return "large" if (is_large_cap(case["stock_code"]) or case["corp_name"] in dispute_names()) else "other"


def decide(noul, choice, tr):
    hi, lo = THRESH[tr]
    if noul >= hi:
        return choice if choice in ("PASS", "PASS_CHECK", "NOTIFY") else "PASS_CHECK"
    if noul >= lo:
        return "NOTIFY" if choice == "NOTIFY" else ("DROP" if choice == "DROP" else "HOLD")   # 회색 & Choice=DROP → DROP (연장·대환 등, 2026-10-08)
    return "NOTIFY" if choice == "NOTIFY" else "DROP"


def jev_answers(resp):
    """Jev 응답에서 (noul, choice) 를 뽑는다."""
    a = resp["answers"]
    ch = a["triage"].get("choice") or max(a["triage"]["probabilities"], key=a["triage"]["probabilities"].get)
    return a["proceed"]["noul"], ch


def triage_case(case, body="", key=None, resp=None):
    """case: dict(report_nm, corp_name, stock_code, is_correction[, day, rcept_no]) → 결과 dict.
    resp 를 주면 API 호출 없이 저장된 Jev 응답으로 판정한다(평가용)."""
    h = hard_rule(case, body)
    if h:
        label, rule, why = h
        return dict(label=label, source="rule", rule=rule, reason=why, noul=None, choice=None, tier=tier(case), proceed=label in ANALYZE)
    if resp is None:
        state = build_state(case, "TD", VERSION)      # 본문은 lib.read_body(case)로 읽는다 (jev_test/data/bodies)
        resp = call_jev(state, QUESTIONS[VERSION][LANG], key)
    if "answers" not in resp:
        return dict(label="HOLD", source="error", rule="E-JEV", reason=f"Jev 오류: {str(resp)[:80]}", noul=None, choice=None, tier=tier(case), proceed=True)
    noul, choice = jev_answers(resp)
    tr = tier(case)
    label = decide(noul, choice, tr)
    return dict(label=label, source="jev", rule=f"J-{tr}", reason=f"Noul {noul:.2f} · Choice {choice} · {tr}", noul=noul, choice=choice, tier=tr, proceed=label in ANALYZE)


if __name__ == "__main__":
    rid, day, code, corp, title = sys.argv[1:6]
    case = dict(rcept_no=rid, day=day, stock_code=code, corp_name=corp, report_nm=title, is_correction=title.startswith("[기재정정]") or title.startswith("[첨부정정]"))
    from lib import read_body
    print(triage_case(case, read_body(case), os.environ.get("TYPE_SAFE_AI_KEY")))
