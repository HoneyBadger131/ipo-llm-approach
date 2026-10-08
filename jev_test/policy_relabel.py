"""정책 답변(Q1~Q12, 2026-10-08)을 정답 라벨에 옮긴 '정책 계층'을 만든다. 우선순위: Claude 기본 < 정책 < 사람 명시 판정.

사용법: python jev_test/policy_relabel.py   ->  cases/labels_policy.json, 변경 요약 출력
적용 규칙 (결정적, 공시명·기존 판정 사유·정정 표의 숫자만 사용):
  Q3  풍문 해명·조회공시 답변 → DROP
  Q4  보호예수 해제 → PASS_CHECK(사람 명시 2건과 동일)
  Q8  중대재해 → PASS_CHECK, 불성실공시법인 지정 → PASS
  Q2  보증·대여·출자의 연장·대환·차환 → DROP, 금융회사(증권·은행·보험·카드·캐피탈)의 보증·대여·수익증권·차입 등 일상 거래 → DROP
  Q6  정정 → 증감액 ≥ 200억 원이고 증감률 ≥ 1% 이거나 계약 해지일 때만 PASS_CHECK, 그 외 DROP
      (200억은 사람 라벨 DL이앤씨 +352억·현대건설 +389억 = PASS_CHECK, HJ중공업 +104억·IPARK +47억 = DROP 사이의 잠정값)
사람이 명시한 행(labels_human.json)은 건드리지 않는다.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import _PAIR, correction_section, read_body  # noqa: E402

WON_THRESHOLD = 200 * 10**8   # 잠정(가정): 정정 '큰 규모' 기준
FIN = re.compile(r"증권|은행|금융|보험|생명|화재|캐피탈|카드|자산운용|손해")
FIN_TYPE = re.compile(r"수익증권|자금대여|금전대여|채무보증|담보제공|기타유가증권|자금차입|유가증권매수")   # 출자·타법인 취득(M&A)은 일상 영업이 아니므로 제외
EXT = re.compile(r"연장|대환|차환|만기")
STRUCT = re.compile(r"증권신고서|증권발행실적|기업설명회|반기보고서|사업보고서|분기보고서")


def base_name(n):
    return re.sub(r"\(.*$", "", re.sub(r"^(\[[^\]]*\]\s*)+", "", n)).strip()


def correction_amount_delta(case):
    """정정 전·후 숫자 쌍에서 원 단위 최대 증감액과 그때의 증감률(%)을 구한다."""
    sec = correction_section(read_body(case))
    i = sec.find("정정후")
    best = (0, 0.0)
    for m in _PAIR.finditer(sec[i:] if i >= 0 else sec):
        a, b = (float(m.group(k).replace(",", "")) for k in (2, 3))
        if max(abs(a), abs(b)) < 1e8 or a == 0:
            continue
        if abs(b - a) > best[0]:
            best = (abs(b - a), (b - a) / abs(a) * 100)
    return best


def policy_label(c):
    t, r, name = c["report_nm"], c["label_reason"], base_name(c["report_nm"])
    if c["is_correction"]:
        if STRUCT.search(t):
            return "DROP", "Q6", "정형 서류 정정"
        if re.search(r"해지|해제", read_body(c)[:1200]) and "계약" in t:
            return "PASS_CHECK", "Q6", "계약 해지 정정"
        d, pct = correction_amount_delta(c)
        if d >= WON_THRESHOLD and abs(pct) >= 1:
            return "PASS_CHECK", "Q6", f"금액 변동 {d / 1e8:,.0f}억 원({pct:+.1f}%)"
        return "DROP", "Q6", f"금액 변동 {d / 1e8:,.0f}억 원 — 큰 규모 아님 또는 기간·일정·명칭 정정"
    if re.match(r"(풍문또는보도에대한해명|조회공시요구)", name):
        return "DROP", "Q3", "풍문 해명·조회공시 답변은 무시"
    if "보호예수" in t + r:
        return "PASS_CHECK", "Q4", "보호예수 해제는 중요 공시(규모 확인)"
    if name == "중대재해발생":
        return "PASS_CHECK", "Q8", "중대재해는 중요도 판단을 위해 통과·확인"
    if name == "불성실공시법인지정":
        return "PASS", "Q8", "불성실공시법인 지정은 통과"
    if re.match(r"(타인에대한채무보증결정|금전대여결정|특수관계인에대한자금대여|부동산투자회사자금차입)", name) and EXT.search(r):
        return "DROP", "Q2", "연장·대환·차환은 무시"
    if FIN.search(c["corp_name"]) and FIN_TYPE.search(name):
        return "DROP", "Q2", "금융회사의 일상 영업 거래"
    return c["label"], None, ""


def main():
    import glob
    base = []
    for p in sorted(glob.glob(os.path.join(HERE, "cases", "cases_*.json"))):
        base += json.load(open(p, encoding="utf-8"))
    human = json.load(open(os.path.join(HERE, "cases", "labels_human.json"), encoding="utf-8"))
    default = json.load(open(os.path.join(HERE, "cases", "labels_human_default.json"), encoding="utf-8"))
    out, skipped = {}, 0
    for c in base:
        if c["rcept_no"] in human or c["kind"] == "rule_exclude":
            skipped += 1
            continue
        lab, rule, why = policy_label(c)
        if rule and lab != c["label"]:
            out[c["rcept_no"]] = dict(label=lab, was=c["label"], rule=rule, why=why, company=c["corp_name"], title=c["report_nm"],
                                      overrides_default_row=c["rcept_no"] in default)
    json.dump(out, open(os.path.join(HERE, "cases", "labels_policy.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    print(f"정책으로 라벨이 바뀐 건 {len(out)} (사람 명시 {len(human)}건·규칙 제외 유형은 대상 아님)")
    print("규칙별:", dict(Counter(v["rule"] for v in out.values())))
    print("전환:", dict(Counter(f"{v['was']}→{v['label']}" for v in out.values()).most_common()))
    print("기본값 그대로 둔 행(사람 미확정)과 충돌해 정책이 이긴 건:", sum(v["overrides_default_row"] for v in out.values()))


if __name__ == "__main__":
    main()
