"""여러 종목의 특정일 공시를 분류하고, review 대상 본문을 trial_case/<날짜>/<종목코드>_<접수번호>.txt로 저장.

사용법: python dart_trial_case.py 20260910 329180 326030 003490 267270
"""
import os
import sys

from dart_list_test import fetch_all
from dart_rules import classify
from dart_body import fetch_body_text

day, stocks = sys.argv[1], sys.argv[2:]
out_dir = f"trial_case/{day}"
os.makedirs(out_dir, exist_ok=True)

allrows = fetch_all(day, day)
for stock in stocks:
    rows = [r for r in allrows if r.get("stock_code") == stock]
    print(f"\n## {stock} ({rows[0]['corp_name'] if rows else '-'}) {len(rows)}건")
    for r in rows:
        kind = classify(r["report_nm"])
        print(f"[{kind}] {r['rcept_no']} {r['report_nm'].strip()}")
        if kind == "review":
            text = fetch_body_text(r["rcept_no"])
            header = f"# {r['corp_name']}({stock}) | {r['rcept_dt']} | {r['report_nm'].strip()} | {r['rcept_no']}\n\n"
            open(f"{out_dir}/{stock}_{r['rcept_no']}.txt", "w", encoding="utf-8").write(header + text)
