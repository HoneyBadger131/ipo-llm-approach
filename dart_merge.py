"""복합공시 병합 단계: 에이전트가 공시별 보고서를 다 만든 뒤, 같은 거래·같은 회사의 같은 날 공시를 한 꼭지로 묶는다(2026-10-20 사용자 결정).

  .venv/bin/python dart_merge.py <YYYYMMDD>            # 묶음 판정 → 병합 에이전트(1회 작성 + 검수, 실패 시 재작성 1회, 그래도 실패하면 규칙 병합) → merge.json
  .venv/bin/python dart_merge.py <YYYYMMDD> --no-agent # 에이전트 없이 규칙 병합만(테스트)

산출물
  trial_case/<day>/merge.json                       : {day, groups:[{rep, members[], file, method(agent|fallback), issues[]}]}
  trial_case/<day>/merged/<대표접수번호>_merged.json  : 병합 보고서(대표 보고서 + 병합 텍스트 + composite{companies, refs[]})
  공시별 보고서(reports/*_v2.json)·PDF·MD 는 그대로 둔다. 화면·메일·주요 공시 모아보기가 apply_merge() 로 병합본을 대신 쓴다.

묶음 규칙(같은 거래 판단은 규칙만 쓴다 — Jev 미사용, 사용자 결정): 같은 날 보고서끼리. **공시 유형군(family)이 다르면 절대 묶지 않는다**(수주 vs 중대재해, 영업양수도 vs 자기주식 등 — 2026-10-21 사용자 결정).
  유형군: 중대재해 / 자기주식(취득·처분·소각) / 잠정실적 / 장래사업계획 / 수주(단일판매·공급계약) / 거래(영업양수도·합병·분할·부동산·특수관계인·타법인주식·출자·담보·자율공시 양수도). 그 밖(투자판단관련주요경영사항 등)은 자동 병합 대상이 아니다.
  (a) 같은 종목이고 같은 유형군이면 묶는다(같은 회사의 여러 공시는 되도록 병합이 기본 원칙).
  (b) 다른 회사끼리: 같은 유형군이면서 금액이 1% 이내로 일치하고(10억 이상) 상대 회사명이 언급되거나 related_ids 로 이어질 때.
  (c) 모회사 사본 쌍둥이: 둘 다 '(자회사/종속회사의 주요경영사항)' 공시이고 기준 제목이 같고 본문이 거의 같을 때(토큰 자카드 0.9 이상). 같은 자회사 사건을 지배구조상 여러 상위회사가 각자 낸 경우다.
  related_ids·키워드만으로는 묶지 않는다(같은 발주처·같은 그룹이라는 이유만으로 별개 회사의 수주가 묶이던 문제, 10-20).
대표 = 묶음 안에서 중요도 > 점수가 가장 높은 공시. 병합본 중요도 = 대표 + 0.5(최대 5). 투심은 건별로 따로 판단하고 묶음 투심도 에이전트가 따로 정한다.
묶인 공시는 사라지지 않는다: 대표 한 건 + 맨 아래 '참고 공시'(날짜·회사·제목·한 줄·건별 투심·DART 링크).
"""
import copy
import glob
import itertools
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(ROOT, ".venv", "bin", "python")
IMP_BONUS = 0.5
AGENT_TIMEOUT = 15 * 60
LABELS = ("긍정적", "부정적", "혼재됨", "알수 없음")
BANNED = re.compile(r"(?<!세금)계산|도구 이력|시장 추정|공시가 아님|역산")


# ---------------- 묶음 ----------------
def load_reports(day):
    out = {}
    for f in glob.glob(os.path.join(ROOT, "trial_case", day, "reports", "*_v2.json")):
        try:
            j = json.load(open(f, encoding="utf-8"))
            out[j["rcept_no"]] = j
        except Exception:  # noqa: BLE001
            continue
    return out


def _money(t):
    return [float(m.group(1).replace(",", "")) * (1e12 if m.group(2) == "조" else 1e8) for m in re.finditer(r"([\d,\.]+)\s*(조|억)", t)]


def _txt(j):
    return " ".join([j["headline"]] + j["keywords"] + [k["value"] for k in j["kpis"]])


