"""HD현대중공업(329180) 20260910 공시: 규칙 분류 -> 판단 대상 본문 추출 -> bodies/ 저장."""
import os
import sys

from dart_list_test import fetch_all
from dart_rules import classify
from dart_body import fetch_body_text

day = sys.argv[1] if len(sys.argv) > 1 else "20260910"
stock = sys.argv[2] if len(sys.argv) > 2 else "329180"

rows = [r for r in fetch_all(day, day) if r.get("stock_code") == stock]
os.makedirs("bodies", exist_ok=True)
for r in rows:
    kind = classify(r["report_nm"])
    print(f"[{kind}] {r['rcept_no']} {r['report_nm'].strip()}")
    if kind != "review":
        continue
    text = fetch_body_text(r["rcept_no"])
    path = f"bodies/{r['rcept_no']}.txt"
    open(path, "w", encoding="utf-8").write(text)
    print(f"  -> {path} ({len(text)}자)")
