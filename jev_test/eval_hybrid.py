"""하이브리드(하드 규칙 + Jev v3 + 시총 구간 임계값) 평가 — 저장된 Jev 응답만 쓰므로 API 호출이 없다.

사용법: python jev_test/eval_hybrid.py [응답실험명=w_all_v3] [--cases-period w0907,w0901,w0930]  ->  jev_test/runs/eval_hybrid_<실험명>.md
대상: 판정 공시 중 자회사 사본·부속 공시를 제외한 운영 대상. 라벨 = 사람 명시 > 정책 > Claude.
지표: 노출(SURF=PASS·PASS_CHECK·NOTIFY·HOLD) 재현율/정밀도, 분석 진행(ANALYZE=PASS·PASS_CHECK·HOLD) 기준, 5×5 혼동행렬, 구간별.
"""
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from eval_final import is_dup  # noqa: E402
from lib import load_cases, read_body  # noqa: E402
from score_run import SURF, metrics  # noqa: E402
from triage import ANALYZE, triage_case  # noqa: E402

LABELS = ["PASS", "PASS_CHECK", "NOTIFY", "HOLD", "DROP"]


def load_resp(exp):
    d = {}
    for l in open(os.path.join(HERE, "runs", exp, "raw_TD-en.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        d[r["rcept_no"]] = r["resp"]
    return d


def main():
    exp = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "w_all_v3"
    periods = set(sys.argv[sys.argv.index("--cases-period") + 1].split(",")) if "--cases-period" in sys.argv else None
    resp = load_resp(exp)
    cases = [c for c in load_cases() if c["kind"] == "judged" and not is_dup(c) and c["rcept_no"] in resp and (periods is None or c["period"] in periods)]
    out = []
    for c in cases:
        t = triage_case(c, read_body(c), resp=resp[c["rcept_no"]])
        out.append((c, t))
    L = [f"# 하이브리드 평가 ({exp}, 대상 {len(cases)}건)\n"]
    L.append(f"- 라벨 분포(정답): {dict(Counter(c['label'] for c, _ in out))}")
    L.append(f"- 하드 규칙이 확정한 건 {sum(t['source'] == 'rule' for _, t in out)}건, Jev가 판단한 건 {sum(t['source'] == 'jev' for _, t in out)}건\n")

    def block(title, rows):
        m = metrics([(c, t["label"] in SURF) for c, t in rows], None, True)
        ma = metrics([(c, c["label"] in {"PASS", "PASS_CHECK", "HOLD"}, ) for c, t in rows], None, True)
        ana = [(c, t["label"] in ANALYZE) for c, t in rows]
        truth = lambda c: c["label"] in {"PASS", "PASS_CHECK", "HOLD"}
        tp = sum(1 for c, a in ana if a and truth(c)); fn = sum(1 for c, a in ana if not a and truth(c)); fp = sum(1 for c, a in ana if a and not truth(c))
        L.append(f"| {title} | {len(rows)} | {m['recall'] * 100:.0f}% ({m['fn']}/{m['tp'] + m['fn']}) | {m['precision'] * 100:.0f}% | {m['tp'] + m['fp']} | "
                 f"{tp / (tp + fn) * 100 if tp + fn else float('nan'):.0f}% ({fn}/{tp + fn}) | {tp / (tp + fp) * 100 if tp + fp else float('nan'):.0f}% |")

    L.append("## 1. 지표 (노출 = PASS·PASS_CHECK·NOTIFY·HOLD, 분석 = PASS·PASS_CHECK·HOLD)\n\n| 구분 | 건수 | 노출 재현율 | 노출 정밀도 | 노출 건수 | 분석 재현율 | 분석 정밀도 |\n|---|---:|---|---|---:|---|---|")
    block("전체", out)
    for per, nm in (("w0907", "개발 9/7~9/11"), ("w0901", "검증 9/1~9/4"), ("w0930", "검증 9/30~10/1")):
        block(nm, [(c, t) for c, t in out if c["period"] == per])
    for tr in ("large", "other"):
        block(f"시총 구간 {tr}", [(c, t) for c, t in out if t["tier"] == tr])
    block("하드 규칙이 확정한 건", [(c, t) for c, t in out if t["source"] == "rule"])
    block("Jev가 판단한 건", [(c, t) for c, t in out if t["source"] == "jev"])
    cm = defaultdict(Counter)
    for c, t in out:
        cm[c["label"]][t["label"]] += 1
    L.append("\n## 2. 혼동행렬 (행=정답 라벨, 열=하이브리드)\n\n| 정답＼예측 | " + " | ".join(LABELS) + " |\n|---|" + "---:|" * len(LABELS))
    for lab in LABELS:
        if cm[lab]:
            L.append(f"| {lab} | " + " | ".join(str(cm[lab].get(x, 0)) for x in LABELS) + " |")
    ok = sum(1 for c, t in out if c["label"] == t["label"])
    ok_c = sum(1 for c, t in out if (c["label"] in SURF) == (t["label"] in SURF))
    L.append(f"\n라벨 5종 정확 일치 {ok}/{len(out)} ({ok / len(out) * 100:.0f}%), 노출 여부 일치 {ok_c}/{len(out)} ({ok_c / len(out) * 100:.0f}%)")
    miss = [(c, t) for c, t in out if c["label"] in SURF and t["label"] not in SURF]
    fpos = [(c, t) for c, t in out if c["label"] == "DROP" and t["label"] in SURF]
    L.append(f"\n## 3. 놓친 건 {len(miss)}건 (정답 노출 → 하이브리드 DROP)\n")
    for c, t in miss:
        L.append(f"- [{c['day'][4:]}] {c['corp_name']} | {c['report_nm'][:30]} | 정답 {c['label']}({c['label_source']}) | {t['reason']} | {c['label_reason'][:60]}")
    L.append(f"\n## 4. 불필요 노출 {len(fpos)}건 (정답 DROP → 하이브리드 노출)\n")
    for c, t in sorted(fpos, key=lambda x: x[0]["day"]):
        L.append(f"- [{c['day'][4:]}] {c['corp_name']} | {c['report_nm'][:30]} | 하이브리드 {t['label']} ({t['source']}:{t['rule']}) | {t['reason']} | {c['label_reason'][:50]}")
    open(os.path.join(HERE, "runs", f"eval_hybrid_{exp}.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
