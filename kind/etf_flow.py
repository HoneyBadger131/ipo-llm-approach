"""ETF 설정/환매 흐름 집계 → 리포트 'ETF 흐름' 탭 데이터 (읽기 전용 DB 조회).

  .venv/bin/python kind/etf_flow.py [YYYY-MM-DD]      # 집계 JSON 요약 출력(콘솔)
  .venv/bin/python kind/etf_flow.py --check [날짜]    # 코멘트(kind/etf_comment.json)의 숫자를 집계 값과 대조

정의(2026-10-11 합의): 금액 = 순증감 좌수 × 설정/환매일 종가(etf_price; 없으면 스냅샷가로 근사, 그것도 없으면 금액 미산정).
창은 최신 설정일 L(공시 보고일 ≤ 기준일) 기준 — 1일 = L 하루, 7일 = 달력 7일(L-6 ~ L), 3개월 = 달력 3개월. (네이버 누적순유입 대비 1일·7일 1% 이내 일치, 3개월은 10~30% 차이)
표본: KIND 수집 경로상 8개 운용사(삼성·미래·KB·한투·한화·NH-Amundi·신한·타임폴리오)의 ETF. '전체 시장'이 아니다.
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

HERE = os.path.dirname(os.path.abspath(__file__))
COMMENT_PATH = os.path.join(HERE, "etf_comment.json")
WINDOWS = [("1d", "1일"), ("7d", "7일"), ("3m", "3개월")]
TOPN = 6

# 테마 태깅: 이름 키워드, 위에서부터 첫 일치. (대분류, 방향)
THEMES = [
    ("채권·머니마켓", r"채권|금융채|국채|국고채|회사채|특수채|머니마켓|MMF|CD금리|KOFR|금리|단기|통안|SOFR|전단채|파킹|초단기|CMA|예금"),
    ("해외 지수", r"미국|S&P|나스닥|필라델피아|다우|일본|닛케이|중국|차이나|인도|베트남|유럽|선진국|신흥|글로벌|항셍|홍콩|대만|브라질|MSCI(?! ?Korea)|테슬라|엔비디아|빅테크|월드|WORLD|아시아|이머징|인도네시아|멕시코|독일|영국|캐나다|호주|달러|USD|금현물|국제금|금액티브|은액티브|골드|구리|원유|은선물|원자재|비트코인|이더리움|ETH|BTC|농산물|팔라듐"),
    ("TDF·자산배분", r"TDF|TRF|자산배분|BBIG"),
    ("레버리지", r"레버리지|2X|3X"),
    ("인버스", r"인버스|곱버스"),
    ("원자력·SMR", r"원자력|SMR|원전|우라늄"),
    ("AI·반도체", r"AI|반도체|HBM|데이터센터|GPU|팹리스|테크TOP|소프트웨어|클라우드|인프라|전력기기|전력설비"),
    ("2차전지·에너지", r"2차전지|배터리|리튬|전고체|에너지|태양광|수소|전력|풍력"),
    ("바이오·헬스", r"바이오|헬스|제약|의료"),
    ("방산·조선·로봇", r"방산|조선|로봇|우주|항공|K방산|K-방산"),
    ("배당·커버드콜", r"배당|커버드콜|프리미엄|타겟|월배당|인컴|고배당"),
    ("금융·지주", r"은행|증권|보험|금융|지주"),
    ("업종(자동차·소비·산업)", r"자동차|화장품|여행|레저|미디어|컨텐츠|콘텐츠|KPOP|건설|음식|소비|게임|엔터|철강|화학|운송|기계|제조업|수출|필수|경기"),
    ("국내 시장대표", r"그룹|Top5|MSCI Korea|KRX\s*100|코리아|한국|(?<![\d.])200(?!\d)|코스닥\s*150|코스피|KRX\s*300|KOSPI|코스닥|TOP\s*10|K200|밸류업|ESG|우량|가치|성장|모멘텀|퀄리티|저변동|로우볼"),
]
EXCLUDE = {"채권·머니마켓", "해외 지수", "TDF·자산배분"}   # 리포팅 제외(사용자 지침 2026-10-11): 시장 심리·국내 테마와 무관하거나 해외 자산


TAB_EXCL = {4: "해외 지수", 5: "해외 지수", 6: "채권·머니마켓", 7: "채권·머니마켓"}   # 네이버 etfTabCode(해외주식·원자재·채권·혼합) — 이름 규칙보다 우선


def theme(name, tab=None):
    if tab in TAB_EXCL:
        return TAB_EXCL[tab]
    for t, pat in THEMES:
        if tab in (1, 2, 3) and t == "해외 지수":   # 국내 분류로 확인된 ETF 는 이름의 '미국' 등으로 해외로 보내지 않는다
            continue
        if re.search(pat, name, re.I):
            return t
    return "기타"


def won(v):
    """원 → 억원/조원 문자열(부호 포함)"""
    if v is None:
        return "-"
    s = "+" if v > 0 else "−" if v < 0 else ""
    a = abs(v)
    if a >= 1e12:
        return f"{s}{a / 1e12:.2f}조원"
    if a >= 1e8:
        return f"{s}{round(a / 1e8):,}억원"
    return f"{s}{round(a / 1e4):,}만원"


def units_txt(v):
    s = "+" if v > 0 else "−" if v < 0 else ""
    a = abs(v)
    return f"{s}{a / 1e4:,.0f}만좌" if a >= 1e4 else f"{s}{a:,}좌"


def windows(L):
    d = dt.date.fromisoformat(L)
    y, m = d.year, d.month - 3
    if m < 1:
        m += 12; y -= 1
    d3 = dt.date(y, m, min(d.day, 28)) + dt.timedelta(days=1)
    return {"1d": L, "7d": (d - dt.timedelta(days=6)).isoformat(), "3m": d3.isoformat()}


def _p(txt):
    """부호 제거(문장에서 들어왔/빠졌 로 방향을 말한다)"""
    return txt.lstrip("+−-")


def _dir(v, pos="들어왔", neg="빠졌"):
    return pos if v >= 0 else neg


def auto_comment(d):
    """집계 값만으로 만드는 기본 코멘트(쉬운 문장). kind/etf_comment.json 에 그 날짜 항목이 있으면 그쪽(수작업·에이전트)이 우선한다."""
    W, L = d["windows"], d["latest"][5:].replace("-", "/")
    w1, w7, w3 = W["1d"], W["7d"], W["3m"]
    lines = []
    big = max(w1["inflow"][:1] + w1["outflow"][:1], key=lambda i: abs(i["amt"]), default=None)
    t = f"{L} 하루 국내 ETF는 {_p(w1['total_txt'])} 순{'유입' if w1['total'] >= 0 else '유출'}이었습니다."
    if big:
        t += f" {big['name']} 한 종목에서 {_p(big['amt_txt'])}이 {'설정' if big['amt'] > 0 else '환매'}된 영향이 큽니다." if abs(big["amt"]) >= 0.5 * abs(w1["total"]) else f" 가장 큰 변화는 {big['name']}의 {_p(big['amt_txt'])} {'설정' if big['amt'] > 0 else '환매'}입니다."
    lines.append(t)
    k = w1["kpi"]
    lines.append(f"시장대표 ETF에는 {_p(k['market'])}이 {_dir(k['market_v'])}습니다. 레버리지는 {_p(k['lev'])}이 {_dir(k['lev_v'])}습니다.")
    k = w7["kpi"]
    lines.append(f"최근 7일로 보면 시장대표 ETF에 {_p(k['market'])}이 {_dir(k['market_v'])}고, 레버리지는 {_p(k['lev'])}이 {_dir(k['lev_v'])}습니다. 인버스는 {_p(k['inv'])}이 {_dir(k['inv_v'])}습니다.")
    if k["top_in"] != "-" and k["top_out"] != "-":
        lines.append(f"7일 동안 테마로는 {k['top_in'].replace('+', '')}이 들어왔고, {k['top_out'].replace('−', '')}이 빠졌습니다.".replace("억원이 들어왔고", "억원이 들어왔고"))
    P = w7["pressure"]
    if P["down"] or P["up"]:
        dn = ", ".join(f"{o['name']} {_p(o['amt_txt'])}" for o in P["down"][:3])
        up = ", ".join(f"{o['name']} {_p(o['amt_txt'])}" for o in P["up"][:2])
        lines.append("ETF 구성 비중으로 대략 계산하면 7일 동안 " + (f"{dn} 쪽에 매도 압력이 있었습니다. " if dn else "") + (f"매수 압력은 {up} 정도입니다." if up else ""))
    th = ", ".join(f"{t['theme']} {_p(t['amt_txt'])}" for t in w3["themes"][:2] if t["amt"] > 0)
    lines.append(f"3개월로 보면 {th}으로 돈이 가장 많이 몰렸습니다. 새로 나온 ETF는 {w3['n_new']}종입니다.")
    return lines


AGENT_DIR = os.path.join(HERE, "data", "etf_comment")


def load_comment(asof):
    """수작업(kind/etf_comment.json) > 에이전트 산출(kind/data/etf_comment/<기준일>.json) 순. 없으면 None(호출 쪽이 자동 코멘트로 대체)."""
    try:
        c = json.load(open(COMMENT_PATH, encoding="utf-8")).get(asof)
        if c:
            return dict(c, src="수작업")
    except (OSError, ValueError):
        pass
    try:
        c = json.load(open(os.path.join(AGENT_DIR, f"{asof}.json"), encoding="utf-8"))
        if c.get("lines"):
            return dict(c, src="에이전트")
    except (OSError, ValueError):
        pass
    return None


def price_of(prices, snap, sid, day):
    """설정일 종가; 없으면 직전 영업일 종가; 없으면 스냅샷(근사)"""
    p = prices.get(sid)
    if p:
        ds = [d for d in p if d <= day]
        if ds:
            return p[max(ds)], False
    s = snap.get(sid)
    return (s, True) if s else (None, True)


ADV_MIN = 3e8   # %ADV 순위에는 압력 3억원 이상만(너무 작은 값이 순위를 차지하지 않도록)


def pressure(con, etfs, topn=4):
    """순유입/유출 상위 국내 ETF의 상위10 구성종목 비중으로 종목별 매수·매도 압력(원)을 추정. 레버리지·인버스는 선물·스왑 중심이라 제외.
    %ADV = 압력 ÷ 종목 5영업일 평균 거래대금(stock_adv, 근사). cand = ADV 조회가 필요한 종목(압력 상·하위 + 3억원 이상)."""
    acc = {}
    for e in etfs:
        if e["theme"] in ("레버리지", "인버스") or e["amt"] is None:
            continue
        for r in con.execute("""SELECT t.code, t.name, t.weight FROM etf_top10 t WHERE t.security_id=? AND NOT EXISTS
                                (SELECT 1 FROM security_code c JOIN security s USING(security_id) WHERE s.sec_type='ETF' AND c.code=t.code)""", (e["sec"],)):
            a = acc.setdefault(r["code"], {"code": r["code"], "name": r["name"], "amt": 0.0, "src": {}})
            v = e["amt"] * r["weight"] / 100
            a["amt"] += v
            a["src"][e["name"]] = a["src"].get(e["name"], 0) + v
    adv = {r[0]: r[1] for r in con.execute("SELECT code, adv5 FROM stock_adv")}
    out = []
    for a in acc.values():
        top = sorted(a["src"].items(), key=lambda kv: -abs(kv[1]))[:2]
        o = {"code": a["code"], "name": a["name"], "amt": a["amt"], "amt_txt": won(a["amt"]), "src": [k for k, _ in top]}
        if a["code"] in adv and adv[a["code"]]:
            o["pct"] = a["amt"] / adv[a["code"]] * 100
            o["days"] = o["pct"] / 100   # 하루 거래대금의 몇 배(수익률과 혼동되지 않게 % 대신 일수로 표시)
            o["days_txt"] = f"{o['days']:+.2f}일".replace("-", "−")
            o["adv_txt"] = won(adv[a["code"]]).lstrip("+")
        out.append(o)
    up = sorted([o for o in out if o["amt"] > 0], key=lambda o: -o["amt"])
    dn = sorted([o for o in out if o["amt"] < 0], key=lambda o: o["amt"])
    big = [o for o in out if abs(o["amt"]) >= ADV_MIN and "pct" in o]
    return {"up": up[:topn], "down": dn[:topn],
            "up_adv": sorted([o for o in big if o["amt"] > 0], key=lambda o: -o["pct"])[:topn],
            "down_adv": sorted([o for o in big if o["amt"] < 0], key=lambda o: o["pct"])[:topn],
            "cand": up[:15] + dn[:15] + [o for o in out if abs(o["amt"]) >= ADV_MIN]}


def build(con, asof, cand=False):
    L = con.execute("SELECT max(create_date) FROM etf_unit_change WHERE report_date<=? AND create_date<=?", (asof, asof)).fetchone()[0]
    if not L:
        return None
    lo = windows(L)
    first = min(lo.values())
    prices = {}
    for r in con.execute("SELECT security_id, trade_date, close FROM etf_price"):
        prices.setdefault(r[0], {})[r[1]] = r[2]
    snap = {r[0]: r[1] for r in con.execute("SELECT security_id, close FROM etf_snapshot WHERE close IS NOT NULL")}
    tabs = {r[0]: r[1] for r in con.execute("SELECT security_id, tab_code FROM etf_snapshot WHERE tab_code IS NOT NULL")}
    meta = {r[0]: (r[1], r[2]) for r in con.execute("SELECT security_id, name, manager FROM security")}
    rows = con.execute("""SELECT security_id, create_date, reason, net_change, units_before, units_after FROM etf_unit_change
                          WHERE superseded_by IS NULL AND report_date<=? AND create_date BETWEEN ? AND ?
                          ORDER BY create_date, filing_id""", (asof, first, L)).fetchall()
    seen = {r[0]: r[1] for r in con.execute("SELECT security_id, min(create_date) FROM etf_unit_change WHERE superseded_by IS NULL GROUP BY 1")}
    t0 = (dt.date.fromisoformat(con.execute("SELECT min(create_date) FROM etf_unit_change").fetchone()[0]) + dt.timedelta(days=30)).isoformat()
    out = {"asof": asof, "latest": L, "n_managers": 8, "windows": {}}
    for key, label in WINDOWS:
        per = {}
        unpriced = approx = 0
        for r in rows:
            if r["create_date"] < lo[key]:
                continue
            sid = r["security_id"]
            e = per.setdefault(sid, {"net": 0, "amt": 0.0, "priced": True, "first_before": r["units_before"], "last_after": r["units_after"], "new": False, "days": set()})
            p, ap = price_of(prices, snap, sid, r["create_date"])
            e["net"] += r["net_change"]
            e["last_after"] = r["units_after"]
            e["last_p"] = p
            e["days"].add(r["create_date"])
            if seen[sid] >= max(lo[key], t0):  # 수집 시작 30일 이후 처음 등장 = 신규 상장 추정(상장일은 etf_prices 가 meta 에 보관)
                e["new"] = True
            if p is None:
                e["priced"] = False; unpriced += 1
            else:
                e["amt"] += r["net_change"] * p
                approx += ap
        items = []
        for sid, e in per.items():
            name, mgr = meta[sid]
            th = theme(name, tabs.get(sid))
            gap = (e["last_after"] - e["first_before"]) - e["net"]  # 공시 연결이 끊긴 구간(미관측 순증감) — 잔고 차분으로 보정해 금액에 포함(창 마지막 종가로 환산)
            amt = e["amt"] + gap * e["last_p"] if e["priced"] and e.get("last_p") else (e["amt"] if e["priced"] else None)
            items.append({"sec": sid, "name": name, "mgr": mgr, "theme": th, "net": e["net"] + gap, "obs": e["net"], "amt": amt,
                          "amt_txt": won(amt) if amt is not None else "-", "net_txt": units_txt(e["net"] + gap), "new": e["new"], "gap": gap,
                          "adj": abs(gap) > 0.2 * abs(e["net"]) and abs(gap * (e.get("last_p") or 0)) >= 1e9,
                          "cum_txt": f"{e['last_after'] / 1e4:,.0f}만좌"})
        n_excl = sum(1 for i in items if i["theme"] in EXCLUDE)
        items = [i for i in items if i["theme"] not in EXCLUDE]
        priced = [i for i in items if i["amt"] is not None]
        tot = sum(i["amt"] for i in priced)
        inflow = sorted([i for i in priced if i["amt"] > 0], key=lambda i: -i["amt"])
        outflow = sorted([i for i in priced if i["amt"] < 0], key=lambda i: i["amt"])
        th = {}
        for i in priced:
            t = th.setdefault(i["theme"], {"theme": i["theme"], "amt": 0.0, "n": 0})
            t["amt"] += i["amt"]; t["n"] += 1
        themes = sorted(th.values(), key=lambda t: -abs(t["amt"]))
        for t in themes:
            t["amt_txt"] = won(t["amt"])
        gross = sum(abs(i["obs"]) for i in items)
        gaps = sum(abs(i["gap"]) for i in items)
        new = sorted([i for i in items if i["new"]], key=lambda i: -(i["amt"] or 0))
        lev = th.get("레버리지", {}).get("amt", 0.0)
        inv = th.get("인버스", {}).get("amt", 0.0)
        mk = th.get("국내 시장대표", {}).get("amt", 0.0)
        up_t = max(themes, key=lambda t: t["amt"], default=None)
        dn_t = min(themes, key=lambda t: t["amt"], default=None)
        out["windows"][key] = {
            "label": label, "from": lo[key], "to": L, "n_etf": len(items), "n_unpriced": sum(1 for i in items if i["amt"] is None), "n_approx": approx,
            "total": tot, "total_txt": won(tot),
            "kpi": {"market": won(mk), "lev": won(lev), "inv": won(inv), "top_in": f"{up_t['theme']} {up_t['amt_txt']}" if up_t and up_t["amt"] > 0 else "-",
                    "top_out": f"{dn_t['theme']} {dn_t['amt_txt']}" if dn_t and dn_t["amt"] < 0 else "-", "market_v": mk, "lev_v": lev, "inv_v": inv,
                    "top_in_v": up_t["amt"] if up_t else 0, "top_out_v": dn_t["amt"] if dn_t else 0},
            "n_excl": n_excl, "pressure": pressure(con, inflow[:10] + outflow[:10]), "src_secs": [i["sec"] for i in inflow[:10] + outflow[:10]],
            "inflow": inflow[:TOPN], "outflow": outflow[:TOPN], "themes": themes[:8],
            "new": new[:TOPN], "n_new": len(new),
            "coverage": round(100 * (1 - gaps / gross), 1) if gross else None,
            "n_adj": sum(1 for i in items if i["adj"]),
        }
    if not cand:   # ADV 조회용 후보 목록은 etf_prices 만 쓴다(리포트 데이터에서 제외)
        for w in out["windows"].values():
            w["pressure"].pop("cand", None)
    out["comment"] = load_comment(asof)
    if not out["comment"] and out["windows"]["1d"]["inflow"] + out["windows"]["1d"]["outflow"]:
        out["comment"] = {"lines": auto_comment(out), "src": "자동"}
    return out


NUM = re.compile(r"\d[\d,]*\.?\d*")


def numbers(text):
    return {m.rstrip(".").replace(",", "") for m in NUM.findall(text)}


def check(data):
    """코멘트 속 숫자가 모두 집계 값(표시 문자열)에 있는지 대조. 날짜(YYYY-MM-DD, MM/DD)는 제외하고 라벨 숫자(1일·7일·3개월)는 허용."""
    c = data.get("comment")
    if not c:
        return None
    allowed = {"1", "7", "3", "8", "200"}
    blob = json.dumps(data["windows"], ensure_ascii=False)
    allowed |= numbers(re.sub(r"\d{4}-\d{2}-\d{2}", " ", blob))
    bad = []
    for line in c.get("lines", []):
        txt = re.sub(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}", " ", line)
        for n in numbers(txt):
            if n not in allowed:
                bad.append((n, line[:40]))
    return bad


if __name__ == "__main__":
    con = db.connect()
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    asof = a[0] if a else dt.date.today().isoformat()
    asof = con.execute("SELECT max(cal_date) FROM calendar_day WHERE is_trading=1 AND cal_date<=?", (asof,)).fetchone()[0]
    d = build(con, asof)
    if "--check" in sys.argv:
        bad = check(d)
        print("코멘트 없음" if bad is None else ("숫자 대조 통과" if not bad else f"불일치: {bad}"))
        sys.exit(1 if bad else 0)
    print(f"기준 {asof} · 최신 설정일 {d['latest']}")
    for k, w in d["windows"].items():
        print(f"\n[{w['label']}] {w['from']}~{w['to']} ETF {w['n_etf']}종(미산정 {w['n_unpriced']}) 순유입 {w['total_txt']} · 커버리지 {w['coverage']}% · 신규 {w['n_new']}")
        print("  KPI", {x: y for x, y in w["kpi"].items() if not x.endswith("_v")}, "제외", w["n_excl"])
        print("  압력", [(o["name"], o["amt_txt"]) for o in w["pressure"]["up"]], [(o["name"], o["amt_txt"]) for o in w["pressure"]["down"]])
        print("  유입", [(i["name"], i["amt_txt"], i["theme"]) for i in w["inflow"]])
        print("  유출", [(i["name"], i["amt_txt"], i["theme"]) for i in w["outflow"]])
        print("  테마", [(t["theme"], t["amt_txt"]) for t in w["themes"]])
        print("  신규", [(i["name"], i["amt_txt"], i["theme"]) for i in w["new"]])
