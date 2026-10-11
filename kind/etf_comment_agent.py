"""ETF 흐름 코멘트를 에이전트(claude -p)로 작성 → kind/data/etf_comment/<기준일>.json. 실패하면 아무것도 쓰지 않는다(리포트는 자동 코멘트로 대체).

  .venv/bin/python kind/etf_comment_agent.py --asof 2026-10-08 [--model sonnet] [--force]
원칙: 집계 JSON 의 수치만 인용(생성 뒤 etf_flow.check 로 대조), 시황 애널리스트/운용역 말투로 간결하게, 금지 표현 검사.
토큰 사용량은 같은 폴더의 <기준일>.usage.json 에 남긴다.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import etf_flow

BANNED = re.compile(r"—|–|…|나뉜다|선다|갈린다|뚜렷|시사|두드러|주목할|양상|국면|견인")
PROMPT = """너는 한국 주식시장 시황 애널리스트(운용역)다. 아래 JSON 은 국내 ETF 설정·환매 집계다(채권·해외 제외). 이걸 읽고 사내 메일에 들어갈 시장 코멘트를 쓴다.

규칙
- 5~6줄. 한 줄은 문장 1~2개. 쉬운 말, 간결한 뉴스·시황 문체(합니다, 했습니다, 보입니다).
- 순서: 오늘(1일) 한 줄, 시장대표와 레버리지·인버스로 본 투자 심리, 7일 흐름과 테마(반도체, 원자력·SMR, 커버드콜 등 눈에 띄는 것), 구성종목 매수·매도 압력(%가 아니라 '하루 거래대금 대비 일수'로 표시된 값 포함 가능), 3개월 흐름과 신규 ETF.
- 숫자는 JSON 에 적힌 표기 그대로만 쓴다. 계산해서 새 숫자를 만들지 않는다. 원인을 단정하지 말고 '~로 보입니다' 정도로 해석한다.
- 쓰지 않는 표현: 줄표(—, –), 말줄임표, 문어체 수사('나뉜다', '선다', '갈린다', '뚜렷', '시사', '두드러', '주목할', '양상', '국면', '견인'), 영어 약어 남발, 이모지.
- 투자 권유는 하지 않는다.
- 출력은 JSON 한 개만: {"lines": ["...", "..."]}. 설명이나 코드블록 금지. 도구는 쓰지 않는다.

JSON
"""


def compact(d):
    def etf(i):
        return {"name": i["name"], "theme": i["theme"], "amt": i["amt_txt"]}

    def st(o):
        r = {"name": o["name"], "amt": o["amt_txt"]}
        if "days_txt" in o:
            r["days_of_volume"] = o["days_txt"]
        return r
    out = {"asof": d["asof"], "latest": d["latest"], "windows": {}}
    for k, w in d["windows"].items():
        P = w["pressure"]
        x = {"label": w["label"], "from": w["from"], "to": w["to"], "total": w["total_txt"], "n_etf": w["n_etf"],
             "kpi": {a: b for a, b in w["kpi"].items() if not a.endswith("_v")},
             "inflow": [etf(i) for i in w["inflow"]], "outflow": [etf(i) for i in w["outflow"]],
             "themes": [{"theme": t["theme"], "amt": t["amt_txt"]} for t in w["themes"][:6]],
             "new_etf_count": w["n_new"], "new_etf": [etf(i) for i in w["new"][:3]],
             "buy_pressure": [st(o) for o in P["up"]], "sell_pressure": [st(o) for o in P["down"]]}
        if k != "3m":
            x["buy_vs_volume"] = [st(o) for o in P["up_adv"]]
            x["sell_vs_volume"] = [st(o) for o in P["down_adv"]]
        out["windows"][k] = x
    return out


def ask(prompt, model):
    r = subprocess.run(["claude", "-p", "--model", model, "--output-format", "json"], input=prompt, capture_output=True, text=True, timeout=240)
    if r.returncode != 0:
        raise RuntimeError(f"claude rc={r.returncode}: {(r.stderr or r.stdout)[-200:]}")
    j = json.loads(r.stdout)
    return j.get("result", ""), {k: j.get(k) for k in ("usage", "total_cost_usd", "duration_ms", "num_turns")}


def parse(text):
    m = re.search(r"\{.*\}", text, re.S)
    lines = json.loads(m.group(0))["lines"]
    if not (3 <= len(lines) <= 8) or not all(isinstance(x, str) and x.strip() for x in lines):
        raise ValueError("줄 수/형식")
    return [x.strip() for x in lines]


def main():
    a = sys.argv[1:]
    asof = a[a.index("--asof") + 1]
    model = a[a.index("--model") + 1] if "--model" in a else "sonnet"
    os.makedirs(etf_flow.AGENT_DIR, exist_ok=True)
    path = os.path.join(etf_flow.AGENT_DIR, f"{asof}.json")
    if os.path.exists(path) and "--force" not in a:
        print("이미 있음", path)
        return
    con = db.connect()
    d = etf_flow.build(con, asof)
    if not d:
        print("ETF 데이터 없음")
        return
    base = PROMPT + json.dumps(compact(d), ensure_ascii=False, separators=(",", ":"))
    note, usage_all = "", []
    for attempt in (1, 2):
        text, usage = ask(base + note, model)
        usage_all.append(usage)
        try:
            lines = parse(text)
        except Exception as e:  # noqa: BLE001
            note = f"\n\n(이전 출력이 형식 오류: {e}. JSON 한 개만 출력.)"
            continue
        probe = dict(d, comment={"lines": lines})
        bad = etf_flow.check(probe)
        ban = [m.group(0) for x in lines for m in BANNED.finditer(x)]
        if bad or ban:
            note = f"\n\n(이전 출력 문제: 근거 없는 숫자 {bad[:3]}, 금지 표현 {ban[:4]}. 고쳐서 다시 출력.)"
            print(f"시도 {attempt} 거부:", bad[:3], ban[:4])
            continue
        json.dump({"asof": asof, "model": model, "lines": lines, "at": dt.datetime.now().isoformat(timespec="seconds")}, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump(usage_all, open(os.path.join(etf_flow.AGENT_DIR, f"{asof}.usage.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("작성", path, f"시도 {attempt}회")
        return
    print("에이전트 코멘트 실패 — 자동 코멘트 사용")
    sys.exit(1)


if __name__ == "__main__":
    main()
