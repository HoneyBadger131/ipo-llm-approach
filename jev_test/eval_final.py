"""운영 시나리오 평가: 자회사 사본·부속 공시를 먼저 제거한 뒤(운영의 자회사 중복 단계), v1/v2/v2b 를 같은 라벨로 비교한다.

사용법: python jev_test/eval_final.py  ->  jev_test/runs/eval_final.md
라벨 = Claude 기본 < 정책 < 사람 명시 판정. 진행 = PASS·PASS_CHECK·HOLD.
운영 구성(제안): Noul ≥ HI → 진행, LO ≤ Noul < HI → 회색(HOLD: 진행 + 검수 표시), Noul < LO → DROP.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from eval_v2 import pooled  # noqa: E402
from lib import load_cases  # noqa: E402
from score_run import ADV, metrics  # noqa: E402

RUNS = {
    "v1 TD-en": [("w0907_v1", "TD-en"), ("val_v1", "TD-en")],
    "v2 TD-en": [("w_all_v2", "TD-en")],
    "v2b TD-en": [("w_all_v2b", "TD-en")],
    "v2b TD-ko": [("w_all_v2b", "TD-ko")],
}


def is_dup(c):
    return bool(re.search(r"중복|부속|사본", c["label_reason"])) or "(자회사" in c["report_nm"] or "(종속회사" in c["report_nm"]


def main():
    cases = {c["rcept_no"]: c for c in load_cases()}
    L = ["# 운영 시나리오 평가 (자회사 사본 제거 후, 새 라벨)\n"]
    base = [c for c in cases.values() if c["kind"] == "judged" and not is_dup(c)]
    adv = lambda c: c["label"] in ADV | {"HOLD"}
    L.append(f"- 대상 {len(base)}건(자회사 사본·부속 {sum(1 for c in cases.values() if c['kind'] == 'judged' and is_dup(c))}건 제외), 정답 진행 {sum(adv(c) for c in base)}건, "
             f"사람 명시 판정 {sum(c['label_source'] == 'human' for c in base)}건\n")
    L.append("## 1. Noul 임계값별 재현율 (놓침/정답 진행) / 정밀도 / 진행 건수\n\n| 설정 | ≥0.2 | ≥0.3 | ≥0.5 |\n|---|---|---|---|")
    P = {n: pooled(r) for n, r in RUNS.items()}
    for n, preds in P.items():
        cells = []
        for t in (0.2, 0.3, 0.5):
            rows = [(c, preds[c["rcept_no"]]["proceed_p"] >= t) for c in base if c["rcept_no"] in preds]
            m = metrics(rows, None, True)
            cells.append(f"{m['recall'] * 100:.0f}% ({m['fn']}/{m['tp'] + m['fn']}) / {m['precision'] * 100:.0f}% / {m['tp'] + m['fp']}건")
        L.append(f"| {n} | " + " | ".join(cells) + " |")
    L.append("\n## 2. 구간별 재현율 (Noul ≥0.2)\n\n| 설정 | 개발 9/7~9/11 | 검증 9/1~9/4 | 검증 9/30~10/1 |\n|---|---|---|---|")
    for n, preds in P.items():
        cells = []
        for per in ("w0907", "w0901", "w0930"):
            m = metrics([(c, preds[c["rcept_no"]]["proceed_p"] >= 0.2) for c in base if c["period"] == per and c["rcept_no"] in preds], None, True)
            cells.append(f"{m['recall'] * 100:.0f}% ({m['fn']}/{m['tp'] + m['fn']}) / {m['precision'] * 100:.0f}%")
        L.append(f"| {n} | " + " | ".join(cells) + " |")
    L.append("\n## 3. 제안 운영 구성: Noul ≥0.5 진행 / 0.2~0.5 회색(HOLD=진행+검수 표시) / <0.2 DROP\n\n| 설정 | ≥0.5 (정답 진행) | 회색 0.2~0.5 (정답 진행) | <0.2 (정답 진행) | 하루 회색 건수 |\n|---|---|---|---|---|")
    days = len({c["day"] for c in base})
    for n, preds in P.items():
        rows = [(c, preds[c["rcept_no"]]["proceed_p"]) for c in base if c["rcept_no"] in preds]
        hi = [c for c, p in rows if p >= 0.5]
        g = [c for c, p in rows if 0.2 <= p < 0.5]
        lo = [c for c, p in rows if p < 0.2]
        L.append(f"| {n} | {len(hi)} ({sum(adv(c) for c in hi)}) | {len(g)} ({sum(adv(c) for c in g)}) | {len(lo)} ({sum(adv(c) for c in lo)}) | {len(g) / days:.1f} |")
    L.append("\n## 4. 사람이 직접 판정한 건만 (순환성 없음)\n\n| 설정 | Noul ≥0.2 | Noul ≥0.5 | Choice(진행·HOLD) |\n|---|---|---|---|")
    for n, preds in P.items():
        cells = []
        for fn in (lambda p: p["proceed_p"] >= 0.2, lambda p: p["proceed_p"] >= 0.5, lambda p: p["triage"] in ADV | {"HOLD"}):
            m = metrics([(c, fn(preds[c["rcept_no"]])) for c in base if c["label_source"] == "human" and c["rcept_no"] in preds], None, True)
            cells.append(f"{m['recall'] * 100:.0f}% ({m['fn']}/{m['tp'] + m['fn']}) / {m['precision'] * 100:.0f}%")
        L.append(f"| {n} | " + " | ".join(cells) + " |")
    pv = P["v2b TD-en"]
    L.append("\n## 5. v2b TD-en, Noul ≥0.2 에서 놓친 건\n")
    for c in sorted(base, key=lambda c: c["day"]):
        p = pv.get(c["rcept_no"])
        if p and adv(c) and p["proceed_p"] < 0.2:
            L.append(f"- [{c['day'][4:]}] {c['corp_name']} | {c['report_nm'][:34]} | 정답 {c['label']}({c['label_source']}) | Noul {p['proceed_p']:.2f} | {c['label_reason'][:80]}")
    open(os.path.join(HERE, "runs", "eval_final.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
