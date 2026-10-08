"""여러 실험(v0/v1 등)의 핵심 지표를 한 표로 모은다.

사용법: python jev_test/compare_runs.py w0907_v0 w0907_v1  ->  jev_test/runs/comparison.md
범위: (A) 판정 82건, (B) 정정 공시 중 정형 서류 정정을 유형 규칙으로 먼저 제외한 23건. HOLD는 진행으로 간주(놓침 우선).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from score_run import ADV, EXCLUDE_PATTERNS, SEPARATE_PATTERNS, metrics, normalize, predict  # noqa: E402

METHODS = [
    ("Noul ≥0.5", lambda p: p.get("proceed_p", 0) >= 0.5),
    ("Noul ≥0.3", lambda p: p.get("proceed_p", 0) >= 0.3),
    ("Choice (HOLD 포함)", lambda p: p.get("triage") in ADV | {"HOLD"}),
    ("Score ≥2.0", lambda p: p.get("imp", 0) >= 2.0),
    ("앙상블 OR(Noul≥0.5·Choice·Score≥2.0)", lambda p: p.get("proceed_p", 0) >= 0.5 or p.get("triage") in ADV | {"HOLD"} or p.get("imp", 0) >= 2.0),
    ("원자 Noul 조합(HOLD 포함)", lambda p: p["comp"] in ADV | {"HOLD"}),
]


def load(exp, cfg):
    path = os.path.join(HERE, "runs", exp, f"raw_{cfg}.jsonl")
    out = {}
    for l in open(path, encoding="utf-8"):
        r = json.loads(l)
        if "answers" in r["resp"]:
            out[r["rcept_no"]] = predict(r["resp"]["answers"])
    return out


def main():
    exps = sys.argv[1:]
    cases = {c["rcept_no"]: c for c in json.load(open(os.path.join(HERE, "cases", "cases_v0.json"), encoding="utf-8"))}
    L = ["# 실험 비교 (재현율 / 정밀도, HOLD는 진행으로 간주)\n",
         "표기: `재현율% / 정밀도%`. 재현율 = 진행해야 할 공시를 놓치지 않은 비율(가장 중요), 정밀도 = 진행시킨 것 중 맞는 비율.\n"]
    for scope, kinds, rule_first in (("A. 판정 82건", {"judged"}, False), ("B. 정정 공시 23건 (정형 서류 정정은 유형 규칙으로 선행 제외)", {"correction"}, True)):
        L.append(f"\n## {scope}\n")
        cols = [(e, cfg) for e in exps for cfg in ("T-en", "T-ko", "TD-en", "TD-ko") if os.path.exists(os.path.join(HERE, "runs", e, f"raw_{cfg}.jsonl"))]
        L.append("| 방식 | " + " | ".join(f"{e[-2:]} {cfg}" for e, cfg in cols) + " |")
        L.append("|---|" + "---|" * len(cols))
        data = {}
        for e, cfg in cols:
            preds = load(e, cfg)
            rows = [(cases[i], p) for i, p in preds.items() if cases[i]["kind"] in kinds]
            if rule_first:
                rows = [(c, p) for c, p in rows if not any(re.search(pt, normalize(c["report_nm"])) for pt in EXCLUDE_PATTERNS + SEPARATE_PATTERNS)]
            data[(e, cfg)] = rows
        for name, fn in METHODS:
            cells = []
            for key in cols:
                m = metrics([(c, fn(p)) for c, p in data[key]], None, True)
                cells.append(f"{m['recall'] * 100:.0f} / {m['precision'] * 100:.0f}")
            L.append(f"| {name} | " + " | ".join(cells) + " |")
    open(os.path.join(HERE, "runs", "comparison.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
