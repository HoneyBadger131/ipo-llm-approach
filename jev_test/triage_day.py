"""일 단위 공시 분류 실행기 — dart_prep_day.py 산출물(prep.json, bodies/<날짜>/)을 읽어 하이브리드(하드 규칙 → Jev v3)로 라벨을 붙인다.

사용법 (레포 루트에서, TYPE_SAFE_AI_KEY 필요):
  python dart_prep_day.py 20261002                  # 1) 조회·규칙 필터·본문·자회사 중복 제거 (기존 단계)
  python jev_test/triage_day.py 20261002            # 2) 이 단계: 라벨 5종 부여 -> trial_case/20261002/triage.json
  python jev_test/triage_day.py 20261002 --write-judgments   # judgments.json 도 기존 스키마로 저장(없을 때만; 사람이 쓴 판정은 덮어쓰지 않는다)

산출물 triage.json: [{rcept_no, stock_code, corp_name, report_nm, label, proceed, source(rule|jev), rule, reason, noul, choice, tier}]
  label  PASS·PASS_CHECK·HOLD → 심화 분석(HOLD는 검수 표시) / NOTIFY → 브리프에 한 줄 알림만 / DROP → 종료
judgments.json 호환: proceed = 분석 진행 여부, tag = 제목 기반 추정(사업 변동|기타 사항), rules = [규칙/라벨], borderline = HOLD·PASS_CHECK
"""
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
from lib import read_body  # noqa: E402
from triage import triage_case  # noqa: E402

BUSINESS = re.compile(r"계약|합병|분할|출자|시설투자|취득|처분|임상|투자판단|매각|양수|양도|생산")


def main():
    day = sys.argv[1]
    key = os.environ.get("TYPE_SAFE_AI_KEY")
    out_dir = os.path.join(ROOT, "trial_case", day)
    prep = json.load(open(os.path.join(out_dir, "prep.json"), encoding="utf-8"))
    cases = [dict(day=day, rcept_no=r["rcept_no"], stock_code=r["stock_code"], corp_name=r["corp_name"], report_nm=r["report_nm"],
                  is_correction=False) for r in prep["review"]]

    def one(c):
        return {**{k: c[k] for k in ("rcept_no", "stock_code", "corp_name", "report_nm")}, **triage_case(c, read_body(c), key)}
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(one, cases))
    json.dump(res, open(os.path.join(out_dir, "triage.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    print(day, f"판단 대상 {len(res)}건", dict(Counter(r["label"] for r in res)), "| 규칙 확정", sum(r["source"] == "rule" for r in res))
    if "--write-judgments" in sys.argv:
        jp = os.path.join(out_dir, "judgments.json")
        if os.path.exists(jp):
            print("judgments.json 이 이미 있어 덮어쓰지 않았다:", jp)
            return
        js = [dict(rcept_no=r["rcept_no"], stock_code=r["stock_code"], corp_name=r["corp_name"], report_nm=r["report_nm"], proceed=r["proceed"],
                   tag="사업 변동" if BUSINESS.search(r["report_nm"]) else "기타 사항", rules=[r["rule"], r["label"]],
                   reason=r["reason"], borderline=r["label"] in ("HOLD", "PASS_CHECK")) for r in res]
        json.dump(js, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("judgments.json 저장:", jp)


if __name__ == "__main__":
    main()
