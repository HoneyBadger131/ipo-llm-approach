"""날짜 단위 전 종목 이벤트 공시 스캔 — 종목별 조회 대신 하루치를 이벤트 유형만 서버에서 걸러 받는다(종목 확장 후보 방식).

  .venv/bin/python kind/scan_day.py 2026-04-10 [--market 1|2|''] [--universe kind/universe/kospi_list_clean.md]
유형 필터(서버): 수시공시 0127 영업양수도/분할/합병 · 0126 주식분할/병합 · 0131 주식소각 · 0145 증자/감자 · 0113 배당 · 0134 자기주식 · 0119 주식관련사채
                 시장조치 0303 권리락/배당락/기준가격 · 0321 신규/추가/변경/재상장 · 0311 매매거래정지 · 0328 상장폐지
출력: 후보 공시(회사명·제목·접수번호) + 유니버스(회사명 기준) 해당 여부. 호출 수·시간을 함께 출력.
"""
import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kind_client as kc

TYPES = {"01": ["0127", "0126", "0131", "0145", "0113", "0134", "0119"], "02": ["0303", "0321", "0311", "0328"]}
EVENT_RE = re.compile(r"합병|분할|주식배당|무상증자|유상증자|감자|소각|권리락|권배락|배당락|기준가격|추가상장|변경상장|재상장|신규상장|상장안내|상장폐지|매매거래정지|전환사채|신주인수권부사채|자기주식")
SKIP_RE = re.compile(r"종속회사|주식선물|선물ㆍ옵션|선물·옵션")


def norm(n):
    return re.sub(r"\s|\(주\)|㈜|주식회사|\(.*?\)", "", n or "").lower()


def load_universe(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\|\s*\d+\s*\|\s*`(\w{6})`\s*\|\s*(.+?)\s*\|", line)
        if m:
            out[norm(m.group(2))] = m.group(1)
    return out


ETF_RE = re.compile(r"증권상장지수투자신탁|상장지수|ETF|ETN|수익증권")


def code_of(name):
    """KIND 회사명 → 단축코드 (종목명 자동완성, 결과는 kind_client 캐시). 같은 이름이 없으면 None."""
    for x in kc.resolve_name(name):
        if x.get("secugrpId") == "ST" and x.get("comabbrv") == name:
            return x["repisusrtcd"][1:]
    return None


def scan(day, market="1"):
    rows = []
    for mj, codes in TYPES.items():
        v = "|".join(codes) + "|"
        extra = {f"disclosureType{mj}": v, f"pDisclosureType{mj}": v}
        if market is not None:
            extra["marketType"] = market
        rows += [{**r, "major": mj} for r in kc.list_filings(frm=day, to=day, **extra)]
    seen, out = set(), []
    for r in rows:
        if r["acpt_no"] in seen:
            continue
        seen.add(r["acpt_no"])
        out.append(r)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("day")
    ap.add_argument("--market", default="1")
    ap.add_argument("--universe", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "universe", "kospi_list_clean.md"))
    a = ap.parse_args()
    uni_codes = set(load_universe(a.universe).values())
    t0 = time.time()
    rows = scan(a.day, a.market if a.market != "all" else None)
    ev = [r for r in rows if EVENT_RE.search(r["title"]) and not SKIP_RE.search(r["title"]) and not ETF_RE.search(r["title"])]
    names = sorted({r["company"] for r in ev})
    codes = {}
    for n in names:
        codes[n] = code_of(n)
        time.sleep(0.4)
    hits = [r for r in ev if codes.get(r["company"]) in uni_codes]
    print(f"{a.day} market={a.market!r}: 서버 필터 후 {len(rows)}건 → 이벤트(ETF 제외) {len(ev)}건 → 유니버스 {len(hits)}건 ({time.time() - t0:.1f}s, 회사 {len(names)}곳 코드 해석)")
    for r in sorted(ev, key=lambda r: r["company"]):
        c = codes.get(r["company"])
        print(f"  {'U' if c in uni_codes else '-'} {r['company']:<16} {(c or '?'):<7} {r['title'][:44]:<46} {r['acpt_no']}")
