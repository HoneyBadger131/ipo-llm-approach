"""실험 채점: 네 가지 방식(Noul·Choice·Score·원자 Noul 조합)을 같은 정답셋으로 비교한다.

사용법: python jev_test/score_run.py <실험명>   ->  jev_test/runs/<실험명>/report.md

정답의 '진행'(advance) = PASS 또는 PASS_CHECK. HOLD는 두 가지로 따로 본다.
  (a) HOLD를 진행으로 간주(놓침 비용 우선 — 보류 건도 일단 다음 단계로 보내는 운영)
  (b) HOLD 제외(정답이 불확실한 건은 채점에서 뺌)
지표: 재현율(진행해야 할 것을 진행시킨 비율) — 가장 중요 / 정밀도 / 놓친 건 목록 / 불필요 통과 건 목록.
"""
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from dart_rules import EXCLUDE_PATTERNS, SEPARATE_PATTERNS, normalize  # noqa: E402
ADV = {"PASS", "PASS_CHECK"}


def composite(a, hi=0.5, uncertain=None):
    """원자 Noul -> 4단계 라벨. 보증 연장·대환(repeat_known + 금액)은 통과 선례를 따른다."""
    g = lambda k: a[k]["noul"] if k in a else 0.0
    if "material_change" in a:  # 정정 공시: 핵심 조건이 바뀌었는가
        if g("material_change") >= hi:
            return "PASS"
        return "HOLD" if uncertain and abs(g("material_change") - hi) < uncertain else "DROP"
    if g("monthly_results") >= hi:  # 월간 실적: 전년 동월 ±10% 이상일 때만 진행, 증감률이 없으면 계산 필요
        if g("yoy_big") >= hi:
            return "PASS"
        return "PASS_CHECK" if g("needs_comparison") >= hi else "DROP"
    pos = max(g("big_amount"), g("business_shift"), g("bio_clinical"), g("rumor_first"))
    if g("routine_admin") >= hi and g("big_amount") >= hi:
        return "HOLD"
    if g("routine_admin") >= hi and pos < hi:
        return "DROP"
    if g("repeat_known") >= hi and g("big_amount") < hi:
        return "DROP"
    if pos >= hi:
        if uncertain and abs(pos - hi) < uncertain:
            return "HOLD"
        return "PASS"
    if g("needs_comparison") >= hi:
        return "PASS_CHECK"
    return "DROP"


def predict(ans):
    """한 응답에서 방식별 예측을 뽑는다."""
    out = {}
    if "proceed" in ans:
        out["proceed_p"] = ans["proceed"]["noul"]
    if "triage" in ans:
        out["triage"] = ans["triage"]["choice"] if "choice" in ans["triage"] else max(ans["triage"]["probabilities"], key=ans["triage"]["probabilities"].get)
        out["triage_conf"] = ans["triage"].get("confidence")
    if "importance" in ans:
        out["imp"] = ans["importance"]["score"]
    out["comp"] = composite(ans)
    out["comp_u"] = composite(ans, uncertain=0.15)
    out["atomic"] = {k: round(v["noul"], 2) for k, v in ans.items() if v["type"] == "noul" and k not in ("proceed",)}
    return out


def metrics(rows, pred_adv, hold_as_adv):
    """rows: [(case, pred_advance_bool)]. 반환: tp, fn, fp, tn 및 오류 목록"""
    tp = fn = fp = tn = 0
    miss, extra = [], []
    for c, adv in rows:
        lab = c["label"]
        if lab == "HOLD":
            if not hold_as_adv:
                continue
            truth = True
        else:
            truth = lab in ADV
        if truth and adv:
            tp += 1
        elif truth and not adv:
            fn += 1
            miss.append(c)
        elif not truth and adv:
            fp += 1
            extra.append(c)
        else:
            tn += 1
    rec = tp / (tp + fn) if tp + fn else float("nan")
    pre = tp / (tp + fp) if tp + fp else float("nan")
    return dict(tp=tp, fn=fn, fp=fp, tn=tn, recall=rec, precision=pre, miss=miss, extra=extra)


def fmt(m):
    return f"{m['recall'] * 100:.0f}% ({m['tp']}/{m['tp'] + m['fn']}) | {m['precision'] * 100:.0f}% ({m['tp']}/{m['tp'] + m['fp']}) | {m['fn']} | {m['fp']}"


