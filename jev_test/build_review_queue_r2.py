"""2차 사람 검토 큐. 1차 반영 + 정책 v0.3 + 질문 v2b 결과를 바탕으로 '사람이 정해야 하는 것'만 모았다.

사용법: python jev_test/build_review_queue_r2.py  ->  jev_test/review/human_review_queue_r2.csv (UTF-8 BOM)
채워서 돌려받은 뒤:  python jev_test/apply_review.py <채워진.csv> jev_test/review/human_review_queue_r2.csv

포함 기준 (자회사 사본·부속 공시는 운영의 자회사 중복 단계가 처리하므로 제외)
  A 정책 답변과 사람 라벨의 충돌          — 어느 쪽이 맞는지 정해 달라
  B 정책 규칙이 바꾼 라벨                  — 정책을 기계적으로 적용한 것이라 확인이 필요
  C Jev 회색지대(Noul 0.2~0.5)             — 운영에서 HOLD(진행+검수 표시)가 될 건들
  D 라벨 의심: 정답은 탈락인데 Jev가 강하게 진행(Noul≥0.8), 또는 정답은 진행인데 Jev가 강하게 탈락(<0.1)
"""
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from eval_final import is_dup  # noqa: E402
from eval_v2 import pooled  # noqa: E402
from lib import load_cases  # noqa: E402
from policy_relabel import policy_label  # noqa: E402
from score_run import ADV  # noqa: E402

PER = {"w0907": "개발 9/7~9/11", "w0901": "검증 9/1~9/4", "w0930": "검증 9/30~10/1"}


def main():
    cases = {c["rcept_no"]: c for c in load_cases()}
    P = pooled([("w_all_v2b", "TD-en")])
    pol = json.load(open(os.path.join(HERE, "cases", "labels_policy.json"), encoding="utf-8"))
    rows = []
    for i, c in cases.items():
        if c["kind"] not in ("judged", "correction") or is_dup(c) or i not in P:
            continue
        p = P[i]
        n = p["proceed_p"]
        adv = c["label"] in ADV | {"HOLD"}
        why = []
        if c["label_source"] == "human":
            lab, rule, _ = policy_label(dict(c, label=c.get("label_ai", c["label"])))
            if rule and lab != c["label"] and not c["is_correction"]:
                why.append(f"A 정책({rule}) {lab} vs 사람 {c['label']}")
        if i in pol:
            why.append(f"B 정책({pol[i]['rule']})이 {pol[i]['was']}→{pol[i]['label']}로 바꿈: {pol[i]['why']}")
        if 0.2 <= n < 0.5:
            why.append("C Jev 회색지대(0.2~0.5)")
        if (not adv and n >= 0.8) or (adv and n < 0.1):
            why.append("D 라벨 의심(Jev와 강하게 불일치)")
        if not why:
            continue
        pr = 1 if any(w.startswith(("A", "D")) for w in why) else (2 if any(w.startswith("B") for w in why) else 3)
        rows.append((pr, c["day"], c["corp_name"], {
            "우선순위": pr, "검토사유": "; ".join(why), "구간": PER[c["period"]], "날짜": c["day"], "종목코드": "'" + c["stock_code"] if False else c["stock_code"],
            "회사": c["corp_name"], "공시명": c["report_nm"], "접수번호": c["rcept_no"],
            "DART 링크": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={c['rcept_no']}",
            "현재 라벨": c["label"], "라벨 출처": c["label_source"], "라벨 근거": c["label_reason"][:260],
            "Jev Noul(v2b TD-en)": f"{n:.2f}", "Jev Choice": p["triage"], "Jev 중요도(0~4)": f"{p['imp']:.1f}",
            "사람 판정(PASS/PASS_CHECK/HOLD/DROP)": "", "사람 메모": ""}))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    out = []
    for k, (_, _, _, r) in enumerate(rows, 1):
        out.append({"행ID": f"R2-{k:03d}", **r})
    path = os.path.join(HERE, "review", "human_review_queue_r2.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    from collections import Counter
    print(len(out), "행 →", path, "| 우선순위", dict(sorted(Counter(r["우선순위"] for r in out).items())),
          "| 사유", dict(Counter(w[0] for r in out for w in r["검토사유"].split("; "))))


if __name__ == "__main__":
    main()
