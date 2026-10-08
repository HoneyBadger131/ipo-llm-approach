"""사람 검토 큐(CSV) 생성. 엑셀에서 열어 '사람 판정' 열을 채워 돌려주면 apply_review.py 로 반영한다.

포함 기준: 라벨 HOLD / PASS_CHECK, Claude 경계(borderline) 표시, Jev와 정답 불일치(놓침·불필요 통과), Jev 확률이 경계(0.3~0.7),
          규칙 필터가 닫았는데 Jev가 진행으로 본 비정형 유형(점검용).
사용법: python jev_test/build_review_queue.py  ->  jev_test/review/human_review_queue.csv (UTF-8 BOM, 엑셀 호환)
"""
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from compare_runs import METHODS, load  # noqa: E402
from lib import load_cases  # noqa: E402

ADV = {"PASS", "PASS_CHECK"}
SURF = ADV | {"HOLD", "NOTIFY"}
ENS = METHODS[4][1]
RUNS = [("w0907_v1", "TD-en", "v1 TD-en"), ("val_v1", "TD-en", "v1 TD-en")]
PERIOD_NAME = {"w0907": "개발 9/7~9/11", "w0901": "검증 9/1~9/4", "w0930": "검증 9/30~10/1"}


def hint(c):
    r, t = c["label_reason"], c["report_nm"]
    h = []
    if re.search(r"중복|부속|사본", r):
        h.append("자회사 사본·부속 공시 가능성(자회사 중복 단계 처리 유형)")
    if re.search(r"정례|차환", r) and c["label"] in ("DROP", "HOLD"):
        h.append("정례 자금운용·차환: 금액 규칙(30억↑) vs 정례 규칙 충돌")
    if "재공시" in r:
        h.append("재공시(이미 공시된 사안)")
    if re.search(r"영업.*잠정|월간", t + r):
        h.append("월간 실적: 전년 동월 ±10% 규칙")
    if re.search(r"임상", t + r):
        h.append("임상 규칙(변경 승인도 통과)")
    if c["is_correction"]:
        h.append("정정 공시: 금액 ±10%↑ 통과 / 30억↑ 통과·확인 / 일정·오기 탈락")
    return " | ".join(h)


def main():
    cases = {c["rcept_no"]: c for c in load_cases()}
    jev = {}
    for exp, cfg, name in RUNS:
        for i, p in load(exp, cfg).items():
            jev[i] = (p, name)
    rule_audit = {}
    for i, p in load("w0907_v0", "T-en").items():
        c = cases[i]
        if c["kind"] == "rule_exclude" and p["proceed_p"] >= 0.5 and re.search(r"주주총회|결과보고서|계열회사", c["report_nm"]):
            rule_audit[i] = (p, "v0 T-en(제목만)")
    rows = []
    for i, c in cases.items():
        why = []
        p, src = jev.get(i, rule_audit.get(i, (None, "")))
        if c["kind"] == "rule_exclude":
            if i not in rule_audit:
                continue
            why.append("규칙 필터 점검(필터가 닫았으나 Jev는 진행으로 봄)")
        else:
            if p is None:
                continue
            if c["label"] == "HOLD":
                why.append("라벨 보류(HOLD)")
            if c["label"] == "PASS_CHECK":
                why.append("라벨 통과·확인(PASS_CHECK)")
            if c["was_borderline"]:
                why.append("Claude 경계 표시")
            adv_label = c["label"] in SURF
            adv_jev = p["proceed_p"] >= 0.5
            if adv_label and not adv_jev and c["label"] != "HOLD":
                why.append("Jev 놓침(정답 진행인데 Noul<0.5)")
            if c["label"] == "DROP" and adv_jev:
                why.append("Jev 불필요 통과(정답 탈락인데 Noul≥0.5)")
            if 0.3 <= p["proceed_p"] <= 0.7:
                why.append("Jev 확률 경계(0.3~0.7)")
        if not why:
            continue
        h = hint(c)
        miss = any(w.startswith("Jev 놓침") for w in why)
        pr = 1 if (c["label"] in ("HOLD", "PASS_CHECK") or miss) else (2 if (("Claude 경계 표시" in why and len(why) > 1) or ("Jev 불필요 통과" in " ".join(why) and "자회사 사본" not in h)) else 3)
        if c["kind"] == "rule_exclude":
            pr = 3
        rows.append({
            "우선순위": pr, "검토사유": "; ".join(why), "구간": PERIOD_NAME[c["period"]], "날짜": c["day"], "종목코드": c["stock_code"],
            "회사": c["corp_name"], "공시명": c["report_nm"], "접수번호": c["rcept_no"],
            "DART 링크": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={c['rcept_no']}",
            "Claude 현재 라벨": c["label"], "Claude 라벨 근거": c["label_reason"], "Claude 경계표시": "Y" if c["was_borderline"] else "",
            "Jev Noul(진행 확률)": f"{p['proceed_p']:.2f}" if p else "", "Jev Choice": p["triage"] if p else "",
            "Jev 중요도(0~4)": f"{p['imp']:.1f}" if p else "", "Jev 설정": src, "힌트": h,
            "사람 판정(PASS/PASS_CHECK/HOLD/DROP)": "", "사람 메모": "",
        })
    rows.sort(key=lambda r: (r["우선순위"], r["날짜"], r["회사"]))
    os.makedirs(os.path.join(HERE, "review"), exist_ok=True)
    out = os.path.join(HERE, "review", "human_review_queue.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print(len(rows), "행 →", out, "| 우선순위", dict(sorted(Counter(r["우선순위"] for r in rows).items())))


if __name__ == "__main__":
    main()
