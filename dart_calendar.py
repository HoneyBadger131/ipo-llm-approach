"""보고서 캘린더 — 영업일과 '공백 구간(window)' 계산.

규칙: 보고서의 기준일 B = 영업일. B의 구간 = (직전 영업일 다음 날 ~ B) 달력일 전부.
  예) 10/2(금) 다음 보고서 B=10/6(화): 구간 10/3~10/6 (토·일·대체공휴일 10/5 포함) → 휴일에 올라온 공시도 빠지지 않는다.
  보고서는 B 다음 영업일 새벽에 전일(B) 데이터로 생성한다고 가정.

사용법
  python dart_calendar.py                       # 9/1~오늘 캘린더와 trial_case 산출물 대조(연속성 점검)
  python dart_calendar.py window 20261006       # 한 기준일의 구간 출력
HOLIDAYS: 2026년 KRX 휴장일(주말 제외). 2027년 이후는 연초에 추가한다. 데이터로 교차 확인: 휴장일은 DART 전체 공시가 0건.
"""
import datetime as dt
import json
import os
import sys

HOLIDAYS = {dt.date.fromisoformat(d) for d in (
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-02", "2026-05-01", "2026-05-05", "2026-05-25",
    "2026-06-03", "2026-07-17", "2026-08-17", "2026-09-24", "2026-09-25", "2026-09-26", "2026-10-05", "2026-10-09", "2026-12-25", "2026-12-31")}


def is_business(d):
    return d.weekday() < 5 and d not in HOLIDAYS


def prev_business(d):
    d -= dt.timedelta(days=1)
    while not is_business(d):
        d -= dt.timedelta(days=1)
    return d


def window(day):
    """기준일 B(YYYYMMDD 문자열 또는 date) → (bgn, end) date. 영업일이 아니면 ValueError."""
    b = day if isinstance(day, dt.date) else dt.datetime.strptime(day, "%Y%m%d").date()
    if not is_business(b):
        raise ValueError(f"{b} 는 영업일이 아니다(휴장일)")
    return prev_business(b) + dt.timedelta(days=1), b


def business_days(a, b):
    d = a
    while d <= b:
        if is_business(d):
            yield d
        d += dt.timedelta(days=1)


def check(start=dt.date(2026, 9, 1), end=None):
    """영업일마다 trial_case/<날짜>/prep.json 존재 여부와 구간 연속성을 점검한다."""
    root = os.path.dirname(os.path.abspath(__file__))
    end = end or dt.date.today()
    rows, prev_end = [], None
    for b in business_days(start, end):
        bgn, e = window(b)
        p = os.path.join(root, "trial_case", b.strftime("%Y%m%d"), "prep.json")
        tot = json.load(open(p, encoding="utf-8")).get("total") if os.path.exists(p) else None
        contiguous = prev_end is None or bgn == prev_end + dt.timedelta(days=1)
        rows.append((b, bgn, tot, contiguous))
        prev_end = e
    return rows


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "window":
        a, b = window(sys.argv[2])
        print(a, b)
    else:
        for b, bgn, tot, ok in check():
            span = f"{bgn:%m/%d}~{b:%m/%d}" if bgn != b else f"{b:%m/%d}"
            print(f"{b} {b:%a} 구간 {span:11s} prep {'없음' if tot is None else str(tot) + '건'}{'' if ok else '  ⚠구간 불연속'}")
