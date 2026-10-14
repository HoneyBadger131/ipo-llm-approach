"""자회사 공시 중복 처리.

모회사 공시 중 "(자회사의 주요경영사항)" 은 상장 자회사가 같은 날 낸 동일 공시의 사본이다.
원칙: 본회사(자회사) 공시로만 처리하고 모회사 쪽은 제외한다. 자회사가 비상장이 명확하면 모회사 공시를 처리한다.

find_listed_twin(): 같은 날 전체 공시(allrows)에서 제목이 같고 상장사(corp_cls Y/K/N)가 낸 쌍둥이 공시를 찾는다.
  - 쌍둥이를 찾으면 중복 -> 제외
  - 못 찾으면 "상장 공시 미확인": 자회사가 비상장이거나, 상장사인데 같은 날 공시를 내지 않은 경우다. 사람이 확인한다.
"""
import re

SUFFIX = re.compile(r"\s*\((자|종속)회사의주요경영사항\)\s*$")
LISTED = {"Y", "K", "N"}  # 유가증권·코스닥·코넥스


def _squash(s):
    return re.sub(r"\s+", "", s or "")


def is_sub_filing(report_nm):
    return bool(SUFFIX.search(_squash(report_nm)))


def base_title(report_nm):
    return SUFFIX.sub("", _squash(report_nm))


def sub_name(text):
    """본문에서 자회사 이름('자회사인 / X / 의 주요경영사항신고')."""
    m = re.search(r"(?:자|종속)회사인\s*[/\n]*\s*(.+?)\s*[/\n]*\s*의\s*주요경영사항", text or "", re.S)
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


# ---- 자본으로 인정되는 채무증권 발행결정 ↔ 전환사채·신주인수권부사채·교환사채 발행결정 중복 -------------------------------------------
# 영구채 CB/BW 는 같은 사채를 두 번 신고한다: '○○권 발행결정'(6.4) 과 '자본으로인정되는채무증권발행결정'(6.2). 내용(회차·종류·권면총액)이 같다.
# 같은 회사·같은 날의 쌍을 찾아 자본인정 쪽을 빼고 CB/BW 쪽 1건만 남긴다. 짝이 없는 자본인정 공시(순수 신종자본증권 등)는 그대로 둔다.
CAPITAL_NM = "자본으로인정되는채무증권발행결정"
CBBW_NM = re.compile(r"(전환사채권|신주인수권부사채권?|교환사채권)발행결정")
_KEY = re.compile(r"사채의\s*종류\s*회차\s*(\S+)\s*종류\s*(.+?)\s*2\.\s*사채의\s*권면\(전자등록\)총액\s*\(원\)\s*([\d,]+)", re.S)


def _bond_key(text):
    m = _KEY.search(re.sub(r"\s+", " ", text or ""))
    return (m.group(1), re.sub(r"\s+", "", m.group(2)), m.group(3).replace(",", "")) if m else None


def drop_capital_twins(rows, read_text):
    """rows: prep['review'] 의 row 목록, read_text(row)->본문(없으면 ''). 반환 (남길 목록, [제외 row + twin_rcept_no]).
    짝 판정: 같은 stock_code, 한쪽은 자본으로인정되는채무증권발행결정, 다른 쪽은 CB/BW/EB 발행결정이고 (회차, 사채 종류, 권면총액)이 같다. 본문을 못 읽으면 짝짓지 않는다."""
    cbbw = {}
    for r in rows:
        if CBBW_NM.search(_squash(r["report_nm"])):
            k = _bond_key(read_text(r))
            if k:
                cbbw.setdefault((r["stock_code"], k), r)
    keep, dup = [], []
    for r in rows:
        if CAPITAL_NM in _squash(r["report_nm"]):
            k = _bond_key(read_text(r))
            tw = cbbw.get((r["stock_code"], k)) if k else None
            if tw:
                dup.append(dict(r, twin_rcept_no=tw["rcept_no"], twin_report_nm=tw["report_nm"]))
                continue
        keep.append(r)
    return keep, dup
