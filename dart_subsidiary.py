"""자회사 공시 중복 처리.

모회사 공시 중 "(자회사의 주요경영사항)" 은 상장 자회사가 같은 날 낸 동일 공시의 사본이다.
원칙: 본회사(자회사) 공시로만 처리하고 모회사 쪽은 제외한다. 자회사가 비상장이 명확하면 모회사 공시를 처리한다.

find_listed_twin(): 같은 날 전체 공시(allrows)에서 제목이 같고 상장사(corp_cls Y/K/N)가 낸 쌍둥이 공시를 찾는다.
  - 쌍둥이를 찾으면 중복 -> 제외
  - 못 찾으면 "상장 공시 미확인": 자회사가 비상장이거나, 상장사인데 같은 날 공시를 내지 않은 경우다. 사람이 확인한다.
"""
import re

SUFFIX = re.compile(r"\s*\(자회사의주요경영사항\)\s*$")
LISTED = {"Y", "K", "N"}  # 유가증권·코스닥·코넥스


def _squash(s):
    return re.sub(r"\s+", "", s or "")


def is_sub_filing(report_nm):
    return bool(SUFFIX.search(_squash(report_nm)))


def base_title(report_nm):
    return SUFFIX.sub("", _squash(report_nm))


def sub_name(text):
    """본문에서 자회사 이름('자회사인 / X / 의 주요경영사항신고')."""
    m = re.search(r"자회사인\s*[/\n]*\s*(.+?)\s*[/\n]*\s*의\s*주요경영사항", text or "", re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def _big_numbers(text):
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]{6,}\d", text or "")}


def find_listed_twin(parent_row, parent_text, allrows, fetch_text):
    """parent_row: {rcept_no, stock_code, corp_name, report_nm}. fetch_text(rcept_no)->본문.
    반환: 쌍둥이 row(dict) 또는 None."""
    want = base_title(parent_row["report_nm"])
    mine = _big_numbers(parent_text)
    for r in allrows:
        if r["rcept_no"] == parent_row["rcept_no"] or r.get("corp_cls") not in LISTED:
            continue
        if not r.get("stock_code", "").strip() or r["stock_code"] == parent_row["stock_code"]:
            continue
        if _squash(r["report_nm"]) != want:
            continue
        try:
            other = fetch_text(r["rcept_no"])
        except Exception:
            continue
        if mine & _big_numbers(other):
            return r
    return None
