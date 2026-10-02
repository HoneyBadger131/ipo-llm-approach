"""공시명(report_nm) 기반 규칙 필터 (초안 — 검토 후 수정 전제).

classify(report_nm) 반환값
  "separate": 사업보고서처럼 중요하고 분량이 큰 공시 -> 별도 파이프라인에서 처리
  "exclude" : 중요도가 낮고 반복적/정형적인 공시 -> 본문을 받지 않고 제외
  "review"  : 그 외 -> 본문을 받아 판단 대상으로 삼음 (기본값, 보수적)
"""
import re

# 정기·대형 보고서 (별도 처리). exclude보다 먼저 검사한다.
SEPARATE_PATTERNS = [
    r"^사업보고서",
    r"^반기보고서",
    r"^분기보고서",
    r"^(연결)?감사보고서",
    r"^증권신고서\((지분증권|합병|분할|주식의포괄적교환ㆍ이전)",
    r"^투자설명서\((합병|분할)",
]

# 반복적/정형적이라 판단 가치가 낮은 공시 (제외)
EXCLUDE_PATTERNS = [
    r"^투자설명서",                        # 일괄신고 포함
    r"^일괄신고추가서류",                   # ELS/DLS/ETN 등 파생결합증권 발행
    r"^증권발행실적보고서",
    r"^기업설명회\(IR\)개최",
    r"^주식등의대량보유상황보고서",
    r"^임원ㆍ주요주주특정증권등소유상황보고서",
    r"^최대주주등소유주식변동신고서",
    r"^동일인등출자계열회사와의상품ㆍ용역거래",
    r"^신탁계약에의한취득상황보고서",
    r"^신탁계약해지결과보고서",
    r"^의결권대리행사권유참고서류",
    r"^주주총회소집공고",
    r"^(자기주식|자기주식취득|주식소각)?결과보고서",
]

_PREFIX = re.compile(r"^(\[[^\]]*\]\s*)+")  # [기재정정], [발행조건확정] 등 접두어


def normalize(report_nm):
    return _PREFIX.sub("", re.sub(r"\s+", " ", report_nm).strip())


def classify(report_nm):
    name = normalize(report_nm)
    if any(re.search(p, name) for p in SEPARATE_PATTERNS):
        return "separate"
    if any(re.search(p, name) for p in EXCLUDE_PATTERNS):
        return "exclude"
    return "review"
