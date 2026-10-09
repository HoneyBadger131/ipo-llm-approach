"""영업일 새벽 무인 실행: 직전 영업일 공시 → 분류 → 심화 분석 → 브리프·번들 → 메일.

사용법 (레포 루트, launchd가 호출):
  .venv/bin/python run_daily.py                   # 오늘이 영업일이면 직전 영업일 기준으로 실행
  .venv/bin/python run_daily.py --date 20261008   # 기준일 지정(영업일 판정 건너뜀)
  .venv/bin/python run_daily.py --no-send         # 메일만 건너뜀(로그에 사유 기록)
  .venv/bin/python run_daily.py --no-agents       # 스모크: 에이전트 생략(기존 reports 사용)
  .venv/bin/python run_daily.py --force           # 이미 발송한 날도 다시 실행

종료 규칙: 휴장일·통과 공시 0건 → 조용히 종료(메일 없음). 실패 → 알림 메일 + macOS 알림.
재시도: DART 수집 10분×최대 6회, 분류 60초×3회, 에이전트(회사 단위) 1회 재실행, 메일 60초×3회.
상한: 에이전트 투입 공시 최대 30건(분류 라벨 PASS > PASS_CHECK > HOLD, 같은 라벨은 noul 점수 내림차순).
"""
import datetime as dt
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
import dart_calendar as cal  # noqa: E402

PY = os.path.join(ROOT, ".venv", "bin", "python")
CAP = 30                 # 하드캡: 에이전트에 넘기는 공시 수
BATCH = 3                # 에이전트 1개당 공시 수(회사는 쪼개지 않음)
PARALLEL = 4             # 동시 에이전트 수
AGENT_TIMEOUT = 25 * 60  # 에이전트 1개 제한 시간(초)
DART_RETRIES, DART_WAIT = 6, 600
LABEL_RANK = {"PASS": 0, "PASS_CHECK": 1, "HOLD": 2}
ALLOWED = ("Read Write Edit WebSearch WebFetch ToolSearch mcp__claude_ai_OpenProxyMCP "
           "Bash(node *) Bash(.venv/bin/python *) Bash(python3 *) Bash(ls *) Bash(cat *) Bash(mkdir *) Bash(pdfinfo *) Bash(pdftoppm *)")

LOG = None


def log(msg):
    line = f"{dt.datetime.now():%H:%M:%S} {msg}"
    print(line, flush=True)
    if LOG:
        LOG.write(line + "\n")
        LOG.flush()


def sh(cmd, env=None, timeout=None, stdin=None):
    """명령 실행. (returncode, 출력) 반환. 출력은 로그에도 남긴다."""
    e = {**os.environ, **(env or {})}
    e["PATH"] = f"{ROOT}/.venv/bin:" + e.get("PATH", "")
    r = subprocess.run(cmd, cwd=ROOT, env=e, capture_output=True, text=True, timeout=timeout, input=stdin)
    out = (r.stdout or "") + (r.stderr or "")
    if LOG:
        LOG.write(f"$ {' '.join(cmd)[:200]}\n{out[-3000:]}\n")
        LOG.flush()
    return r.returncode, out


def load_env():
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def notify_mac(title, text):
    subprocess.run(["osascript", "-e", f'display notification "{text}" with title "{title}"'], capture_output=True)


def fail(day, why):
    log(f"실패: {why}")
    notify_mac("공시 리포트 실패", f"{day}: {why}"[:120])
    if "--no-send" not in sys.argv:
        sh([PY, "send_report.py", "--alert", f"[AI Agent 공시 브리핑 실패] {day}", f"{why}\n\n로그: logs/{day}.log", "--send"])
    sys.exit(1)


