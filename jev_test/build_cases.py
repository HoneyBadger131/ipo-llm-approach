"""정답셋(cases_v0.json) 생성. 라벨은 Claude 위임 판정(label_source=claude_v0)이며 사람 검수 전이다.

구성
  kind=judged        기존 판정 82건(judgments.json)을 4단계 라벨로 재라벨 (기본: 가->PASS, 부->DROP + 아래 보정)
  kind=correction    정정 공시로 규칙 필터가 제외한 35건 (jev_test/cases/corrections_labels.json 의 라벨)
  kind=rule_exclude  공시명 규칙으로 제외된 382건 (제목만 시험; 라벨은 DROP 가정 = rule_presumed)

사용법: python jev_test/build_cases.py
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from dart_rules import _CORRECTION, EXCLUDE_PATTERNS, normalize  # noqa: E402

DATA = os.path.join(ROOT, "jev_test", "data")
CASES = os.path.join(ROOT, "jev_test", "cases")

# 기존 판정(가/부)에서 라벨을 바꾸는 항목: 접수번호 끝자리 -> (라벨, 사유)
OVERRIDE = {
    "907800002": ("PASS", "사용자 결정: 임상은 계획 변경 승인이라도 통과(바이오 영향 큼)"),
    "907800004": ("PASS", "사용자 결정: 임상은 계획 변경 승인이라도 통과(바이오 영향 큼)"),
    "910800130": ("PASS_CHECK", "국가별 실적 합산 계산이 필요(전년 동월 ±10% 판단) — 다음 단계 에이전트가 계산"),
    "910800311": ("PASS_CHECK", "금액 비공개(최근 매출 2.5% 이상이라 공시) — 실제 규모는 다음 단계에서 확인"),
    "911800620": ("PASS_CHECK", "금액 비공개(최근 매출 2.5% 이상이라 공시) — 실제 규모는 다음 단계에서 확인"),
    "910000386": ("HOLD", "규칙1(200억 ≥30억)과 규칙3(기간 만료 정례 해지) 충돌"),
    "907800369": ("HOLD", "규칙1(1,000억)과 규칙3(만기 차환 정례) 충돌 — 보증 연장·대환은 통과시킨 선례와 불일치"),
    "911000423": ("HOLD", "규칙1(799억)과 규칙3(계열 운용사 정례 자금운용) 충돌"),
    "911000318": ("HOLD", "규칙1(500억, 누계 3,850억)과 규칙3(정례 자금운용) 충돌"),
    "910800538": ("HOLD", "대법원 유죄 확정이나 재무 영향은 이미 반영 — 평판·지배구조 영향 해석이 갈림"),
}


def load_judged():
    J = []
    for p in sorted(glob.glob(os.path.join(ROOT, "trial_case", "2026090[7-9]", "judgments.json"))
                    + glob.glob(os.path.join(ROOT, "trial_case", "2026091[01]", "judgments.json"))):
        day = p.split(os.sep)[-2]
        J += [dict(j, day=day) for j in json.load(open(p, encoding="utf-8"))]
    return J


def main():
    os.makedirs(CASES, exist_ok=True)
    uni = {u["rcept_no"]: u for u in json.load(open(os.path.join(DATA, "universe.json"), encoding="utf-8"))}
    cases = []
    for j in load_judged():
        u = uni[j["rcept_no"]]
        label, why = ("PASS", j["reason"]) if j["proceed"] else ("DROP", j["reason"])
        for suf, (lb, note) in OVERRIDE.items():
            if j["rcept_no"].endswith(suf):
                label, why = lb, note + " | 기존 판정: " + j["reason"]
        cases.append(dict(rcept_no=j["rcept_no"], day=j["day"], period="w0907", stock_code=u["stock_code"], corp_name=u["corp_name"],
                          report_nm=u["report_nm"], is_correction=False, kind="judged", label=label, label_reason=why[:300],
                          label_source="claude_v0", was_borderline=bool(j.get("borderline")), tag=j.get("tag")))
    cl_path = os.path.join(CASES, "corrections_labels.json")
    cl = json.load(open(cl_path, encoding="utf-8")) if os.path.exists(cl_path) else {}
    for u in uni.values():
        if u["is_correction"]:
            lb = cl.get(u["rcept_no"])
            cases.append(dict(rcept_no=u["rcept_no"], day=u["day"], period="w0907", stock_code=u["stock_code"], corp_name=u["corp_name"],
                              report_nm=u["report_nm"], is_correction=True, kind="correction",
                              label=lb["label"] if lb else None, label_reason=lb["why"] if lb else "미라벨",
                              label_source="claude_v0", was_borderline=False, tag=None))
        elif u["rule"] == "exclude":
            n = normalize(u["report_nm"])
            if any(re.search(p, n) for p in EXCLUDE_PATTERNS):
                cases.append(dict(rcept_no=u["rcept_no"], day=u["day"], period="w0907", stock_code=u["stock_code"], corp_name=u["corp_name"],
                                  report_nm=u["report_nm"], is_correction=False, kind="rule_exclude", label="DROP",
                                  label_reason="공시명 규칙 필터 제외 유형(검증 전 가정)", label_source="rule_presumed",
                                  was_borderline=False, tag=None))
    json.dump(cases, open(os.path.join(CASES, "cases_v0.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    print(len(cases), dict(Counter(c["kind"] for c in cases)))
    for k in ("judged", "correction", "rule_exclude"):
        print(k, dict(Counter(c["label"] for c in cases if c["kind"] == k)))


if __name__ == "__main__":
    main()
