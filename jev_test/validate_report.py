"""v1 검증 보고서: 개발 주간(w0907)과 검증 주간(w0901, w0930)을 같은 설정·같은 임계값으로 비교한다.

사용법: python jev_test/validate_report.py w0907_v1 val_v1   ->  jev_test/runs/validation_report.md
검증 주간은 v1 질문·전처리·임계값(0.5, 0.3 등)을 고치지 않고 그대로 적용한 결과다.
정답은 기존 Claude 판정(judgments.json)의 가/부이며 사람 검수 전이다.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from compare_runs import METHODS, load  # noqa: E402
from lib import load_cases  # noqa: E402
from score_run import ADV, SURF, metrics  # noqa: E402

CFGS = ("TD-en", "TD-ko", "T-en")
PERIODS = [("w0907", "개발 주간 9/7~9/11"), ("w0901", "검증 9/1~9/4"), ("w0930", "검증 9/30~10/1")]


def main():
    dev_exp, val_exp = sys.argv[1], sys.argv[2]
    cases = {c["rcept_no"]: c for c in load_cases()}
    L = ["# v1 검증 보고서\n",
         "질문·전처리·임계값을 고치지 않고 개발 주간에서 정한 v1을 새 주간에 그대로 적용했다. 정답은 기존 Claude 판정(가→PASS, 부→DROP)이며 사람 검수 전이다.\n",
         "표기: `재현율% (놓친 건수/정답 진행 건수) / 정밀도%`. 재현율이 1순위(놓침은 복구 불가)다.\n"]
    data = {}
    for cfg in CFGS:
        preds = {}
        for exp in (dev_exp, val_exp):
            p = os.path.join(HERE, "runs", exp, f"raw_{cfg}.jsonl")
            if os.path.exists(p):
                preds.update(load(exp, cfg))
        data[cfg] = {i: pr for i, pr in preds.items() if cases[i]["kind"] == "judged"}
    # 기저율
    L.append("## 1. 표본 규모\n\n| 구간 | 판정 건수 | 정답 진행(PASS 계열) | 진행 비율 | 경계(borderline) |\n|---|---:|---:|---:|---:|")
    for per, name in PERIODS:
        cs = [c for c in cases.values() if c["period"] == per and c["kind"] == "judged"]
        adv = [c for c in cs if c["label"] in SURF]
        L.append(f"| {name} | {len(cs)} | {len(adv)} | {len(adv) / len(cs) * 100:.0f}% | {sum(c['was_borderline'] for c in cs)} |")
    for cfg in CFGS:
        L.append(f"\n## 2. 설정 {cfg} — 방식별 재현율 / 정밀도\n")
        L.append("| 방식 | " + " | ".join(n for _, n in PERIODS) + " | 검증 합계(9/1~4 + 9/30~10/1) |\n|---|" + "---|" * (len(PERIODS) + 1))
        for name, fn in METHODS:
            cells = []
            for per, _ in PERIODS + [("val", "")]:
                rows = [(cases[i], fn(p)) for i, p in data[cfg].items()
                        if (cases[i]["period"] == per if per != "val" else cases[i]["period"] in ("w0901", "w0930"))]
                m = metrics(rows, None, True)
                cells.append(f"{m['recall'] * 100:.0f}% ({m['fn']}/{m['tp'] + m['fn']}) / {m['precision'] * 100:.0f}%" if rows else "-")
            L.append(f"| {name} | " + " | ".join(cells) + " |")
    # Noul 임계값 스윕 (TD-en)
    L.append("\n## 3. Noul 임계값 스윕 (TD-en, 재현율 / 정밀도)\n")
    L.append("| 임계값 | " + " | ".join(n for _, n in PERIODS) + " | 검증 합계 |\n|---|" + "---|" * (len(PERIODS) + 1))
    for t in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
        cells = []
        for per, _ in PERIODS + [("val", "")]:
            rows = [(cases[i], p.get("proceed_p", 0) >= t) for i, p in data["TD-en"].items()
                    if (cases[i]["period"] == per if per != "val" else cases[i]["period"] in ("w0901", "w0930"))]
            m = metrics(rows, None, True)
            cells.append(f"{m['recall'] * 100:.0f}% / {m['precision'] * 100:.0f}%")
        L.append(f"| ≥{t} | " + " | ".join(cells) + " |")
    # 오류 목록 (TD-en, Noul ≥0.5 / 앙상블)
    L.append("\n## 4. 검증 주간 오류 목록 (TD-en)\n")
    for title, fn in (("Noul ≥0.5", lambda p: p.get("proceed_p", 0) >= 0.5),
                      ("앙상블 OR(Noul≥0.5·Choice·Score≥2.0)", METHODS[4][1])):
        rows = [(cases[i], fn(p), p) for i, p in data["TD-en"].items() if cases[i]["period"] in ("w0901", "w0930")]
        miss = [(c, p) for c, a, p in rows if c["label"] in ADV and not a]
        extra = [(c, p) for c, a, p in rows if c["label"] == "DROP" and a]
        L.append(f"\n### {title}\n\n**놓친 건 {len(miss)}건** (정답=진행, Jev=탈락)\n")
        for c, p in sorted(miss, key=lambda x: x[0]["day"]):
            L.append(f"- [{c['day'][4:]}] {c['corp_name']} | {c['report_nm'][:34]} | Noul {p['proceed_p']:.2f} · {p['triage']} · 중요도 {p['imp']:.1f} | 기존 판정 사유: {c['label_reason'][:80]}")
        L.append(f"\n**불필요 통과 {len(extra)}건** (정답=탈락, Jev=진행)\n")
        for c, p in sorted(extra, key=lambda x: x[0]["day"]):
            L.append(f"- [{c['day'][4:]}] {c['corp_name']} | {c['report_nm'][:34]} | Noul {p['proceed_p']:.2f} · {p['triage']} · 중요도 {p['imp']:.1f} | 기존 판정 사유: {c['label_reason'][:80]}")
    open(os.path.join(HERE, "runs", "validation_report.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:60]))


if __name__ == "__main__":
    main()
