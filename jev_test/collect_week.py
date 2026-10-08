"""OpenDART 일주일치 전체 공시 수집 (Jev 분류 시험용 원본 데이터).

사용법 (레포 루트에서):
  python jev_test/collect_week.py 20260907 20260911
산출물: jev_test/data/raw_<YYYYMMDD>.json  (그날 전체 공시 list.json 행, 가공 없음)
휴장일은 0건으로 저장된다.
"""
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from dart_list_test import fetch_all  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def daterange(a, b):
    d = date(int(a[:4]), int(a[4:6]), int(a[6:]))
    e = date(int(b[:4]), int(b[4:6]), int(b[6:]))
    while d <= e:
        yield d
        d += timedelta(days=1)


def main():
    a, b = sys.argv[1], sys.argv[2]
    os.makedirs(OUT, exist_ok=True)
    for d in daterange(a, b):
        if d.weekday() >= 5:  # 주말 건너뜀
            continue
        day = d.strftime("%Y%m%d")
        path = os.path.join(OUT, f"raw_{day}.json")
        if os.path.exists(path):
            print(day, "이미 있음", len(json.load(open(path, encoding="utf-8"))), flush=True)
            continue
        rows = fetch_all(day, day)
        json.dump(rows, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        print(day, len(rows), flush=True)


if __name__ == "__main__":
    main()
