"""하루치 파이프라인 보조 도구 (준비는 dart_prep_day.py, 판단은 대화에서).

  python dart_day_pipeline.py stage <YYYYMMDD> [배치크기=3]   judgments.json -> 에이전트 입력 준비 + agent_tasks.json 생성
  python dart_day_pipeline.py brief <YYYYMMDD>   통합 브리프 생성 + 점검(1쪽, 금지 문구, 기준일 이후 뉴스)

stage
  - proceed=true 공시와 같은 회사의 같은 날 다른 공시(관련 후보) 본문을 bodies/<날짜>/ → trial_case/<날짜>/ 로 복사
  - 회사 단위 작업 정의를 trial_case/<날짜>/agent_tasks.json 에 저장 (에이전트는 이 파일에서 자기 항목을 읽는다)
  - judgments.json 항목에 선택 필드를 둘 수 있다: "agent_note"(에이전트에게 줄 메모), "related_with"(다른 회사 관련 공시 접수번호 리스트)
brief
  - summary_meta.json 의 funnel을 prep.json 에서 갱신(기존 top_order가 있으면 유지), render_summary.js 실행, 점검 결과 출력
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict


def _date(day):
    return f"{day[:4]}-{day[4:6]}-{day[6:]}"


def stage(day, batch=3):
    d = f"trial_case/{day}"
    judg = json.load(open(f"{d}/judgments.json", encoding="utf-8"))
    by_co = defaultdict(list)
    for j in judg:
        by_co[j["stock_code"]].append(j)

    def body(j):
        name = f"{j['stock_code']}_{j['rcept_no']}.txt"
        src, dst = f"bodies/{day}/{name}", f"{d}/{name}"
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy(src, dst)
        return dst if os.path.exists(dst) else None

    tasks = []
    for code, items in by_co.items():
        passed = [j for j in items if j["proceed"]]
        if not passed:
            continue
        others = [j for j in items if not j["proceed"]]
        tasks.append(dict(
            stock_code=code, corp_name=passed[0]["corp_name"], base_date=_date(day),
            filings=[dict(rcept_no=j["rcept_no"], report_nm=j["report_nm"], tag=j["tag"], reason=j["reason"],
                          body=body(j), note=j.get("agent_note", ""), related_with=j.get("related_with", []),
                          output=f"{d}/reports/{code}_{j['rcept_no']}_v2.json") for j in passed],
            same_day_other_filings=[dict(rcept_no=j["rcept_no"], report_nm=j["report_nm"], reason=j["reason"],
                                         body=body(j)) for j in others]))
    os.makedirs(f"{d}/reports", exist_ok=True)
    json.dump(tasks, open(f"{d}/agent_tasks.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    missing = [f["rcept_no"] for t in tasks for f in t["filings"] if not f["body"]]
    print(f"{day}: 통과 {sum(len(t['filings']) for t in tasks)}건 / 회사 {len(tasks)}개 -> {d}/agent_tasks.json"
          + (f" | 본문 누락: {missing}" if missing else ""))
    # 에이전트 1개당 공시 batch건 이내로 회사를 묶는다(고정 컨텍스트 약 4만 토큰을 나눠 쓰기 위해). 한 회사는 쪼개지 않는다.
    groups, cur, w = [], [], 0
    for t in tasks:
        n = len(t["filings"])
        if cur and w + n > batch:
            groups.append(cur)
            cur, w = [], 0
        cur.append(t)
        w += n
    if cur:
        groups.append(cur)
    print(f"\n에이전트 프롬프트(에이전트 {len(groups)}개, 공시 {batch}건 이내로 묶음 — 6개씩 병렬):")
    for g in groups:
        names = ", ".join(f"{t['stock_code']} {t['corp_name']}" for t in g)
        codes = ", ".join(t["stock_code"] for t in g)
        print(f"[{names}] 레포 /home/user/ipo-llm-approach 에서 공시 대시보드를 만든다. "
              f"먼저 report_v2/AGENT_SPEC.md 를 읽고 그대로 따른다. 작업 정의는 {d}/agent_tasks.json 의 "
              f"stock_code={codes} 항목(기준일 {g[0]['base_date']}). "
              + ("종목이 여럿이면 종목별로 차례로(MCP·검색은 종목마다) 처리한다." if len(g) > 1 else ""))


def brief(day):
    d = f"trial_case/{day}"
    date = _date(day)
    prep = json.load(open(f"{d}/prep.json", encoding="utf-8"))
    reports = sorted(glob.glob(f"{d}/reports/*_v2.json"))
    meta_path = f"{d}/summary_meta.json"
    meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}
    meta["funnel"] = [["전체 공시", prep["total"]], ["리스트 종목 공시", prep["watchlist_filings"]],
                      ["판단 대상", len(prep["review"])], ["심화 분석", len(reports)]]
    json.dump(meta, open(meta_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    out = subprocess.run(["node", "report_v2/render_summary.js", f"{d}/reports", date, meta_path],
                         capture_output=True, text=True)
    print(out.stdout.strip() or out.stderr.strip())

    pages = lambda p: re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", p], capture_output=True, text=True).stdout)
    bad = re.compile(r"(?<!세금)계산|도구 이력|시장 추정|공시가 아님|역산")
    problems, no_news, no_cons = [], [], []
    for f in reports:
        j = json.load(open(f, encoding="utf-8"))
        pg = pages(f.replace(".json", ".pdf"))
        if not pg or pg.group(1) != "1":
            problems.append(f"{j['corp_name']} {j['rcept_no']}: PDF {pg.group(1) if pg else '없음'}쪽")
        late = [n["date"] for n in j["news"] if n["date"] > date]
        if late:
            problems.append(f"{j['corp_name']} {j['rcept_no']}: 기준일 이후 뉴스 {late}")
        if bad.search(open(f, encoding="utf-8").read()):
            problems.append(f"{j['corp_name']} {j['rcept_no']}: 금지 문구")
        for k in ("importance", "brief"):
            if not j.get(k):
                problems.append(f"{j['corp_name']} {j['rcept_no']}: {k} 없음")
        if not j["news"]:
            no_news.append(j["corp_name"])
        if j.get("report_version") == 3:
            if j.get("financials") or j.get("valuation") or j.get("consensus"):
                problems.append(f"{j['corp_name']} {j['rcept_no']}: v3인데 재무/가치평가/컨센서스 포함")
        elif not j.get("consensus"):
            no_cons.append(j["corp_name"])
    sp = pages(f"trial_case/{day}/summary_{date}.pdf")
    print(f"통합 브리프 {sp.group(1) if sp else '?'}쪽 / 대시보드 {len(reports)}개")
    print("문제:", problems or "없음")
    print("뉴스 없음:", no_news or "없음")
    if no_cons:
        print("컨센서스 없음(v2):", no_cons)


if __name__ == "__main__":
    cmd, day = sys.argv[1], sys.argv[2]
    if cmd == "stage":
        stage(day, int(sys.argv[3]) if len(sys.argv) > 3 else 3)
    else:
        brief(day)
