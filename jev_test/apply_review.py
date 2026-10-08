"""사람이 채운 검토 CSV를 정답셋에 반영한다.

사용법: python jev_test/apply_review.py <채워진.csv>
  - '사람 판정' 열이 PASS / PASS_CHECK / HOLD / DROP 중 하나인 행만 반영 (빈칸·그 외 값은 무시하고 알려 준다)
  - cases/labels_human.json 에 저장 → lib.load_cases() 가 label을 덮어쓰고 label_source='human' 으로 표시
  - 이후 python jev_test/score_run.py <실험명> / compare_runs.py / validate_report.py 를 다시 돌리면 사람 라벨로 재채점된다
"""
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VALID = {"PASS", "PASS_CHECK", "HOLD", "DROP"}


def main():
    src = sys.argv[1]
    out_path = os.path.join(HERE, "cases", "labels_human.json")
    cur = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {}
    n = skipped = 0
    for r in csv.DictReader(open(src, encoding="utf-8-sig")):
        v = (r.get("사람 판정(PASS/PASS_CHECK/HOLD/DROP)") or "").strip().upper().replace("-", "_")
        if not v:
            continue
        if v not in VALID:
            skipped += 1
            print("무시(허용 값 아님):", r["접수번호"], r["회사"], repr(v))
            continue
        cur[r["접수번호"].strip()] = {"label": v, "memo": (r.get("사람 메모") or "").strip()}
        n += 1
    json.dump(cur, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"반영 {n}건, 무시 {skipped}건, 누적 사람 라벨 {len(cur)}건 → {out_path}")


if __name__ == "__main__":
    main()
