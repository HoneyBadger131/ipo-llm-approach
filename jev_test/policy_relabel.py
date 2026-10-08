"""정책 계층 라벨 생성: 사람이 명시하지 않은 건에 rules_core.hard_rule(운영과 같은 규칙)을 적용한다.

사용법: python jev_test/policy_relabel.py   ->  cases/labels_policy.json
우선순위: Claude 기본 < 정책(이 파일) < 사람 명시 판정(labels_human.json). 사람이 기본값 그대로 둔 행은 확정으로 보지 않으므로 정책이 이긴다.
MANUAL: 하드 규칙으로 만들 수 없는(본문 키워드가 신뢰되지 않는) 정책 적용 사례를 사람이 본문을 읽고 확정한 목록.
"""
import glob
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import read_body  # noqa: E402
from rules_core import hard_rule  # noqa: E402

# Q2: 기존 약정의 연장·대환은 DROP (본문 '연장' 키워드는 신규 건에도 나와 하드 규칙으로 쓰지 않는다). (회사, 공시명 일부) -> 라벨
MANUAL = {
    ("CJ CGV", "타인에대한채무보증결정"): ("DROP", "Q2-연장", "기존 보증 연장"),
    ("삼성SDI", "금전대여결정"): ("DROP", "Q2-연장", "기존 대여 한도 종료일 연장"),
}


def main():
    base = []
    for p in sorted(glob.glob(os.path.join(HERE, "cases", "cases_*.json"))):
        base += json.load(open(p, encoding="utf-8"))
    human = json.load(open(os.path.join(HERE, "cases", "labels_human.json"), encoding="utf-8"))
    default = json.load(open(os.path.join(HERE, "cases", "labels_human_default.json"), encoding="utf-8"))
    out = {}
    for c in base:
        if c["rcept_no"] in human or c["kind"] == "rule_exclude" or c.get("label_source") == "claude_blind_v3":   # 블라인드 검증 라벨은 건드리지 않는다
            continue
        res = hard_rule(c, read_body(c))
        if res is None:
            for (corp, kw), v in MANUAL.items():
                if c["corp_name"] == corp and kw in c["report_nm"] and not c["is_correction"]:
                    res = v
        if res and res[0] != c["label"]:
            out[c["rcept_no"]] = dict(label=res[0], was=c["label"], rule=res[1], why=res[2], company=c["corp_name"], title=c["report_nm"],
                                      overrides_default_row=c["rcept_no"] in default)
    json.dump(out, open(os.path.join(HERE, "cases", "labels_policy.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"정책(하드 규칙)으로 라벨이 바뀐 건 {len(out)} (사람 명시 {len(human)}건·규칙 제외 유형은 대상 아님)")
    print("규칙별:", dict(Counter(v["rule"] for v in out.values())))
    print("전환:", dict(Counter(f"{v['was']}→{v['label']}" for v in out.values()).most_common()))
    print("기본값 그대로 둔 행(사람 미확정)과 충돌해 정책이 이긴 건:", sum(v["overrides_default_row"] for v in out.values()))


if __name__ == "__main__":
    main()
