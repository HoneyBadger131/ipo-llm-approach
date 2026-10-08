"""시험 대상 공시의 본문을 내려받는다 (규칙 review 전부 + 정정 공시로 제외된 건).

사용법 (레포 루트에서):  python jev_test/fetch_bodies.py
산출물: jev_test/data/bodies/<YYYYMMDD>/<종목코드>_<접수번호>.txt  (git 제외, 재실행 시 있으면 건너뜀)
       jev_test/data/universe.json  (시험 대상 전체 목록: 접수번호, 분류, 규칙 필터 결과, 정정 여부)
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from dart_body import fetch_body_text  # noqa: E402
from dart_rules import classify, _CORRECTION  # noqa: E402
from dart_watchlist_filings import load_watchlist  # noqa: E402

DATA = os.path.join(ROOT, "jev_test", "data")


def main():
    watch = load_watchlist(os.path.join(ROOT, "kospi_list_clean.md"))
    uni = []
    for p in sorted(glob.glob(os.path.join(DATA, "raw_*.json"))):
        day = os.path.basename(p)[4:12]
        for r in json.load(open(p, encoding="utf-8")):
            if r.get("stock_code") not in watch:
                continue
            nm = re.sub(r"\s+", " ", r["report_nm"]).strip()
            uni.append(dict(day=day, rcept_no=r["rcept_no"], stock_code=r["stock_code"], corp_name=r["corp_name"],
                            report_nm=nm, rule=classify(nm), is_correction=bool(_CORRECTION.match(nm))))
    json.dump(uni, open(os.path.join(DATA, "universe.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    need = [u for u in uni if u["rule"] in ("review", "separate") or u["is_correction"]]
    print(f"universe {len(uni)} / 본문 필요 {len(need)}", flush=True)
    if os.environ.get("REVERSE"):  # 두 프로세스가 앞/뒤에서 나눠 받을 때
        need.reverse()
    for i, u in enumerate(need, 1):
        d = os.path.join(DATA, "bodies", u["day"])
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{u['stock_code']}_{u['rcept_no']}.txt")
        if os.path.exists(path):
            continue
        try:
            open(path, "w", encoding="utf-8").write(fetch_body_text(u["rcept_no"]))
        except Exception as e:  # 본문이 없는 공시(DART 014 등)는 빈 파일로 표시
            open(path, "w", encoding="utf-8").write("")
            print("ERR", u["rcept_no"], u["report_nm"][:30], str(e)[:60], flush=True)
        if i % 20 == 0:
            print(i, "/", len(need), flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