def _edge(A, B):
    """서로 다른 회사 보고서 사이의 같은 거래 신호(같은 회사끼리는 무조건 묶으므로 쓰지 않는다)."""
    rel = B["rcept_no"] in A.get("related_ids", []) or A["rcept_no"] in B.get("related_ids", [])
    name = B["corp_name"] in _txt(A) or A["corp_name"] in _txt(B)
    amt = any(abs(x - y) / max(x, y) < 0.01 for x in _money(_txt(A)) for y in _money(_txt(B)) if x > 1e9 and y > 1e9)
    return amt and (name or rel)


FAMILIES = [("incident", r"중대재해"), ("treasury", r"자기주식|주식소각|소각결정"), ("earnings", r"잠정\)?실적|영업\(잠정\)"), ("plan", r"장래사업|경영계획"),
            ("contract", r"단일판매|공급계약|수주"),
            ("deal", r"영업양수|영업양도|합병|분할|부동산|특수관계인|타법인주식|출자|담보|채무보증")]
SUFFIX = re.compile(r"\((자|종속)회사의주요경영사항\)$")


def family(j):
    t = re.sub(r"\s+", "", j["disclosure_title"] + " " + (j.get("event_type") or ""))
    for name, pat in FAMILIES:
        if re.search(pat, t):
            return name
    return None   # 유형군 없음: 자동 병합 대상 아님


def _tokens(day, j):
    p = os.path.join(ROOT, "bodies", day, f"{j['stock_code']}_{j['rcept_no']}.txt")
    try:
        return set(re.findall(r"[0-9A-Za-z가-힣\.,]+", open(p, encoding="utf-8").read().replace("에이치디", "HD")))
    except OSError:
        return set()


def _twin(day, A, B):
    """(c) 모회사 사본 쌍둥이: 같은 자회사 사건을 서로 다른 상위회사가 낸 공시."""
    ta, tb = re.sub(r"\s+", "", A["disclosure_title"]), re.sub(r"\s+", "", B["disclosure_title"])
    if not (SUFFIX.search(ta) and SUFFIX.search(tb) and SUFFIX.sub("", ta) == SUFFIX.sub("", tb)):
        return False
    xa, xb = _tokens(day, A), _tokens(day, B)
    return bool(xa and xb) and len(xa & xb) / len(xa | xb) >= 0.9


def clusters(reports, day=""):
    par = {k: k for k in reports}

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    for a, b in itertools.combinations(reports, 2):
        A, B = reports[a], reports[b]
        fa, fb = family(A), family(B)
        if _twin(day, A, B) or (fa and fa == fb and (A["stock_code"] == B["stock_code"] or _edge(A, B))):
            par[find(a)] = find(b)
    g = {}
    for k in reports:
        g.setdefault(find(k), []).append(k)
    return [sorted(v) for v in g.values() if len(v) > 1]


def rep_of(reports, members):
    # 동점이면 먼저 접수된 공시(접수번호가 작은 쪽)를 대표로: 모회사 사본 쌍둥이는 사건에 더 가까운 쪽이 먼저 나오는 경향(10-20 HD한국조선해양 < HD현대)
    return min(members, key=lambda i: (-reports[i].get("importance", 0), -reports[i].get("importance_score", 0), i))


# ---------------- 에이전트 ----------------
SLIM = ("corp_name", "stock_code", "rcept_no", "disclosure_title", "disclosure_date", "tag", "sentiment", "headline", "impact_summary", "event_type",
        "keywords", "kpis", "points", "importance", "importance_score", "importance_reason", "related_ids")