def main():
    exp = sys.argv[1]
    cases = {c["rcept_no"]: c for c in json.load(open(os.path.join(HERE, "cases", "cases_v0.json"), encoding="utf-8"))}
    runs = {}
    for p in sorted(glob.glob(os.path.join(HERE, "runs", exp, "raw_*.jsonl"))):
        cfg = os.path.basename(p)[4:-6]
        runs[cfg] = {}
        for l in open(p, encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                if "answers" in r["resp"]:
                    runs[cfg][r["rcept_no"]] = predict(r["resp"]["answers"])
    L = [f"# 실험 {exp} 채점 보고서\n"]
    L.append("정답 라벨은 Claude 위임 판정(claude_v0, 사람 검수 전)이다. 표본이 작아 수치는 경향 참고용이다.\n")
    for cfg, preds in runs.items():
        L.append(f"\n## 설정 {cfg}\n")
        for scope, kinds in (("판정 82건(judged)", {"judged"}), ("정정 공시(correction)", {"correction"}),
                             ("정정 공시 — 공시 유형 규칙 선행(정형 서류 정정 11건을 Jev 이전에 제외)", {"correction"})):
            rows = [(cases[i], p) for i, p in preds.items() if cases[i]["kind"] in kinds]
            if "유형 규칙 선행" in scope:
                rows = [(c, p) for c, p in rows if not any(re.search(pt, normalize(c["report_nm"])) for pt in EXCLUDE_PATTERNS + SEPARATE_PATTERNS)]
            if not rows:
                continue
            L.append(f"\n### {scope} — {len(rows)}건, 정답 분포 {dict(Counter(c['label'] for c, _ in rows))}\n")
            for hold_adv, name in ((True, "HOLD=진행 간주"), (False, "HOLD 제외")):
                L.append(f"\n**{name}**\n\n| 방식 | 재현율 | 정밀도 | 놓침 | 불필요 통과 |\n|---|---|---|---|---|")
                for meth, fn_ in (
                    ("Noul proceed ≥0.5", lambda p: p.get("proceed_p", 0) >= 0.5),
                    ("Noul proceed ≥0.3", lambda p: p.get("proceed_p", 0) >= 0.3),
                    ("Choice triage(PASS·PASS_CHECK)", lambda p: p.get("triage") in ADV),
                    ("Choice triage(HOLD도 진행)", lambda p: p.get("triage") in ADV | {"HOLD"}),
                    ("Score importance ≥2.5", lambda p: p.get("imp", 0) >= 2.5),
                    ("Score importance ≥2.0", lambda p: p.get("imp", 0) >= 2.0),
                    ("앙상블 OR(Noul≥0.5 | Choice | Score≥2.0)", lambda p: p.get("proceed_p", 0) >= 0.5 or p.get("triage") in ADV | {"HOLD"} or p.get("imp", 0) >= 2.0),
                    ("앙상블 2-of-3(Noul≥0.5, Choice, Score≥2.0)", lambda p: (p.get("proceed_p", 0) >= 0.5) + (p.get("triage") in ADV | {"HOLD"}) + (p.get("imp", 0) >= 2.0) >= 2),
                    ("앙상블 OR(Noul≥0.3 | Choice)", lambda p: p.get("proceed_p", 0) >= 0.3 or p.get("triage") in ADV | {"HOLD"}),
                    ("조합 composite", lambda p: p["comp"] in ADV),
                    ("조합 composite(HOLD도 진행)", lambda p: p["comp"] in ADV | {"HOLD"}),
                    ("조합 composite_u(불확실→HOLD, HOLD도 진행)", lambda p: p["comp_u"] in ADV | {"HOLD"}),
                ):
                    m = metrics([(c, fn_(p)) for c, p in rows], None, hold_adv)
                    L.append(f"| {meth} | {fmt(m)} |")
            # 4단계 라벨 혼동행렬 (Choice, 조합)
            for meth, key in (("Choice triage", "triage"), ("조합 composite", "comp")):
                cm = defaultdict(Counter)
                for c, p in rows:
                    cm[c["label"]][p.get(key)] += 1
                L.append(f"\n{meth} 혼동행렬 (행=정답, 열=예측)\n\n| 정답＼예측 | PASS | PASS_CHECK | HOLD | DROP |\n|---|---:|---:|---:|---:|")
                for lab in ("PASS", "PASS_CHECK", "HOLD", "DROP"):
                    if cm[lab]:
                        L.append(f"| {lab} | " + " | ".join(str(cm[lab].get(x, 0)) for x in ("PASS", "PASS_CHECK", "HOLD", "DROP")) + " |")
            # 놓친 건 (정답=진행인데 Choice·Noul 둘 다 놓친 건)
            both = [c for c, p in rows if c["label"] in ADV and p.get("triage") not in ADV | {"HOLD"} and p.get("proceed_p", 0) < 0.5]
            if both:
                L.append("\n**Noul·Choice가 모두 놓친 진행 대상**\n")
                for c in both:
                    L.append(f"- [{c['day'][4:]}] {c['corp_name']} | {c['report_nm'][:50]} | 정답 {c['label']} | {c['label_reason'][:90]}")
        # 규칙 필터 제외 유형을 Jev에게 시켰을 때
        rx = [(cases[i], p) for i, p in preds.items() if cases[i]["kind"] == "rule_exclude"]
        if rx:
            adv = [(c, p) for c, p in rx if p.get("proceed_p", 0) >= 0.5 or p.get("triage") in ADV or p["comp"] in ADV]
            L.append(f"\n### 규칙 필터가 제외한 {len(rx)}건을 Jev에 넣었을 때 (제목만)\n")
            L.append(f"Noul≥0.5 진행 {sum(1 for c, p in rx if p.get('proceed_p', 0) >= 0.5)}건 / Choice 진행 {sum(1 for c, p in rx if p.get('triage') in ADV)}건 / 조합 진행 {sum(1 for c, p in rx if p['comp'] in ADV)}건 / "
                     f"Choice HOLD {sum(1 for c, p in rx if p.get('triage') == 'HOLD')}건. 아래는 어느 한 방식이라도 진행으로 본 건(규칙 필터가 놓쳤을 가능성 점검 대상)이다.\n")
            cnt = Counter()
            for c, p in adv:
                cnt[c["report_nm"][:30]] += 1
            for k, v in cnt.most_common(30):
                L.append(f"- {k} × {v}")
    open(os.path.join(HERE, "runs", exp, "report.md"), "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L)[:6000])


if __name__ == "__main__":
    main()
