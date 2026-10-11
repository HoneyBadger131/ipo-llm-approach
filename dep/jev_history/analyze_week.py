"""수집한 일주일치 공시를 단계별로 집계한다 (전체 -> 종목 리스트 -> 규칙 필터 -> 실제 판정).

사용법 (레포 루트에서):
  python jev_test/analyze_week.py 20260907 20260911 > jev_test/data/week_stats.md
"""
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from dart_rules import classify, normalize  # noqa: E402
from dart_watchlist_filings import load_watchlist  # noqa: E402

DATA = os.path.join(ROOT, "jev_test", "data")
CLS = {"Y": "유가증권(코스피)", "K": "코스닥", "N": "코넥스", "E": "기타(비상장 등)"}


def base_name(report_nm):
    """접두어([기재정정] 등)와 괄호 부분을 걷어낸 공시 대분류명."""
    n = normalize(report_nm).replace("영업(잠정)", "영업잠정")  # '영업(잠정)실적'이 괄호에서 잘리지 않게
    return re.sub(r"\(.*$", "", n).strip() or n


def load(a, b):
    rows = []
    for p in sorted(glob.glob(os.path.join(DATA, "raw_*.json"))):
        d = os.path.basename(p)[4:12]
        if a <= d <= b:
            for r in json.load(open(p, encoding="utf-8")):
                r["_day"] = d
                rows.append(r)
    return rows


def table(counter, total, head, n=25):
    print(f"| {head} | 건수 | 비중 |\n|---|---:|---:|")
    for k, v in counter.most_common(n):
        print(f"| {k} | {v} | {v / total * 100:.1f}% |")


def main():
    a, b = sys.argv[1], sys.argv[2]
    rows = load(a, b)
    watch = load_watchlist(os.path.join(ROOT, "kospi_list_clean.md"))
    days = sorted({r["_day"] for r in rows})

    print(f"# 주간 공시 집계 {a}~{b} (OpenDART list.json)\n")
    print("## 1. 일자별 규모 (전체 → 종목 리스트 290 → 규칙 필터)\n")
    print("| 일자 | 전체 | 리스트 종목 | 규칙 exclude | 규칙 separate | 규칙 review |\n|---|---:|---:|---:|---:|---:|")
    tot = Counter()
    for d in days:
        dr = [r for r in rows if r["_day"] == d]
        wr = [r for r in dr if r.get("stock_code") in watch]
        c = Counter(classify(r["report_nm"]) for r in wr)
        print(f"| {d} | {len(dr)} | {len(wr)} | {c['exclude']} | {c['separate']} | {c['review']} |")
        tot.update(all=len(dr), watch=len(wr), exclude=c["exclude"], separate=c["separate"], review=c["review"])
    print(f"| **합계** | **{tot['all']}** | **{tot['watch']}** | **{tot['exclude']}** | **{tot['separate']}** | **{tot['review']}** |\n")

    print("## 2. 전체 공시: 시장구분(corp_cls)\n")
    table(Counter(CLS.get(r.get("corp_cls"), r.get("corp_cls")) for r in rows), len(rows), "구분")

    print("\n## 3. 전체 공시: 공시 대분류명 상위 30 (정정 접두어·괄호 제거)\n")
    table(Counter(base_name(r["report_nm"]) for r in rows), len(rows), "대분류명", 30)

    wr_all = [r for r in rows if r.get("stock_code") in watch]
    print(f"\n## 4. 종목 리스트(코스피 290) 공시 {len(wr_all)}건: 정정 여부\n")
    corr = Counter("정정/추가(접두어)" if re.match(r"^\[(기재|첨부)(정정|추가)", r["report_nm"].strip()) else "신규" for r in wr_all)
    table(corr, len(wr_all), "구분")

    print("\n## 5. 종목 리스트 공시: 규칙 필터 결과별 대분류명\n")
    for k in ("exclude", "separate", "review"):
        sub = [r for r in wr_all if classify(r["report_nm"]) == k]
        print(f"\n### {k} ({len(sub)}건)\n")
        table(Counter(base_name(r["report_nm"]) for r in sub), len(sub), "대분류명", 40)

    # review 건의 실제 판정(judgments.json) 대조
    print("\n## 6. review 공시의 실제 판정(가/부) — judgments.json 대조\n")
    judged = []
    for d in days:
        p = os.path.join(ROOT, "trial_case", d, "judgments.json")
        if os.path.exists(p):
            judged += [dict(j, _day=d) for j in json.load(open(p, encoding="utf-8"))]
    ok = sum(j["proceed"] for j in judged)
    print(f"판정 {len(judged)}건 중 통과(가) {ok}건, 부 {len(judged) - ok}건\n")
    by = defaultdict(lambda: [0, 0])
    for j in judged:
        by[base_name(j["report_nm"])][0 if j["proceed"] else 1] += 1
    print("| 대분류명 | 가 | 부 | 통과율 |\n|---|---:|---:|---:|")
    for k, (g, n) in sorted(by.items(), key=lambda x: -(x[1][0] + x[1][1])):
        print(f"| {k} | {g} | {n} | {g / (g + n) * 100:.0f}% |")
    print("\n### 판정 태그·규칙 분포\n")
    print("태그:", dict(Counter(j.get("tag") for j in judged if j["proceed"])))
    print("근거 규칙(통과 건):", dict(Counter(r for j in judged if j["proceed"] for r in j.get("rules", []))))
    print("경계 사례(borderline):", sum(1 for j in judged if j.get("borderline")))

    print("\n## 7. 판정 '부' 사유 샘플 (대분류별)\n")
    for j in judged:
        if not j["proceed"]:
            print(f"- [{j['_day']}] {j['corp_name']} | {j['report_nm'].strip()} → {j['reason'][:110]}")
    print("\n## 8. 판정 '가' 목록\n")
    for j in judged:
        if j["proceed"]:
            print(f"- [{j['_day']}] {j['corp_name']} | {j['report_nm'].strip()} | {j.get('tag')} | 규칙{j.get('rules')}")


if __name__ == "__main__":
    main()
