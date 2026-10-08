"""v1 vs v2 를 '새 라벨(정책 + 사람 명시 판정)'로 같은 잣대에서 비교한다.

사용법: python jev_test/eval_v2.py  ->  jev_test/runs/eval_v2.md
주의: 정책 계층 라벨은 v2 질문과 같은 정책으로 만들어졌으므로 v2 점수에는 순환성이 있다.
      사람이 직접 판정한 건(label_source=human)만 따로 집계한 표가 순환성이 없는 신호다(어려운 건 위주라 점수는 낮게 나온다).
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from compare_runs import load  # noqa: E402
from lib import load_cases  # noqa: E402
from score_run import ADV, EXCLUDE_PATTERNS, SEPARATE_PATTERNS, metrics, normalize  # noqa: E402

PER = [("w0907", "개발 9/7~9/11"), ("w0901", "검증 9/1~9/4"), ("w0930", "검증 9/30~10/1")]
METH = [
    ("Noul ≥0.5", lambda p: p.get("proceed_p", 0) >= 0.5),
    ("Noul ≥0.3", lambda p: p.get("proceed_p", 0) >= 0.3),
    ("Choice (PASS·PASS_CHECK·HOLD)", lambda p: p.get("triage") in ADV | {"HOLD"}),
    ("Score ≥2.0", lambda p: p.get("imp", 0) >= 2.0),
    ("앙상블 OR(Noul≥0.5·Choice·Score≥2.0)", lambda p: p.get("proceed_p", 0) >= 0.5 or p.get("triage") in ADV | {"HOLD"} or p.get("imp", 0) >= 2.0),
    ("앙상블 OR(Noul≥0.3·Choice)", lambda p: p.get("proceed_p", 0) >= 0.3 or p.get("triage") in ADV | {"HOLD"}),
    ("원자 Noul 조합", lambda p: p["comp"] in ADV | {"HOLD"}),
]


def pooled(exps_cfg):
    d = {}
    for exp, cfg in exps_cfg:
        p = os.path.join(HERE, "runs", exp, f"raw_{cfg}.jsonl")
        if os.path.exists(p):
            d.update(load(exp, cfg))
    return d


def fmt(m):
    if not (m["tp"] + m["fn"]):
        return "-"
    return f"{m['recall'] * 100:.0f}% ({m['fn']}/{m['tp'] + m['fn']}) / {m['precision'] * 100:.0f}%"


def sel(preds, cases, pred_fn, periods=None, kinds=("judged",), human_only=False, rule_first=False):
    rows = []
    for i, p in preds.items():
        c = cases[i]
        if c["kind"] not in kinds or (periods and c["period"] not in periods):
            continue
        if human_only and c["label_source"] != "human":
            continue
        if rule_first and any(re.search(pt, normalize(c["report_nm"])) for pt in EXCLUDE_PATTERNS + SEPARATE_PATTERNS):
            continue
        rows.append((c, pred_fn(p)))
    return rows


def main():
    cases = {c["rcept_no"]: c for c in load_cases()}
    runs = {"v1 TD-en": pooled([("w0907_v1", "TD-en"), ("val_v1", "TD-en")]), "v2 TD-en": pooled([("w_all_v2", "TD-en")]),
            "v1 TD-ko": pooled([("w0907_v1", "TD-ko"), ("val_v1", "TD-ko")]), "v2 TD-ko": pooled([("w_all_v2", "TD-ko")]),
            "v2 T-en": pooled([("w_all_v2", "T-en")])}
    L = ["# v1 vs v2 평가 (새 라벨: 정책 + 사람 명시 판정)\n",
         "표기: `재현율 (놓침/정답 진행) / 정밀도`. 진행 = PASS·PASS_CHECK·HOLD. 정답은 §0 라벨 분포 참고.\n"]
    cs = [c for c in cases.values() if c["kind"] in ("judged", "correction")]
    L.append(f"## 0. 라벨 분포\n\n- 판정 {sum(c['kind'] == 'judged' for c in cs)}건: {dict(Counter(c['label'] for c in cs if c['kind'] == 'judged'))}\n"
             f"- 정정 {sum(c['kind'] == 'correction' for c in cs)}건: {dict(Counter(c['label'] for c in cs if c['kind'] == 'correction'))}\n"
             f"- 라벨 출처: {dict(Counter(c['label_source'] for c in cs))}\n")
    for title, kw in (("1. 판정 공시 — 구간별", dict()), ("2. 사람이 직접 판정한 건만 (순환성 없음, 어려운 건 위주)", dict(human_only=True))):
        L.append(f"\n## {title}\n")
        for name, preds in runs.items():
            if name not in ("v1 TD-en", "v2 TD-en", "v2 TD-ko", "v1 TD-ko"):
                continue
            L.append(f"\n### {name}\n\n| 방식 | " + " | ".join(n for _, n in PER) + " | 전체 |\n|---|" + "---|" * (len(PER) + 1))
            for mn, fn in METH:
                cells = []
                for per in [[p] for p, _ in PER] + [None]:
                    m = metrics(sel(preds, cases, fn, periods=per, **kw), None, True)
                    cells.append(fmt(m))
                L.append(f"| {mn} | " + " | ".join(cells) + " |")
    # 정정 (유형 규칙 선행)
    L.append("\n## 3. 정정 공시 (정형 서류 정정은 유형 규칙으로 선행 제외), 개발 주간\n")
    L.append("| 방식 | v1 TD-en | v2 TD-en | v2 TD-ko |\n|---|---|---|---|")
    for mn, fn in METH:
        cells = [fmt(metrics(sel(runs[n], cases, fn, kinds=("correction",), rule_first=True), None, True)) for n in ("v1 TD-en", "v2 TD-en", "v2 TD-ko")]
        L.append(f"| {mn} | " + " | ".join(cells) + " |")
    # 임계값 스윕 (v2 TD-en, 판정 전체)
    L.append("\n## 4. Noul 임계값 스윕 (v2 TD-en, 판정 202건 전체 / 구간별 재현율)\n\n| 임계값 | 전체 재현율 / 정밀도 | 개발 | 검증 9/1~9/4 | 검증 9/30~10/1 |\n|---|---|---|---|---|")
    pick = None
    for t in (0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
        fn = lambda p, t=t: p.get("proceed_p", 0) >= t
        mt = metrics(sel(runs["v2 TD-en"], cases, fn), None, True)
        per = [metrics(sel(runs["v2 TD-en"], cases, fn, periods=[p]), None, True) for p, _ in PER]
        L.append(f"| ≥{t} | {fmt(mt)} | " + " | ".join(f"{m['recall'] * 100:.0f}%" for m in per) + " |")
        if mt["recall"] >= 0.95:
            pick = t
    L.append(f"\n재현율 95% 이상을 만족하는 가장 높은 Noul 임계값: **{pick}**\n")
    # 4단계 혼동행렬
    for nm, key in (("v2 TD-en", "triage"), ("v2 TD-en", "comp")):
        cm = defaultdict(Counter)
        for c, _ in sel(runs[nm], cases, lambda p: 0):
            cm[c["label"]][runs[nm][c["rcept_no"]][key]] += 1
        L.append(f"\n### {nm} {'Choice' if key == 'triage' else '원자 조합'} 혼동행렬 (판정 공시, 행=정답)\n\n| 정답＼예측 | PASS | PASS_CHECK | HOLD | DROP |\n|---|---:|---:|---:|---:|")
        for lab in ("PASS", "PASS_CHECK", "HOLD", "DROP"):
            if cm[lab]:
                L.append(f"| {lab} | " + " | ".join(str(cm[lab].get(x, 0)) for x in ("PASS", "PASS_CHECK", "HOLD", "DROP")) + " |")
    # 오류 목록
    P = runs["v2 TD-en"]
    L.append("\n## 5. v2 TD-en 오류 목록 (앙상블 OR Noul≥0.3·Choice 기준)\n")
    fn = METH[5][1]
    rows = sel(P, cases, fn)
    miss = [c for c, a in rows if c["label"] in ADV | {"HOLD"} and not a]
    fp = [c for c, a in rows if c["label"] == "DROP" and a]
    L.append(f"\n**놓친 건 {len(miss)}건**\n")
    for c in sorted(miss, key=lambda c: c["day"]):
        p = P[c["rcept_no"]]
        L.append(f"- [{c['day'][4:]}] {c['corp_name']} | {c['report_nm'][:30]} | 정답 {c['label']}({c['label_source']}) | Noul {p['proceed_p']:.2f}·{p['triage']}·{p['imp']:.1f} | {c['label_reason'][:70]}")
    L.append(f"\n**불필요 통과 {len(fp)}건**\n")
    for c in sorted(fp, key=lambda c: c["day"]):
        p = P[c["rcept_no"]]
        L.append(f"- [{c['day'][4:]}] {c['corp_name']} | {c['report_nm'][:30]} | 정답 DROP({c['label_source']}) | Noul {p['proceed_p']:.2f}·{p['triage']}·{p['imp']:.1f} | {c['label_reason'][:60]}")
    open(os.path.join(HERE, "runs", "eval_v2.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:110]))


if __name__ == "__main__":
    main()
