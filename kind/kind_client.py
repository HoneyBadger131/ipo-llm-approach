"""KIND(kind.krx.co.kr) 최소 클라이언트: 상세검색 목록 + 공시 본문 텍스트.

로그인/키 불필요. 서버 부하를 고려해 요청 사이 sleep(기본 0.5s)을 둔다.
CLI:
  python kind/kind_client.py list 005930 2026-09-01 2026-10-08 [0303,0321,...]   # 시장조치(02) 하위 코드 필터
  python kind/kind_client.py all  005930 2026-01-01 2026-10-08                   # 전 유형(페이지 순회)
  python kind/kind_client.py body 20260724000133                                 # 본문 텍스트
"""
import html
import re
import sys
import time

import requests

BASE = "https://kind.krx.co.kr"
SLEEP = 0.5

_s = requests.Session()
_s.headers["User-Agent"] = "Mozilla/5.0"
_warm = False


def _warmup():
    global _warm
    if not _warm:
        _s.get(f"{BASE}/disclosure/details.do?method=searchDetailsMain", timeout=20)
        _warm = True


def _strip(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", h))).strip()


def _parse_rows(t):
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S):
        m = re.search(r"openDisclsViewer\('(\d+)'.*?title='([^']*)'", tr, re.S)
        if not m:
            continue
        tds = [_strip(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        # tds: 번호, 일시(YYYY-MM-DD HH:MM), 회사명, 제목, 제출인, ...
        out.append({"acpt_no": m.group(1), "title": html.unescape(m.group(2)),
                    "datetime": tds[1] if len(tds) > 1 else "", "company": tds[2] if len(tds) > 2 else ""})
    return out


def list_filings(code="", name="", frm="", to="", market_codes=None, page_size=100, max_pages=50, **extra):
    """상세검색. code는 6자리 단축코드(내부에서 'A' 접두). market_codes=['0303',..] 이면 시장조치(02) 하위 유형만.
    종목 미지정 시 전 종목 대상(기간이 1년을 넘으면 서버가 거부하므로 주의)."""
    _warmup()
    res, seen = [], set()
    for page in range(1, max_pages + 1):
        d = dict(method="searchDetailsSub", currentPageSize=str(page_size), pageIndex=str(page), orderMode="1",
                 orderStat="D", forward="details_sub", searchCodeType="", repIsuSrtCd=("A" + code) if code else "",
                 allRepIsuSrtCd="", searchCorpName=name, fromDate=frm, toDate=to, bfrDsclsType="on")
        if market_codes:
            v = "|".join(market_codes) + "|"
            d.update(disclosureType02=v, pDisclosureType02=v)
        d.update(extra)
        r = _s.post(f"{BASE}/disclosure/details.do", data=d, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=30)
        rows = [x for x in _parse_rows(r.text) if x["acpt_no"] not in seen]
        if not rows:
            break
        seen.update(x["acpt_no"] for x in rows)
        res += rows
        if len(rows) < page_size:
            break
        time.sleep(SLEEP)
    return res


def _viewer_docs(acpt_no):
    """뷰어에서 본문 목록 [(docNo, selected, label)]. 정정공시는 원본(기공시)과 정정본이 함께 나열되며 selected=True 가 해당 접수번호의 본문."""
    _warmup()
    v = _s.get(f"{BASE}/common/disclsviewer.do", params=dict(method="search", acptno=acpt_no, docno="", viewerhost="", viewerport=""), timeout=30).text
    m = re.search(r'<select id="mainDoc".*?</select>', v, re.S)
    out = []
    for o in re.finditer(r"<option value='(\d+)\|(\w)'([^>]*)>([^<]*)", m.group(0) if m else ""):
        out.append((o.group(1), "selected" in o.group(3), html.unescape(o.group(4)).strip()))
    return out


def _doc_url(doc_no):
    r = _s.post(f"{BASE}/common/disclsviewer.do", data=dict(method="searchContents", docNo=doc_no), timeout=30).text
    return re.search(r"setPath\('[^']*',\s*'([^']+)'", r).group(1)


def _pick_doc(acpt_no, which=None):
    docs = _viewer_docs(acpt_no)
    if not docs:
        raise LookupError(f"본문 없음 {acpt_no}")
    if which is not None:
        return docs[which][0]
    sel = [d for d in docs if d[1]]
    return (sel or docs)[-1][0]


def _html_to_text(t):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", t, flags=re.S | re.I)
    t = re.sub(r"</(tr|p|div|table)>", "\n", t, flags=re.I)
    t = re.sub(r"</t[dh]>", " | ", t, flags=re.I)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def body_html(acpt_no, which=None):
    """본문 원본 HTML(표 구조 파싱용). which=None → 해당 접수번호 본문(selected)."""
    doc = _pick_doc(acpt_no, which)
    time.sleep(SLEEP)
    u = _doc_url(doc)
    return _s.get(u, timeout=30).content.decode("utf-8", "replace")


def body_text(acpt_no, which=None):
    """본문 텍스트(첨부 제외). 표는 ' | ' 구분 평문."""
    return _html_to_text(body_html(acpt_no, which))


def prior_versions(acpt_no):
    """정정공시의 기공시 본문 목록(selected 가 아닌 본문) = 정정 체인의 앞부분 [(docNo,label)]."""
    return [(d, l) for d, s, l in _viewer_docs(acpt_no) if not s]


def list_etf_filings(code, name, frm, to, page_size=100, max_pages=50):
    """ETF 전용 목록(공시+ > ETF/ELW/ETN). 일괄공시 `ETF 추가ㆍ변경상장신청서(수량변경)(일괄공시)`는 상세검색 목록에는 안 나오고 이 엔드포인트에서만 나온다."""
    _warmup()
    res, seen = [], set()
    for page in range(1, max_pages + 1):
        d = dict(method="searchDisclosureByStockTypeEtfSub", currentPageSize=str(page_size), pageIndex=str(page), orderMode="1",
                 orderStat="D", forward="disclosurebystocktype_etf_sub", searchCodeType="", repIsuSrtCd="A" + code,
                 searchCorpName=name, etfIsuSrtCd="A" + code, etfIsuSrtNm=name, fromDate=frm, toDate=to, reportNm="", reportCd="")
        r = _s.post(f"{BASE}/disclosure/disclosurebystocktype.do", data=d, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=30)
        rows = [x for x in _parse_rows(r.text) if x["acpt_no"] not in seen]
        if not rows:
            break
        seen.update(x["acpt_no"] for x in rows)
        res += rows
        if len(rows) < page_size:
            break
        time.sleep(SLEEP)
    return res


def resolve_name(name):
    """KIND 종목명 자동완성 JSON → [{repisusrtcd:'A005930', repisucd(ISIN), isurcd, comabbrv, secugrpId(ST/EF…)}]. 우선주는 별도 항목이 없다."""
    import json
    _warmup()
    r = _s.post(f"{BASE}/common/searchcorpname.do", data=dict(method="searchCorpNameJson", searchCodeType="", searchCorpName=name),
                headers={"X-Requested-With": "XMLHttpRequest"}, timeout=20)
    return json.loads(r.text.strip() or "[]")


def filing_type_codes():
    """상세검색 화면의 대분류별 세부 유형 → ({major: [(code,name)]}, {major: 대분류명}). major: '01'수시 '02'시장조치 '04'신고사항 …"""
    _warmup()
    t = _s.get(f"{BASE}/disclosure/details.do?method=searchDetailsMain", timeout=30).text
    out = {}
    for m in re.finditer(r'name="disclosureTypeArr(\d\d)"[^>]*value="(\d+)"[^>]*/>\s*<label[^>]*>([^<]*)', t):
        out.setdefault(m.group(1), []).append((m.group(2), html.unescape(m.group(3)).strip()))
    majors = {m.group(1): m.group(2) for m in re.finditer(r'id="dsclsType(\d\d)"[^>]*><span>([^<]*)', t)}
    return out, majors


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] in ("list", "all"):
        codes = a[4].split(",") if len(a) > 4 else None
        for x in list_filings(code=a[1], frm=a[2], to=a[3], market_codes=codes):
            print(x["datetime"], x["acpt_no"], x["title"])
    elif a and a[0] == "body":
        print(body_text(a[1]))
    else:
        print(__doc__)
