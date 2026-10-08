"""Jev 시험 공용 함수: state 구성, API 호출(재시도), 정정 구간 추출."""
import glob
import json
import os
import re
import sys
import time

import requests

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
DATA = os.path.join(ROOT, "jev_test", "data")
API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"  # 별칭(jev-latest) 대신 버전을 고정해 결과 재현성을 확보한다


def digest(text, cap=1500):
    """판단용 요약 (dart_prep_day.digest와 동일 규칙): 짧으면 전문, 길면 앞부분 + 금액·비율 등 핵심 줄."""
    t = re.sub(r"\n+", " / ", text)
    if len(t) <= cap:
        return t
    head = t[:800]
    keys = [x for x in re.split(r" / ", t[800:])
            if re.search(r"원|%|금액|비율|목적|상대|기간|사유|내용|계약", x) and len(x) < 140]
    return head + " ... " + " / ".join(keys)[:700]


_NUM = re.compile(r"(?<![\d,])(\d{1,3}(?:,\d{3}){2,})(?![\d,])")


def _eok(v):
    return f"{v // 10**12}조 {(v % 10**12) // 10**8:,}억 원" if v >= 10**12 else f"{v // 10**8:,}억 원"


def annotate_won(s):
    """1억 원 이상의 원 단위 숫자 뒤에 '(약 N억 원)'을 붙인다 — 30억 원 기준과 바로 비교할 수 있게(코드가 할 일)."""
    def rep(m):
        v = int(m.group(1).replace(",", ""))
        if v < 10**8 or not re.search(r"원|금액|액", s[max(0, m.start() - 40):m.start()]):
            return m.group(0)
        return f"{m.group(0)}(약 {_eok(v)})"
    return _NUM.sub(rep, s)


_PAIR = re.compile(r"([^/]{1,60}?) / (-?\d[\d,]*(?:\.\d+)?) / (-?\d[\d,]*(?:\.\d+)?)(?= / |$)")


def correction_delta(sec):
    """정정 표의 '정정전 / 정정후' 숫자 쌍에서 증감을 계산한다. 예: '계약금액(원): +7.2% (+352억 원)'"""
    i = sec.find("정정후")
    out = []
    for m in _PAIR.finditer(sec[i:] if i >= 0 else sec):
        a, b = (float(m.group(k).replace(",", "")) for k in (2, 3))
        if a == b or a == 0:
            continue
        label = m.group(1).strip().split(" / ")[-1][-40:]
        txt = f"{label}: {a:,.0f}→{b:,.0f}" if abs(a) >= 1000 else f"{label}: {a:g}→{b:g}"
        txt += f" ({(b - a) / abs(a) * 100:+.1f}%"
        if "원" in label or "금액" in label:
            d = int(b - a)
            txt += f", {'+' if d > 0 else '-'}{_eok(abs(d))}"
        out.append(txt + ")")
    return out[:6]


def body_path(case):
    return os.path.join(DATA, "bodies", case["day"], f"{case['stock_code']}_{case['rcept_no']}.txt")


def read_body(case):
    p = body_path(case)
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def correction_section(text, cap=1200):
    """정정 공시 본문 앞부분(정정사유 / 정정사항 정정전·정정후 표)을 그대로 자른다.
    표 안에 '-' 셀이 있어 구분선으로 자르면 값이 빠지므로 고정 길이로 자른다."""
    if not (text.startswith("정정신고") or "정정사항" in text[:600]):
        return ""
    return re.sub(r"\n+", " / ", text[:cap])


_FIN = re.compile(r"증권|은행|금융|보험|생명|화재|캐피탈|카드|자산운용|손해")
_DISPUTE = None


def dispute_names():
    """watchlists/dispute_watchlist.json 의 회사명 집합 (없으면 빈 집합)."""
    global _DISPUTE
    if _DISPUTE is None:
        p = os.path.join(ROOT, "watchlists", "dispute_watchlist.json")
        _DISPUTE = {c["name"] for c in json.load(open(p, encoding="utf-8"))["companies"]} if os.path.exists(p) else set()
    return _DISPUTE


def _is_large(stock_code):
    from rules_core import is_large_cap
    return is_large_cap(stock_code)


def build_state(case, mode, ver="v0"):
    """mode 'T' = 제목만, 'TD' = 제목 + 본문 요약(정정이면 정정 구간 포함)."""
    st = {"title": case["report_nm"], "company": case["corp_name"]}
    if ver >= "v2":   # 정책 v0.3: 분쟁 리스트·금융회사 맥락을 코드가 알려 준다
        if case["corp_name"] in dispute_names():
            st["company_context"] = ("On the shareholder-rights / ESG proxy-fight and activist watchlist: AGM results, director appointments, "
                                     "and ownership or governance changes are material for this company.")
        if ver >= "v3" and _is_large(case["stock_code"]):
            st["cap_note"] = "Large cap (market-cap top 30): be sensitive; borderline items matter more for this company."
        if _FIN.search(case["corp_name"]):
            st["sector_note"] = "Financial company: guarantees, loans, beneficiary certificates and borrowings are everyday business."
    if mode == "TD":
        body = read_body(case)
        corr = correction_section(body) if case.get("is_correction") else ""
        if corr:
            st["correction"] = annotate_won(corr) if ver != "v0" else corr
            if ver != "v0":
                d = correction_delta(corr)
                st["correction_delta"] = d if d else "숫자 항목의 증감 없음(일정·문구 정정)"
        rest = body[1200:] if corr else body   # 정정이면 앞 1,200자는 correction에 이미 담았다
        if rest.strip():
            st["body"] = annotate_won(digest(rest, 6000 if ver >= "v2" else 1500)) if ver != "v0" else digest(rest)
    return st


def call_jev(state, questions, key, retries=5):
    body = {"state": state, "model": MODEL, "questions": questions}
    for i in range(retries):
        try:
            r = requests.post(API, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=90)
        except requests.RequestException as e:
            time.sleep(2 ** i)
            err = str(e)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(2 ** i, 20))
            err = f"{r.status_code} {r.text[:120]}"
            continue
        return {"error": f"{r.status_code} {r.text[:300]}"}
    return {"error": f"retries exhausted: {err}"}


def load_cases():
    """cases/cases_*.json 을 모두 합쳐 반환한다 (개발 주간 + 검증 주간)."""
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "jev_test", "cases", "cases_*.json"))):
        out += json.load(open(p, encoding="utf-8"))
    layers = (("labels_policy.json", "policy"), ("labels_human.json", "human"))   # 우선순위: Claude 기본 < 정책 < 사람 명시 판정
    for fname, src in layers:
        lp = os.path.join(ROOT, "jev_test", "cases", fname)
        if not os.path.exists(lp):
            continue
        over = json.load(open(lp, encoding="utf-8"))
        for c in out:
            h = over.get(c["rcept_no"])
            if h:
                c.setdefault("label_ai", c["label"])
                c["label"], c["label_source"] = h["label"], src
                note = h.get("memo") or h.get("why") or ""
                if note:
                    c["label_reason"] = f"[{src}] {note} | " + c["label_reason"]
    return out