# ---------- 단계 ----------
def prep_with_retry(day):
    """dart_prep_day 실행 후 본문이 비었으면(점검 등) 10분 간격 재시도."""
    for n in range(1, DART_RETRIES + 1):
        rc, out = sh([PY, "dart_prep_day.py", day], timeout=1800)
        prep_p = f"trial_case/{day}/prep.json"
        ok = rc == 0 and os.path.exists(prep_p)
        if ok:
            prep = json.load(open(prep_p, encoding="utf-8"))
            need = [r for r in prep["review"] + prep.get("separate", [])]
            empty = [r for r in need if not os.path.exists(f"bodies/{day}/{r['stock_code']}_{r['rcept_no']}.txt")
                     or os.path.getsize(f"bodies/{day}/{r['stock_code']}_{r['rcept_no']}.txt") == 0]
            ok = not empty
            if not ok:
                log(f"prep {n}/{DART_RETRIES}: 본문 누락 {len(empty)}건(DART 점검 가능성)")
        else:
            log(f"prep {n}/{DART_RETRIES}: 실패 rc={rc}")
        if ok:
            return json.load(open(prep_p, encoding="utf-8"))
        if n < DART_RETRIES:
            time.sleep(DART_WAIT)
    fail(day, f"DART 수집 {DART_RETRIES}회 실패(원문 API 점검 등)")


def triage_with_retry(day):
    for n in range(1, 4):
        rc, out = sh([PY, "jev_test/triage_day.py", day, "--write-judgments"], timeout=1800)
        if rc == 0 and os.path.exists(f"trial_case/{day}/judgments.json"):
            return
        log(f"분류 {n}/3 실패 rc={rc}")
        time.sleep(60)
    fail(day, "Jev 분류 3회 실패")