def write_input(day, reports, members, rep):
    p = os.path.join(ROOT, "trial_case", day, f"merge_input_{rep}.json")
    json.dump({"rep": rep, "members": [{k: reports[i].get(k) for k in SLIM} for i in members]}, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return p


def run_agent(day, rep, inp, feedback=""):
    out = os.path.join(ROOT, "trial_case", day, f"merge_output_{rep}.json")
    if os.path.exists(out):
        os.remove(out)
    prompt = (f"레포 {ROOT} 에서 복합공시 병합 텍스트를 쓴다. 먼저 report_v2/MERGE_SPEC.md 를 읽고 그대로 따른다. 입력: {inp} . 출력: {out} . "
              + (f"앞선 결과의 검수 문제를 고쳐 다시 쓴다: {feedback} . " if feedback else "") + "git 금지, 최종 응답은 3줄 이내.")
    try:
        subprocess.run(["claude", "-p", "--model", "sonnet", "--permission-mode", "acceptEdits", "--allowedTools", "Read Write Edit"],
                       cwd=ROOT, input=prompt, capture_output=True, text=True, timeout=AGENT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None
    try:
        return json.load(open(out, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _nums(s):
    return [t.replace(",", "").rstrip(".") for t in re.findall(r"\d[\d,]*(?:\.\d+)?", s or "")]


def verify(ag, reports, members):
    """검수: 형식, 금지 문구, 구성원 보고서에 없는 숫자. 문제 목록을 돌려준다(비어 있으면 통과)."""
    pr = []
    if not isinstance(ag, dict):
        return ["출력 JSON 없음/형식 오류"]
    for k in ("headline", "brief", "sentiment", "filing_sentiments", "kpis", "points", "importance_reason"):
        if not ag.get(k):
            pr.append(f"{k} 없음")
    if pr:
        return pr
    if (ag["sentiment"] or {}).get("label") not in LABELS:
        pr.append("sentiment.label 오류")
    fs = ag["filing_sentiments"]
    for i in members:
        if (fs.get(i) or {}).get("label") not in LABELS:
            pr.append(f"filing_sentiments[{i}] 없음/오류")
    if len(ag["kpis"]) != 4 or any(not (k.get("label") and k.get("value")) for k in ag["kpis"]):
        pr.append("kpis 는 label·value 가 있는 정확히 4개")
    if not (6 <= len(ag["points"]) <= 9) or any(p.get("type") not in ("pos", "neg", "unk") or not p.get("text") for p in ag["points"]):
        pr.append("points 는 6~9개, type 은 pos/neg/unk")
    texts = [ag["headline"], ag["brief"], ag["sentiment"].get("reason", ""), ag["importance_reason"]] \
        + [x for k in ag["kpis"] for x in (k.get("label", ""), k.get("value", ""), k.get("sub", ""))] + [p.get("text", "") for p in ag["points"]] \
        + [v.get("reason", "") for v in fs.values()]
    if BANNED.search(" ".join(texts)):
        pr.append("금지 문구(계산·역산·도구 이력·시장 추정·공시가 아님)")
    blob = json.dumps([reports[i] for i in members], ensure_ascii=False).replace(",", "")
    allowed = {str(n) for n in range(0, 13)} | {str(len(members)), str(len(members) - 1)}
    bad = sorted({n for t in texts for n in _nums(t) if n not in allowed and n not in blob})
    if bad:
        pr.append(f"구성원 보고서에 없는 숫자: {bad[:8]}")
    if len(ag["headline"]) > 70:
        pr.append("headline 이 너무 김(70자 이내)")
    return pr


def fallback_agent_out(reports, members, rep):
    """에이전트가 실패했을 때의 규칙 병합: 대표 보고서의 텍스트 + 나머지 구성원의 핵심 포인트(중복 제외)."""
    R = reports[rep]
    pts, seen = [], set()
    for i in [rep] + [m for m in members if m != rep]:
        short = reports[i]["corp_name"]
        for p in reports[i]["points"]:
            if p["text"] in seen:
                continue
            seen.add(p["text"])
            pts.append({"type": p["type"], "text": p["text"], "src": short})
    return {"headline": R["headline"], "brief": R["brief"], "sentiment": R["sentiment"],
            "filing_sentiments": {i: reports[i]["sentiment"] for i in members}, "kpis": R["kpis"][:4], "points": pts[:9],
            "importance_reason": R.get("importance_reason", "")}


# ---------------- 조립 ----------------
def assemble(reports, members, rep, ag):
    R = reports[rep]
    m = copy.deepcopy(R)
    order = sorted(members, key=lambda i: (-reports[i].get("importance", 0), -reports[i].get("importance_score", 0), i))
    comp, seen = [], set()
    for i in order:
        c = (reports[i]["corp_name"], reports[i]["stock_code"])
        if c not in seen:
            seen.add(c)
            comp.append({"corp_name": c[0], "stock_code": c[1]})
    news, urls = [], set()
    for i in order:
        for n in reports[i].get("news", []):
            if n["url"] not in urls:
                urls.add(n["url"])
                news.append(n)
    fs = ag["filing_sentiments"]
    refs = [{"rcept_no": i, "corp_name": reports[i]["corp_name"], "stock_code": reports[i]["stock_code"], "disclosure_date": reports[i]["disclosure_date"],
             "disclosure_title": reports[i]["disclosure_title"], "headline": reports[i]["headline"], "importance": reports[i].get("importance"),
             "tag": reports[i]["tag"], "dart_url": reports[i]["dart_url"], "sentiment": fs.get(i) or reports[i]["sentiment"]} for i in order if i != rep]
    tag = "사업 변동" if any(reports[i]["tag"] == "사업 변동" for i in members) else R["tag"]
    imp = min(5, R.get("importance", 0) + IMP_BONUS)
    m.update({"disclosure_title": f"{R['disclosure_title']} 외 {len(members) - 1}건", "tag": tag, "headline": ag["headline"], "brief": ag["brief"], "sentiment": ag["sentiment"],
              "kpis": ag["kpis"], "points": ag["points"], "importance_reason": ag["importance_reason"], "importance": int(imp) if imp == int(imp) else imp,
              "news": news[:4], "related_ids": [i for i in members if i != rep],
              "composite": {"rep": rep, "companies": comp, "refs": refs}})
    if len(comp) > 1 and m.get("financials"):
        m["financials"] = dict(m["financials"], basis=f"{R['corp_name']} · {m['financials'].get('basis', '')}")
    return m


# ---------------- 실행 ----------------
def merge_cluster(day, reports, members, use_agent=True):
    rep = rep_of(reports, members)
    method, issues, ag = "fallback", [], None
    if use_agent:
        inp, fb = write_input(day, reports, members, rep), ""
        for attempt in (1, 2):
            ag = run_agent(day, rep, inp, fb)
            issues = verify(ag, reports, members)
            if not issues:
                method = "agent"
                break
            fb = "; ".join(issues)
            print(f"  [{rep}] 검수 {attempt}회차 문제: {fb}", flush=True)
    if method != "agent":
        ag = fallback_agent_out(reports, members, rep)
    merged = assemble(reports, members, rep, ag)
    os.makedirs(os.path.join(ROOT, "trial_case", day, "merged"), exist_ok=True)
    fpath = f"trial_case/{day}/merged/{rep}_merged.json"
    json.dump(merged, open(os.path.join(ROOT, fpath), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return {"rep": rep, "members": sorted(members), "file": fpath, "method": method, "issues": issues if method != "agent" else []}


def main():
    day = sys.argv[1]
    use_agent = "--no-agent" not in sys.argv
    reports = load_reports(day)
    cl = clusters(reports, day)
    if "--plan" in sys.argv:   # 묶음만 보여 주고 끝낸다(에이전트·파일 쓰기 없음)
        for c in cl:
            print("묶음:", [(reports[i]["corp_name"], reports[i]["disclosure_title"][:22], i[-6:]) for i in c])
        print(f"{day}: 보고서 {len(reports)}건, 묶음 {len(cl)}개")
        return
    p = os.path.join(ROOT, "trial_case", day, "merge.json")
    if not cl:
        if os.path.exists(p):
            os.remove(p)
        print(f"{day}: 병합할 묶음 없음 (보고서 {len(reports)}건)")
        return
    print(f"{day}: 보고서 {len(reports)}건, 묶음 {len(cl)}개 → " + ", ".join(f"{len(c)}건({'·'.join(sorted({reports[i]['corp_name'] for i in c}))})" for c in cl), flush=True)
    with ThreadPoolExecutor(max_workers=3) as ex:
        groups = list(ex.map(lambda c: merge_cluster(day, reports, c, use_agent), cl))
    json.dump({"day": day, "groups": groups}, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for g in groups:
        print(f"  대표 {g['rep']} ← {len(g['members'])}건 [{g['method']}]" + (f" 미해결 검수 문제: {g['issues']}" if g["issues"] else ""))
    print(f"병합 후 보고서 {len(reports) - sum(len(g['members']) - 1 for g in groups)}건")


# ---------------- 화면·메일 쪽 사용 ----------------
def apply_merge(day, rows):
    """같은 날 보고서 dict 목록 → 병합 반영본(구성원 제거, 대표 자리에 병합본). merge.json 이 없거나 읽기 실패면 그대로."""
    try:
        mj = json.load(open(os.path.join(ROOT, "trial_case", day, "merge.json"), encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return rows
    drop, put = set(), {}
    for g in mj.get("groups", []):
        try:
            put[g["rep"]] = json.load(open(os.path.join(ROOT, g["file"]), encoding="utf-8"))
            drop |= set(g["members"])
        except Exception:  # noqa: BLE001 — 병합본을 못 읽으면 그 묶음은 병합하지 않는다
            continue
    out = []
    for r in rows:
        i = r["rcept_no"]
        if i in put:
            out.append(put[i])
        elif i not in drop:
            out.append(r)
    return out


if __name__ == "__main__":
    main()
