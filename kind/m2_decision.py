"""주요사항보고서(유상증자결정) 본문 파서 → 정규화된 dict.
정정공시는 '정정 표 + 정정 반영된 전문' 구조라 전문 구간(마지막 '유상증자 결정 / 1. 신주의 종류와 수' 이후)만 읽으면 항상 최신 값이다.
"""
import re

from m1_parser import kdate


def toks(s):
    return [x.strip() for x in re.split(r"\|\s*\n|\n|\|", s) if x.strip()]


def num(s):
    s = (s or "").replace(",", "").strip()
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return None


def split_items(tk):
    """토큰열을 '1.' '2.' … 순번 헤더 기준으로 {번호: (라벨, [값토큰])}"""
    items, cur, expect = {}, None, 1
    for t in tk:
        m = re.match(r"^(\d{1,2})\.\s*(.*)$", t)
        if m and int(m.group(1)) == expect:
            cur = expect
            items[cur] = (m.group(2).strip(), [])
            expect += 1
        elif cur:
            items[cur][1].append(t)
    return items


def after(vals, label, n=1, stop=None):
    """vals 에서 label 토큰 다음 n번째 값"""
    for i, v in enumerate(vals):
        if v.startswith(label):
            return vals[i + n] if i + n < len(vals) else None
    return None


def parse_decision(text):
    out = {"amend_of": None, "amend_note": None}
    m = re.search(r"정정대상 공시서류의 최초제출일\s*:\s*\|?\s*\n?\s*([^\n|]+)", text)
    if m:
        out["amend_of"] = kdate(m.group(1))
    m = re.search(r"※\s*(금번[^\n]*?정정은[^\n]*?)(?:\n|$)", text)
    if m:
        out["amend_note"] = re.sub(r"\s+", " ", m.group(1))[:200]
    ms = list(re.finditer(r"유상증자\s*결정\s*\n\s*1\.\s*신주의 종류와 수", text))
    if not ms:
        return None
    body = text[ms[-1].start():]
    it = split_items(toks(body))
    g = lambda n: it.get(n, ("", []))[1]
    lab = lambda n: it.get(n, ("", []))[0]
    # 번호가 서식마다 조금 다를 수 있어 라벨로 찾는다
    byl = {}
    for n, (l, v) in it.items():
        byl[re.sub(r"\s+", "", l.split("(")[0])] = v  # 라벨 공백 차이('신주의 상장예정일' / '신주의 상장 예정일') 무시
    def item(key):
        key = re.sub(r"\s+", "", key)
        for k, v in byl.items():
            if key in k:
                return v
        return []
    v = item("신주의 종류와 수")
    out["new_shares"] = num(after(v, "보통주식"))  # 보통주식 (주) 다음 값
    out["new_shares_other"] = num(after(v, "기타주식"))
    out["par"] = num((item("1주당 액면가액") or [None])[0])
    v = item("증자전")
    out["pre_shares"] = num(after(v, "보통주식"))
    v = item("자금조달의 목적")
    use = {}
    for i in range(0, len(v) - 1, 2):
        use[re.sub(r"\s*\(원\)", "", v[i])] = num(v[i + 1]) or 0
    out["use_of_funds"] = {k: x for k, x in use.items() if x}
    out["method"] = (item("증자방식") or [None])[0]
    v = item("신주 발행가액")
    out["price_confirmed"] = num(after(v, "확정발행가", 2)) if after(v, "확정발행가", 1) == "보통주식 (원)" else None
    # 토큰: ['확정발행가','보통주식 (원)','-', '기타주식 (원)','-','예정발행가','보통주식 (원)','1,174,000','확정예정일','2026년 11월 04일', …]
    try:
        i = v.index("예정발행가")
        out["price_expected"] = num(v[i + 2])
        out["price_confirm_due"] = kdate(v[i + 4]) if v[i + 3].startswith("확정예정일") else None
    except (ValueError, IndexError):
        out["price_expected"] = out["price_confirm_due"] = None
        if v and v[0].startswith("보통주식") and len(v) > 1:  # 제3자배정 등: '보통주식 (원) | 2,555,000' 단일 값(정정으로 확정되기 전엔 참고가)
            out["price_expected"] = num(v[1])
    out["record_date"] = kdate((item("신주배정기준일") or [""])[0])
    out["alloc_ratio"] = num((item("1주당 신주배정주식수") or [None])[0])
    out["esop_pct"] = num((item("우리사주조합원 우선배정비율") or [None])[0])
    v = item("청약예정일")
    sub = {}
    cur = None
    for i, t in enumerate(v):
        if t in ("우리사주조합", "구주주", "일반주주", "일반공모", "제3자"):
            cur = t
        elif t == "시작일" and cur:
            sub[cur + "_start"] = kdate(v[i + 1])
        elif t == "종료일" and cur:
            sub[cur + "_end"] = kdate(v[i + 1])
    out["subscription"] = sub
    out["payment_date"] = kdate((item("납입일") or [""])[0])
    out["dividend_from"] = kdate((item("신주의 배당기산일") or [""])[0])
    out["listing_date"] = kdate((item("신주의 상장예정일") or [""])[0])
    out["lead_underwriters"] = (item("대표주관회사") or [None])[0]
    out["rights_tradable"] = (item("신주인수권양도여부") or [None])[0]
    v = item("신주인수권양도여부")
    out["rights_listed"] = after(v, "- 신주인수권증서의 상장여부") if after(v, "- 신주인수권증서의 상장여부") else None
    out["board_date"] = kdate((item("이사회결의일") or [""])[0])
    v = item("청약이 금지되는 공매도")
    if v:
        s_ = [kdate(x) for x in v if kdate(x)]
        out["shortsale_ban"] = (s_[0], s_[-1]) if len(s_) >= 2 else None
    # 일반공모 청약일: 주1) '… 2026년 11월 12일부터 2026년 11월 13일까지' 또는 24번 표의 '일반공모청약 … 일 ~ 일'
    m = re.search(r"(\d{4}년\s*\d+월\s*\d+일)\s*부터\s*(\d{4}년\s*\d+월\s*\d+일)\s*까지[^\n]{0,12}일반공모\s*청약", body)
    if not m:
        m = re.search(r"일반공모\s*청약(?:\([^)]*\))?\s*\|?\s*[^\n]{0,60}?\|?\s*(\d{4}년\s*\d+월\s*\d+일)\s*~\s*(\d{4}년\s*\d+월\s*\d+일)", body)
    out["public_offer"] = (kdate(m.group(1)), kdate(m.group(2))) if m else None
    return out