def apply_cap(day):
    """agent_tasks.json 을 CAP 건으로 줄인다. 반환: (남긴 건수, 제외 목록)."""
    tp = f"trial_case/{day}/agent_tasks.json"
    tasks = json.load(open(tp, encoding="utf-8"))
    tri = {t["rcept_no"]: t for t in json.load(open(f"trial_case/{day}/triage.json", encoding="utf-8"))}

    def key(f):
        t = tri.get(f["rcept_no"], {})
        return (LABEL_RANK.get(t.get("label"), 3), -(t.get("noul") or 0))
    flat = sorted(((f, t) for t in tasks for f in t["filings"]), key=lambda x: key(x[0]))
    keep = {f["rcept_no"] for f, _ in flat[:CAP]}
    dropped = [f"{t['corp_name']} {f['report_nm']}" for f, t in flat[CAP:]]
    for t in tasks:
        t["filings"] = [f for f in t["filings"] if f["rcept_no"] in keep]
    tasks = [t for t in tasks if t["filings"]]
    json.dump(tasks, open(tp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return len(keep), dropped


def groups_of(tasks):
    groups, cur, w = [], [], 0
    for t in tasks:
        n = len(t["filings"])
        if cur and w + n > BATCH:
            groups.append(cur)
            cur, w = [], 0
        cur.append(t)
        w += n
    if cur:
        groups.append(cur)
    return groups


def run_agent(day, g):
    names = ", ".join(f"{t['stock_code']} {t['corp_name']}" for t in g)
    codes = ", ".join(t["stock_code"] for t in g)
    prompt = (f"[{names}] 레포 {ROOT} 에서 공시 대시보드를 만든다. 먼저 report_v2/AGENT_SPEC.md 를 읽고 그대로 따른다. "
              f"작업 정의는 trial_case/{day}/agent_tasks.json 의 stock_code={codes} 항목(기준일 {g[0]['base_date']}). "
              + ("종목이 여럿이면 종목별로 차례로(MCP·검색은 종목마다) 처리한다. " if len(g) > 1 else "")
              + "git 금지, .env 값 출력 금지, 최종 응답은 10줄 이내.")
    try:
        rc, out = sh(["claude", "-p", "--model", "sonnet", "--permission-mode", "acceptEdits",
                      "--allowedTools", ALLOWED], timeout=AGENT_TIMEOUT, stdin=prompt)
        log(f"에이전트 종료 rc={rc}: {codes}")
    except subprocess.TimeoutExpired:
        log(f"에이전트 시간 초과: {codes}")


def missing_outputs(tasks):
    return [t for t in tasks if any(not os.path.exists(f["output"].replace(".json", ".pdf")) for f in t["filings"])]


def main():
    global LOG
    load_env()
    a = sys.argv[1:]
    today = dt.date.today()
    if "--date" in a:
        base = dt.datetime.strptime(a[a.index("--date") + 1], "%Y%m%d").date()
    else:
        if not cal.is_business(today):
            print(f"{today} 는 영업일이 아니라 종료")
            return
        base = cal.prev_business(today)
    day, date = base.strftime("%Y%m%d"), base.isoformat()
    os.makedirs("logs", exist_ok=True)
    os.makedirs("state", exist_ok=True)
    LOG = open(f"logs/{day}.log", "a", encoding="utf-8")
    sent_mark = f"state/sent_{day}"
    if os.path.exists(sent_mark) and "--force" not in a:
        log(f"{day} 이미 발송함 — 종료(--force 로 재실행)")
        return
    log(f"=== 시작: 기준일 {date} ===")
    t0 = time.time()

    prep = prep_with_retry(day)
    log(f"prep 완료: 전체 {prep['total']} / 판단 대상 {len(prep['review'])}")
    triage_with_retry(day)
    judg = json.load(open(f"trial_case/{day}/judgments.json", encoding="utf-8"))
    passed = [j for j in judg if j["proceed"]]
    if not passed:
        log("통과 공시 0건 — 메일 없이 종료")
        return
    rc, out = sh([PY, "dart_day_pipeline.py", "stage", day, str(BATCH)])
    if rc != 0:
        fail(day, "stage 실패")
    kept, dropped = apply_cap(day)
    tasks = json.load(open(f"trial_case/{day}/agent_tasks.json", encoding="utf-8"))
    log(f"통과 {len(passed)}건 → 투입 {kept}건 / 회사 {len(tasks)}개 (상한 제외 {len(dropped)}건)")

    # 심화 분석(에이전트) — 병렬 실행 후, 결과가 빠진 회사만 1회 재실행
    if "--no-agents" not in a:   # 스모크 테스트용: 기존 reports 로 이후 단계만 확인
        with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
            list(ex.map(lambda g: run_agent(day, g), groups_of(tasks)))
    retry = [] if "--no-agents" in a else missing_outputs(tasks)
    if retry:
        log(f"결과 누락 {len(retry)}개 회사 재실행: {[t['corp_name'] for t in retry]}")
        with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
            list(ex.map(lambda g: run_agent(day, g), groups_of(retry)))
    failed = [t["corp_name"] for t in missing_outputs(tasks)]
    done = sum(1 for t in tasks for f in t["filings"] if os.path.exists(f["output"].replace(".json", ".pdf")))
    if done == 0:
        fail(day, "에이전트 결과 0건")

    rc, out = sh([PY, "dart_day_pipeline.py", "brief", day])
    log("brief: " + " / ".join(l for l in out.strip().splitlines()[-3:]))
    rc, out = sh(["node", "report_v2/render_bundle.js", day])
    if rc != 0 or not os.path.exists(f"trial_case/{day}/bundle_{date}.pdf"):
        fail(day, "번들 생성 실패")

    notes = []
    if dropped:
        notes.append(f"비용 상한({CAP}건)으로 분석 제외 {len(dropped)}건: " + ", ".join(dropped[:8]) + (" 등" if len(dropped) > 8 else ""))
    if failed:
        notes.append("분석 실패(누락): " + ", ".join(failed))
    if "--no-send" in a:
        log("--no-send: 메일 생략")
        return
    for n in range(1, 4):
        cmd = [PY, "send_report.py", f"trial_case/{day}", date, "--send"] + (["--note", " / ".join(notes)] if notes else [])
        rc, out = sh(cmd)
        if rc == 0:
            open(sent_mark, "w").write(dt.datetime.now().isoformat())
            log(f"발송 완료 ({(time.time() - t0) / 60:.1f}분 소요)")
            return
        log(f"메일 {n}/3 실패: {out.strip()[-200:]}")
        time.sleep(60)
    notify_mac("공시 리포트", f"{day} 메일 발송 3회 실패 — trial_case/{day}/bundle_{date}.html 확인")
    log("메일 발송 최종 실패(알림 메일도 같은 SMTP라 macOS 알림만 전송)")
    sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # 예기치 못한 오류도 알림
        import traceback
        if LOG:
            LOG.write(traceback.format_exc())
        notify_mac("공시 리포트 오류", str(e)[:100])
        raise
