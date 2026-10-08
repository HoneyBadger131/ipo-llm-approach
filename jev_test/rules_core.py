"""공시 판단 하드 규칙 (결정적). 제목·본문 숫자만으로 확실히 정해지는 유형을 Jev 이전에 라벨로 확정한다.

정답(라벨) 생성(policy_relabel.py)과 운영(triage.py)이 같은 규칙을 쓴다 — 규칙의 단일 출처.
근거: 공시판단_기본원칙.md §10 (사용자 정책 답변 2026-10-08) 와 docs/DISCLOSURE_TRIAGE.md.

hard_rule(case, body) -> (label, rule_id, why) | None      None 이면 Jev가 판단한다.
  case: dict(report_nm, corp_name, stock_code, is_correction)   body: 공시 본문 텍스트(없으면 "")

규칙 (위에서부터 첫 일치):
  R-CORR-*      정정: 정형 서류 정정 DROP / 계약 해지 PASS_CHECK / 증감 ≥200억 원 & ≥1% PASS_CHECK / 그 외 DROP
  R-UNFAITHFUL  불성실공시법인 지정 → PASS
  R-ACCIDENT    중대재해 → PASS_CHECK
  R-CEO         대표이사 변경(안내공시) → NOTIFY
  R-RUMOR       풍문 해명·조회공시: 시총 상위 30 또는 분쟁 리스트 → PASS_CHECK, 그 외 → DROP
  R-MERGER-PROC 소규모(100% 자회사) 합병·합병 종료 보고·사채권자집회 소집 → DROP
  R-LOCKUP      보호예수 해제 → PASS_CHECK
  R-REIT        리츠의 사채·단기사채 차입(차환 등) → DROP (사용자: 리츠는 정말 중요한 것이 아니면 무시)
  R-TRUST       자기주식 신탁계약 해지 → 1,000억 원 이상 PASS_CHECK, 그 외 DROP
  R-FIN         금융회사의 보증·대여·수익증권·차입 등 일상 거래 → 1,000억 원 이상 PASS_CHECK, 그 외 DROP
임계값(가정, 사용자 승인 2026-10-08): BIG_WON=1,000억 원, CORR_WON=200억 원, CORR_PCT=1%, LARGE_CAP_N=30
"""
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dart_rules import normalize  # noqa: E402

BIG_WON = 1000 * 10**8      # "금액이 매우 크다" (Q1, 승인)
CORR_WON = 200 * 10**8      # 정정 "큰 규모" (Q6, 승인)
CORR_PCT = 1.0
LARGE_CAP_N = 30            # 시총 상위 N (N4, kospi_list_clean.md 의 순번 = 시총 순위)

_FIN_NAME = re.compile(r"증권|은행|금융|보험|생명|화재|캐피탈|카드|자산운용|손해")
_FIN_TYPE = re.compile(r"수익증권|자금대여|금전대여|채무보증|담보제공|기타유가증권|자금차입|유가증권매수")   # 출자·인수는 일상 영업이 아님(Q2 보정)
_STRUCT = re.compile(r"증권신고서|증권발행실적|기업설명회|반기보고서|사업보고서|분기보고서")
_NUM = re.compile(r"(?<![\d,])(\d{1,3}(?:,\d{3}){2,})(?![\d,])")

_RANK = None
_DISPUTE = None


def cap_rank(stock_code):
    """종목 리스트(kospi_list_clean.md)의 순번(시총 순위). 없으면 None."""
    global _RANK
    if _RANK is None:
        _RANK = {}
        p = os.path.join(ROOT, "kospi_list_clean.md")
        for line in open(p, encoding="utf-8"):
            m = re.match(r"\|\s*(\d+)\s*\|\s*`(\w{6})`", line)
            if m:
                _RANK[m.group(2)] = int(m.group(1))
    return _RANK.get(stock_code)


def is_large_cap(stock_code):
    r = cap_rank(stock_code)
    return r is not None and r <= LARGE_CAP_N


def dispute_names():
    global _DISPUTE
    if _DISPUTE is None:
        p = os.path.join(ROOT, "watchlists", "dispute_watchlist.json")
        _DISPUTE = {c["name"] for c in json.load(open(p, encoding="utf-8"))["companies"]} if os.path.exists(p) else set()
    return _DISPUTE


