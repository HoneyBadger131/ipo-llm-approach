"""본문을 읽고 거르는 하드 규칙(2026-10-23 사용자 결정). dart_prep_day 가 본문 수집 직후, 자회사 중복 제거와 같은 자리에서 실행한다.

  drop_hard_filtered(rows, read_text) -> (남길 목록, [제외 row + reason])
  1) 우선주(종류주식) 관련 공시는 삼성전자·현대자동차를 빼고 전부 무시한다(KIND 도 우선주는 다루지 않는다): 증자·자기주식 취득/처분·주식소각 결정에서
     보통주식 수가 0(-)이고 기타주식/종류주식(우선주 등)만 있는 공시, 공시명에 '우선주'가 들어간 공시.
  2) 계열금융회사의 약관에 의한 금융거래(분기 표 공시): 일반적인 영업 거래라 금액과 상관없이 제외.
  3) 특수관계인 금융성 거래(출자·기타유가증권 매수/매도·수익증권거래·계열금융회사 금융거래·자금대여·담보제공·채권매도·유가증권차입)
     - MMF(머니마켓펀드)가 본문에 있으면 금액과 상관없이 제외
     - 거래 금액이 1,000억원 미만이면 제외. 금액을 읽지 못하면 제외하지 않는다(보수적).
  규칙은 제목(공시명)으로 해당 유형을 먼저 고르므로 다른 공시에는 영향이 없다.
"""
import re

THRESHOLD = 100_000_000_000   # 1,000억원
AFFILIATE_FIN = re.compile(r"특수관계인(에대한|으로부터|에게|과의)?(출자|기타유가증권|수익증권거래|자금대여|담보제공|채권매도|유가증권차입)")
GROUP_FIN_ROUTINE = re.compile(r"계열금융회사의약관에의한금융거래")
PREFERRED_EXEMPT = {"005930", "005380"}   # 삼성전자·현대자동차: 우선주 공시도 본다
SHARE_TITLES = re.compile(r"유상증자결정|무상증자결정|자기주식(취득|처분)결정|주식소각결정")
MMF = re.compile(r"MMF|MMW|머니마켓", re.I)
_PRIMARY = r"(출자금액|거래금액|매수금액|매도금액|대여금액|담보제공금액|담보금액|차입금액|양도금액)"
_FALLBACK = r"(?<![누계총])(금액)"   # 누계금액·총출자액 같은 보조 값은 쓰지 않는다


def _squash(s):
    return re.sub(r"\s+", "", s or "")


def _to_won(num, unit, table_unit):
    v = float(num.replace(",", ""))
    mult = {"조": 1e12, "억": 1e8, "백만": 1e6, "천만": 1e7, "만": 1e4, "": table_unit}[unit]
    return v * mult


def affiliate_amount(text):
    """본문에서 거래 금액(원). 표 단위('(단위 : 억 원)' 등)와 금액 옆 단위(억원·조원·백만원)를 반영. 못 읽으면 None."""
    t = re.sub(r"[ \t]+", " ", text or "")
    m = re.search(r"단위\s*:\s*(조|억|백만|천만|만)?\s*원", t)
    table_unit = {"조": 1e12, "억": 1e8, "백만": 1e6, "천만": 1e7, "만": 1e4}.get(m.group(1) if m else None, 1.0)
    vals = []
    for labels in (_PRIMARY, _FALLBACK):   # 주 라벨을 먼저, 없을 때만 일반 '금액'
        for lm in re.finditer(labels + r"\s*(?:\([^)]*\))?\s*[\n:]*\s*([\d,]+(?:\.\d+)?)\s*(조|억|백만|천만|만)?\s*원?", t):
            num, unit = lm.group(2), lm.group(3) or ""
            if num.replace(",", "").replace(".", "").isdigit():
                vals.append(_to_won(num, unit, table_unit))
        if vals:
            break
    return max(vals) if vals else None   # 여러 금액이 있으면 가장 큰 값(누계 같은 값이 섞여도 보수적으로 크게)


def preferred_only(text):
    """증자·자기주식 취득/처분·소각 결정 본문에서 첫 '주식 종류와 수' 블록이 보통주식 0(-)이고 기타주식/종류주식(우선주 등)만 있으면 True."""
    t = re.sub(r"\s+", " ", text or "")
    m = re.search(r"(신주의 종류와 수|취득예정주식\s*\(주\)|처분예정주식\s*\(주\)|소각할 주식의 종류와 수)(.{0,160})", t)
    if not m:
        return False
    blk = m.group(2)
    com = re.search(r"보통주식\s*(?:\(주\))?\s*([\d,\-]+)", blk)
    oth = re.search(r"(?:기타주식|종류주식)\s*(?:\(주\))?\s*([\d,\-]+)", blk)
    zero = lambda x: (not x) or x.group(1).strip() in ("-", "0")
    return zero(com) and not zero(oth)


def classify(row, text):
    """제외 사유(str) 또는 None."""
    nm = _squash(row["report_nm"])
    if row.get("stock_code") not in PREFERRED_EXEMPT:
        if "우선주" in nm:
            return "우선주 공시"
        if SHARE_TITLES.search(nm) and preferred_only(text):
            return "우선주만 대상인 공시"
    if GROUP_FIN_ROUTINE.search(nm):
        return "계열금융회사 약관 금융거래(일반 영업)"
    if AFFILIATE_FIN.search(nm):
        if MMF.search(text or ""):
            return "특수관계인 거래: MMF"
        amt = affiliate_amount(text)
        if amt is not None and amt < THRESHOLD:
            return f"특수관계인 금융거래 1,000억 미만({amt / 1e8:,.0f}억)"
    return None


def drop_hard_filtered(rows, read_text):
    keep, dropped = [], []
    for r in rows:
        why = classify(r, read_text(r))
        if why:
            dropped.append(dict(r, reason=why))
        else:
            keep.append(r)
    return keep, dropped
