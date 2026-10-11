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

import hashlib
import json as _json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "cache")
RAW = os.path.join(HERE, "data", "raw")
OFFLINE = os.environ.get("KIND_OFFLINE") == "1"  # 1 이면 캐시만 사용(네트워크 호출 금지). rebuild_all.sh --offline


def _cache_path(kind, key):
    os.makedirs(CACHE, exist_ok=True)
    return os.path.join(CACHE, f"{kind}_{hashlib.sha1(_json.dumps(key, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]}.json")


def _cached(kind, key, fetch, fresh_if=None):
    """목록류 조회 결과 캐시. 종료일이 충분히 과거(오늘-5일 이전)인 조회는 영구 캐시, 최근 구간은 6시간 TTL.
    OFFLINE 이면 캐시만 사용하고 없으면 오류."""
    p = _cache_path(kind, key)
    if os.path.exists(p):
        d = _json.load(open(p, encoding="utf-8"))
        old = d.get("to") and d["to"] < (dt_today() - __import__("datetime").timedelta(days=5)).isoformat()
        if OFFLINE or old or (time.time() - d["at"] < 6 * 3600):
            return d["rows"]
    if OFFLINE:
        raise RuntimeError(f"OFFLINE 모드: 캐시 없음 {kind} {key}")
    rows = fetch()
    # 빈 결과도 캐시한다. 단 차단(403)은 KindBlocked 예외로 올라오므로 여기까지 오지 않는다.
    # (KIND 는 1년 초과 구간 조회에도 오류 없이 0건을 주므로 호출부에서 330일 이하로 쪼갠다)
    _json.dump({"at": time.time(), "to": key.get("to"), "rows": rows}, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return rows


def dt_today():
    return __import__("datetime").date.today()


class KindBlocked(RuntimeError):
    """KIND 방화벽(Akamai) 차단 — HTTP 403 / 'Access Denied'. 빈 목록으로 오해하지 않도록 반드시 예외로 올린다."""


class _Sess(requests.Session):
    def request(self, method, url, **kw):
        for k_ in range(6):  # 간헐적 차단은 백오프 재시도(3,6,12,24,48초) 후에도 막히면 예외
            r = super().request(method, url, **kw)
            if not (r.status_code in (403, 429) or "Access Denied" in r.text[:400]):
                return r
            time.sleep(3 * 2 ** k_)
        raise KindBlocked(f"KIND 접근 차단 {r.status_code}: {url}")


_s = _Sess()
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
    key = {"code": code, "name": name, "frm": frm, "to": to, "mc": market_codes, "extra": extra}
    return _cached("list", key, lambda: _list_filings(code, name, frm, to, market_codes, page_size, max_pages, **extra))


def _list_filings(code="", name="", frm="", to="", market_codes=None, page_size=100, max_pages=50, **extra):
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
    p = os.path.join(RAW, acpt_no[:4], acpt_no[4:6], f"{acpt_no}.html")
    if which is None and os.path.exists(p):
        return open(p, encoding="utf-8").read()
    if OFFLINE:
        raise RuntimeError(f"OFFLINE 모드: 본문 캐시 없음 {acpt_no}")
    doc = _pick_doc(acpt_no, which)
    time.sleep(SLEEP)
    u = _doc_url(doc)
    h = _s.get(u, timeout=30).content.decode("utf-8", "replace")
    if which is None:  # 온디맨드로 읽은 본문도 캐시(수집기 raw 캐시와 같은 경로)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8").write(h)
    return h


def body_text(acpt_no, which=None):
    """본문 텍스트(첨부 제외). 표는 ' | ' 구분 평문."""
    return _html_to_text(body_html(acpt_no, which))


def prior_versions(acpt_no):
    """정정공시의 기공시 본문 목록(selected 가 아닌 본문) = 정정 체인의 앞부분 [(docNo,label)]."""
    return [(d, l) for d, s, l in _viewer_docs(acpt_no) if not s]


def list_etf_filings(code, name, frm, to, page_size=100, max_pages=50):
    return _cached("etf", {"code": code, "name": name, "frm": frm, "to": to}, lambda: _list_etf_filings(code, name, frm, to, page_size, max_pages))


def _list_etf_filings(code, name, frm, to, page_size=100, max_pages=50):
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


def resolve_name(name, refresh=False):
    """종목명 → KIND 종목 정보. 영구 캐시(상장 전 조회가 빈 결과로 고정되지 않도록 refresh=True 로 다시 받아 덮어쓸 수 있다; OFFLINE 이면 무시)."""
    key = {"name": name, "to": "2000-01-01"}
    if refresh and not OFFLINE:
        rows = _resolve_name(name)
        _json.dump({"at": time.time(), "to": key["to"], "rows": rows}, open(_cache_path("resolve", key), "w", encoding="utf-8"), ensure_ascii=False)
        return rows
    return _cached("resolve", key, lambda: _resolve_name(name))


def _resolve_name(name):
    """KIND 종목명 자동완성 JSON → [{repisusrtcd:'A005930', repisucd(ISIN), isurcd, comabbrv, secugrpId(ST/EF…)}]. 우선주는 별도 항목이 없다."""
    import json
    _warmup()
    r = _s.post(f"{BASE}/common/searchcorpname.do", data=dict(method="searchCorpNameJson", searchCodeType="", searchCorpName=name),
                headers={"X-Requested-With": "XMLHttpRequest"}, timeout=20)
    return json.loads(r.text.strip() or "[]")


_TYPES = None


def filing_type_codes(retries=4):
    """상세검색 화면의 대분류별 세부 유형 → ({major: [(code,name)]}, {major: 대분류명}). major: '01'수시 '02'시장조치 '04'신고사항 …
    프로세스 안에서 1회만 조회(메모)하고, 응답이 비정상(대분류 누락)이면 재시도한다."""
    global _TYPES
    if _TYPES:
        return _TYPES
    fp = os.path.join(HERE, "data", "filing_types.json")
    if os.path.exists(fp):  # 유형 코드는 거의 안 바뀌므로 영구 캐시(삭제하면 재조회)
        d = _json.load(open(fp, encoding="utf-8"))
        _TYPES = ({k: [tuple(x) for x in v] for k, v in d["codes"].items()}, d["majors"])
        return _TYPES
    if OFFLINE:
        raise RuntimeError("OFFLINE 모드: filing_types.json 없음")
    _warmup()
    for k_ in range(retries):
        t = _s.get(f"{BASE}/disclosure/details.do?method=searchDetailsMain", timeout=30).text
        out = {}
        for m in re.finditer(r'name="disclosureTypeArr(\d\d)"[^>]*value="(\d+)"[^>]*/>\s*<label[^>]*>([^<]*)', t):
            out.setdefault(m.group(1), []).append((m.group(2), html.unescape(m.group(3)).strip()))
        majors = {m.group(1): m.group(2) for m in re.finditer(r'id="dsclsType(\d\d)"[^>]*><span>([^<]*)', t)}
        if all(x in out for x in ("01", "02", "04", "07")):
            _TYPES = (out, majors)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            _json.dump({"codes": out, "majors": majors}, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
            return _TYPES
        time.sleep(2 * (k_ + 1))
    raise RuntimeError("KIND 공시유형 코드 조회 실패(대분류 누락) — 잠시 후 재시도")


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
