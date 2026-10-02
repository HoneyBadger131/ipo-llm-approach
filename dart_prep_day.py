"""하루치 공시 준비 단계: 조회 -> 종목 리스트 필터 -> 규칙 분류 -> 본문 수집 -> 판단용 요약(digest) 출력.

사용법:
  export DART_API_KEY=발급키
  python dart_prep_day.py 20261001            # 조회·분류·본문 저장·digest 출력
  python dart_prep_day.py 20261001 --no-bodies   # 건수만 확인(본문 다운로드 생략)
  python dart_prep_day.py 20261001 --digest-only # 저장된 bodies/<YYYYMMDD>/ 로 digest만 다시 출력

산출물
  trial_case/<YYYYMMDD>/prep.json     : 단계별 건수, review/separate 목록(접수번호·종목·공시명)
  bodies/<YYYYMMDD>/<종목코드>_<접수번호>.txt : review/separate 공시의 text body (git 제외)
"""
import json
import os
import re
import sys
from collections import Counter

from dart_list_test import fetch_all
from dart_rules import classify, normalize
from dart_watchlist_filings import load_watchlist
from dart_body import fetch_body_text


def digest(text, cap=1500):
    """판단용 요약: 짧으면 전문, 길면 앞부분 + 금액·비율 등 핵심 줄."""
    t = re.sub(r"\n+", " / ", text)
    if len(t) <= cap:
        return t
    head = t[:800]
    keys = [x for x in re.split(r" / ", t[800:])
            if re.search(r"원|%|금액|비율|목적|상대|기간|사유|내용|계약", x) and len(x) < 140]
    return head + " ... " + " / ".join(keys)[:700]


def main():
    day = sys.argv[1]
    flags = set(sys.argv[2:])
    date = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    wl_path = "kospi_list_clean.md"
    out_dir = f"trial_case/{day}"
    body_dir = f"bodies/{day}"
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(body_dir, exist_ok=True)

    if "--digest-only" in flags:
        prep = json.load(open(f"{out_dir}/prep.json", encoding="utf-8"))
    else:
        watch = load_watchlist(wl_path)
        allrows = fetch_all(day, day)
        rows = [r for r in allrows if r.get("stock_code") in watch]
        cls = Counter(classify(r["report_nm"]) for r in rows)
        pick = lambda k: [dict(rcept_no=r["rcept_no"], stock_code=r["stock_code"], corp_name=r["corp_name"],
                               report_nm=r["report_nm"].strip()) for r in rows if classify(r["report_nm"]) == k]
        prep = dict(date=date, total=len(allrows), watchlist_filings=len(rows),
                    watchlist_companies=len({r["stock_code"] for r in rows}),
                    excluded=cls["exclude"], separate=pick("separate"), review=pick("review"))
        json.dump(prep, open(f"{out_dir}/prep.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{date} 전체 {prep['total']} / 리스트 종목 {prep['watchlist_filings']}건({prep['watchlist_companies']}개) "
              f"/ 규칙 제외 {prep['excluded']} / 별도 처리 {len(prep['separate'])} / 판단 대상 {len(prep['review'])}"
              f"({len({r['stock_code'] for r in prep['review']})}개 회사)", flush=True)

    if "--no-bodies" in flags:
        return
    for r in prep["review"] + prep["separate"]:
        path = f"{body_dir}/{r['stock_code']}_{r['rcept_no']}.txt"
        if not os.path.exists(path):
            try:
                open(path, "w", encoding="utf-8").write(fetch_body_text(r["rcept_no"]))
            except Exception as e:  # 개별 실패는 건너뛰고 표시
                print("ERR", r["rcept_no"], str(e)[:80])
                continue
    print("\n===== 판단 대상 digest =====")
    for r in sorted(prep["review"], key=lambda r: r["stock_code"]):
        path = f"{body_dir}/{r['stock_code']}_{r['rcept_no']}.txt"
        if os.path.exists(path):
            t = open(path, encoding="utf-8").read()
            print(f"\n#### {r['stock_code']} {r['corp_name']} | {r['report_nm']} | {r['rcept_no']} | {len(t)}자\n{digest(t)}")
    if prep["separate"]:
        print("\n===== 별도 처리 대상 =====")
        for r in prep["separate"]:
            print(r["stock_code"], r["corp_name"], r["report_nm"], r["rcept_no"])


if __name__ == "__main__":
    main()