def max_won(text):
    """본문에서 '원'·'금액' 문맥의 가장 큰 원 단위 금액(1억 원 이상). 없으면 0."""
    best = 0
    for m in _NUM.finditer(text):
        v = int(m.group(1).replace(",", ""))
        if v >= 10**8 and re.search(r"원|금액|액", text[max(0, m.start() - 40):m.start()]) and v > best:
            best = v
    return best


def correction_amount_delta(body):
    """정정 표의 정정 전·후 숫자 쌍에서 (원 단위 최대 증감액, 그때의 증감률%)."""
    from lib import _PAIR, correction_section
    sec = correction_section(body)
    i = sec.find("정정후")
    best = (0, 0.0)
    for m in _PAIR.finditer(sec[i:] if i >= 0 else sec):
        a, b = (float(m.group(k).replace(",", "")) for k in (2, 3))
        if max(abs(a), abs(b)) < 1e8 or a == 0:
            continue
        if abs(b - a) > best[0]:
            best = (abs(b - a), (b - a) / abs(a) * 100)
    return best


def _name(report_nm):
    return re.sub(r"\(.*$", "", normalize(report_nm)).strip()


def hard_rule(case, body=""):
    t, corp, code = case["report_nm"], case["corp_name"], case["stock_code"]
    name = _name(t)
    full = normalize(t)                     # 괄호 안 유형명(예: 주요사항보고서(회사합병결정))까지 보는 전체 제목
    if case.get("is_correction"):
        if _STRUCT.search(t):
            return "DROP", "R-CORR-FORM", "정형 서류 정정"
        if "계약" in t and re.search(r"계약\s*(해지|해제)", body[:1500]):
            return "PASS_CHECK", "R-CORR-TERMINATED", "계약 해지 정정"
        d, pct = correction_amount_delta(body)
        if d >= CORR_WON and abs(pct) >= CORR_PCT:
            return "PASS_CHECK", "R-CORR-BIG", f"금액 변동 {d / 1e8:,.0f}억 원({pct:+.1f}%)"
        return "DROP", "R-CORR-SMALL", f"금액 변동 {d / 1e8:,.0f}억 원 — 큰 규모 아님 또는 기간·일정·명칭 정정"
    if name == "불성실공시법인지정":
        return "PASS", "R-UNFAITHFUL", "불성실공시법인 지정"
    if name == "중대재해발생":
        return "PASS_CHECK", "R-ACCIDENT", "중대재해는 중요도 확인"
    if re.match(r"대표이사.*변경", normalize(t)):   # 제목에 괄호가 있어(대표집행임원) 전체 제목으로 본다
        return "NOTIFY", "R-CEO", "대표이사 변경은 알림만"
    if re.match(r"(풍문또는보도에대한해명|조회공시요구)", name):
        if is_large_cap(code) or corp in dispute_names():
            return "PASS_CHECK", "R-RUMOR", "시총 상위 30·분쟁 리스트: 풍문 해명도 민감하게"
        return "DROP", "R-RUMOR", "풍문·조회공시 답변은 무시"
    if name in ("합병등종료보고서", "사채권자집회소집") or ("회사합병결정" in full and "소규모합병" in body):
        return "DROP", "R-MERGER-PROC", "소규모(100% 자회사) 합병·종료·사채권자집회 등 절차성 합병 공시"
    if "보호예수" in t + body[:600] and name.startswith("기타안내사항"):
        return "PASS_CHECK", "R-LOCKUP", "보호예수 해제는 중요(규모 확인)"
    if corp.endswith("리츠") and "자금차입" in full:
        return "DROP", "R-REIT", "리츠의 정례 차입·차환"
    if "자기주식취득신탁계약해지" in full:
        return ("PASS_CHECK", "R-TRUST", "대규모 신탁 해지") if max_won(body) >= BIG_WON else ("DROP", "R-TRUST", "단순 신탁 해지")
    if _FIN_NAME.search(corp) and _FIN_TYPE.search(full):
        return ("PASS_CHECK", "R-FIN", "금융회사 거래지만 금액이 매우 큼") if max_won(body) >= BIG_WON else ("DROP", "R-FIN", "금융회사의 일상 영업 거래")
    return None
