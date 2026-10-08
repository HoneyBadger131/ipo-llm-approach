"""검증용 정답셋(cases_val.json) 생성 + 본문 확보. 새 판정은 만들지 않는다.

정답 = 기존 judgments.json 의 proceed (가 -> PASS, 부 -> DROP). PASS_CHECK/HOLD 라벨은 붙이지 않는다(label_source=claude_existing).
구간: 9/1~9/4(V2 시기 판정), 9/30~10/1.  본문은 trial_case/<날짜>/ 에 있으면 복사하고, 없는 것만 DART에서 내려받는다.

사용법 (레포 루트에서):  python jev_test/build_val_cases.py
"""
import json
import os
import shutil
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from dart_body import fetch_body_text  # noqa: E402

PERIODS = {"w0901": ["20260901", "20260902", "20260903", "20260904"], "w0930": ["20260930", "20261001"]}
DATA = os.path.join(ROOT, "jev_test", "data")


def main():
    cases = []
    for period, days in PERIODS.items():
        for d in days:
            for j in json.load(open(os.path.join(ROOT, "trial_case", d, "judgments.json"), encoding="utf-8")):
                cases.append(dict(rcept_no=j["rcept_no"], day=d, period=period, stock_code=j["stock_code"], corp_name=j["corp_name"],
                                  report_nm=" ".join(j["report_nm"].split()), is_correction=False, kind="judged",
                                  label="PASS" if j["proceed"] else "DROP", label_reason=j["reason"][:300],
                                  label_source="claude_existing", was_borderline=bool(j.get("borderline")), tag=j.get("tag")))
    json.dump(cases, open(os.path.join(ROOT, "jev_test", "cases", "cases_val.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(len(cases), "건 정답셋 저장", flush=True)
    copied = fetched = 0
    for c in cases:
        dst_dir = os.path.join(DATA, "bodies", c["day"])
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, f"{c['stock_code']}_{c['rcept_no']}.txt")
        if os.path.exists(dst):
            continue
        src = os.path.join(ROOT, "trial_case", c["day"], f"{c['stock_code']}_{c['rcept_no']}.txt")
        if os.path.exists(src):
            shutil.copy(src, dst)
            copied += 1
            continue
        try:
            open(dst, "w", encoding="utf-8").write(fetch_body_text(c["rcept_no"]))
        except Exception as e:
            open(dst, "w", encoding="utf-8").write("")
            print("ERR", c["rcept_no"], str(e)[:60], flush=True)
        fetched += 1
        if fetched % 10 == 0:
            print("fetched", fetched, flush=True)
    print(f"done: 복사 {copied}, 새로 받음 {fetched}", flush=True)


if __name__ == "__main__":
    main()
