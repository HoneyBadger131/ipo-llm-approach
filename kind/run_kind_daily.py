"""KIND 일일 작업(HANDOFF 3절 일일 루틴의 자동화): 스캔 → 체결내역 → 보충 → 상태 → 파싱 → M2 → 리포트 → 요약 JSON.
  .venv/bin/python kind/run_kind_daily.py [--asof YYYY-MM-DD] [--offline] [--budget 900]
- --asof: 기준일(없으면 오늘 이전 마지막 영업일). 반드시 ISO 형식.
- --offline: 네트워크 단계 생략, 캐시만(KIND_OFFLINE=1).  --budget: 전체 시간 상한(초). 넘기면 남은 단계를 건너뛴다.
출력: kind/reports/kind_report_<기준일>.html · kind/reports/kind_daily_<기준일>.json(요약+단계 결과+경고).
격리 설계: 각 단계는 별도 프로세스(타임아웃), 실패해도 다음 단계 진행. 방화벽 차단(KindBlocked) 감지 시 이후 온라인 단계는 건너뛴다.
재생성(rebuild_all.sh) 중(.rebuilding)이거나 다른 일일 작업이 돌고 있으면(.daily.lock) 아무것도 하지 않고 종료한다.
종가(prices_*.csv)는 주 1회 사람이 갱신 — 기준일보다 7일 넘게 오래되면 경고.
"""
import datetime as dt
import fcntl
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import db  # noqa: E402

PY = os.path.join(ROOT, ".venv", "bin", "python")
DATA = os.path.dirname(db.DB_PATH)
STEP_CAP = 420  # 단계 1개 상한(초)


def out_dir():
    return os.environ.get("KIND_REPORT_DIR") or os.path.join(HERE, "reports")


def write_status(asof, st):
    os.makedirs(out_dir(), exist_ok=True)
    p = os.path.join(out_dir(), f"kind_daily_{asof}.json")
    json.dump(st, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    return p


def summarize(con, data, asof):
    """리포트 데이터(html_report.build) → 메일용 요약."""
    def slim(x):
        return {k: x.get(k) for k in ("id", "issuer", "code", "type", "headline", "delta_txt", "pct", "mc_txt", "mc", "right", "dd", "anchor", "est", "applied")} | {"url": (x.get("link") or {}).get("url")}
    rows = data["t1"] + data["t2"]
    t0 = con.execute("SELECT tseq FROM calendar_day WHERE cal_date=?", (asof,)).fetchone()[0]
    d5, prev = (con.execute("SELECT max(cal_date) FROM calendar_day WHERE is_trading=1 AND tseq<=?", (t0 + 5,)).fetchone()[0],
                con.execute("SELECT max(cal_date) FROM calendar_day WHERE is_trading=1 AND tseq<?", (t0,)).fetchone()[0])
    win_from = (dt.date.fromisoformat(prev) + dt.timedelta(days=1)).isoformat() if prev else asof
    new_ids = {str(r[0]) for r in con.execute("""SELECT ef.event_id FROM event_filing ef JOIN filing f USING(filing_id)
                                                 WHERE ef.relation='initial' AND f.filed_date BETWEEN ? AND ?""", (win_from, asof))}
    return {
        "counts": {"t1": len(data["t1"]), "t2": len(data["t2"]), "cbw": len(data["cbw"]), "bb": len(data["bb"]), "closed": len(data["closed"])},
        "important": [slim(x) for x in sorted((x for x in data["t1"] if not x.get("applied")), key=lambda x: -abs(x.get("mc") or 0))[:8]],
        "upcoming": [slim(x) for x in sorted(rows, key=lambda x: x.get("anchor") or "9999") if x.get("anchor") and asof < x["anchor"] <= d5],
        "new": [slim(x) for x in rows if x.get("id") in new_ids],
        "window": [win_from, asof],
        "price_date": data["price_date"],
    }


def main():
    a = sys.argv[1:]
    offline = "--offline" in a
    budget = int(a[a.index("--budget") + 1]) if "--budget" in a else 900
    t0 = time.time()
    if os.path.exists(os.path.join(DATA, ".rebuilding")):
        print("rebuild_all.sh 진행 중 — 건너뜀")
        return
    if not os.path.exists(db.DB_PATH):
        asof = a[a.index("--asof") + 1] if "--asof" in a else dt.date.today().isoformat()
        write_status(asof, {"ok": False, "asof": asof, "warnings": ["KIND DB 없음 — kind/rebuild_all.sh 로 먼저 재생성 필요"], "steps": []})
        print("KIND DB 없음")
        return
    os.makedirs(DATA, exist_ok=True)
    lock = open(os.path.join(DATA, ".daily.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("다른 KIND 일일 작업 진행 중 — 건너뜀")
        return

    con = db.connect()
    if con.execute("SELECT count(*) FROM calendar_day").fetchone()[0] == 0:
        write_status(a[a.index("--asof") + 1] if "--asof" in a else dt.date.today().isoformat(), {"ok": False, "warnings": ["KIND DB 비어 있음(calendar_day 0행)"], "steps": []})
        return
    today = a[a.index("--asof") + 1] if "--asof" in a else dt.date.today().isoformat()
    asof = con.execute("SELECT max(cal_date) FROM calendar_day WHERE is_trading=1 AND cal_date<=?", (today if "--asof" in a else (dt.date.fromisoformat(today) - dt.timedelta(days=1)).isoformat(),)).fetchone()[0]
    tag = today if "--asof" in a else asof   # 결과 파일명 = 요청 기준일(훅이 찾는 이름), 내용의 asof 는 KIND 달력으로 보정한 영업일
    st = {"ok": True, "asof": asof, "requested": tag, "offline": offline, "steps": [], "warnings": []}
    blocked = {"v": False}

    def step(name, args, network=True, timeout=STEP_CAP):
        left = budget - (time.time() - t0)
        rec = {"name": name}
        if left <= 5:
            rec.update(rc=None, skipped="시간 상한")
            st["warnings"].append(f"{name}: 시간 상한({budget}초)으로 건너뜀")
        elif network and (offline or blocked["v"]):
            rec.update(rc=None, skipped="오프라인/차단")
        else:
            s = time.time()
            try:
                env = dict(os.environ, KIND_OFFLINE="1") if (offline or blocked["v"]) else dict(os.environ)  # 차단 후엔 캐시만(재생성과 같은 경로)
                r = subprocess.run([PY] + args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=min(timeout, left))
                rec.update(rc=r.returncode, secs=round(time.time() - s, 1), tail=(r.stdout + r.stderr).strip()[-300:])
                if r.returncode != 0:
                    st["warnings"].append(f"{name}: 실패 rc={r.returncode}")
                    if "KindBlocked" in r.stderr:
                        blocked["v"] = True
                        st["warnings"].append("KIND 방화벽 차단 감지 — 이후 온라인 단계 생략")
            except subprocess.TimeoutExpired:
                rec.update(rc=None, secs=round(time.time() - s, 1), skipped="타임아웃")
                st["warnings"].append(f"{name}: 타임아웃")
        st["steps"].append(rec)
        return rec

    # 1) 스캔: 마지막 성공일 다음 영업일부터 기준일까지, 하루씩(진행을 정확히 기록)
    m = con.execute("SELECT value FROM meta WHERE key='last_scan_date'").fetchone()
    last = m[0] if m else con.execute("SELECT max(filed_date) FROM filing").fetchone()[0]
    days = [r[0] for r in con.execute("SELECT cal_date FROM calendar_day WHERE is_trading=1 AND cal_date>? AND cal_date<=? ORDER BY cal_date", (last, asof))]
    for d in days:
        r = step(f"scan {d}", ["kind/scan_range.py", "--from", d, "--to", d])
        if r.get("rc") == 0:
            con.execute("INSERT INTO meta(key,value) VALUES('last_scan_date',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (d,))
            con.commit()
        else:
            break  # 이후 날짜를 건너뛰고 last_scan_date 를 올리면 구멍이 생긴다 — 다음 실행이 이어 받는다
    be = con.execute("SELECT max(day) FROM buyback_exec").fetchone()[0] or "2026-06-01"
    step("buyback_exec", ["kind/buyback_exec.py", "--from", be, "--to", asof])
    step("backfill_orphans", ["kind/backfill_orphans.py"])
    step("status_flags", ["kind/status_flags.py", "--to", asof])
    # 2) 파싱(오프라인 가능): 원장·시장조치 → M2 스레드
    step("m1_parser", ["kind/m1_parser.py"], network=False)
    step("m3_parser", ["kind/m3_parser.py", "--asof", asof], network=False)
    step("m2_rights_issue", ["kind/m2_rights_issue.py", "--asof", asof], network=True)  # replay 가 증서 일정(투자설명서)을 온디맨드로 받아 다시 쓰므로, 오프라인/차단이면 건너뛰어 이전 결과를 보존
    step("m2_cancel", ["kind/m2_cancel.py", "--asof", asof], network=False)
    step("m2_cbbw", ["kind/m2_cbbw.py", "--asof", asof], network=True)  # 오프라인/차단이면 건너뛴다(이전 결과 유지)
    step("m2_split", ["kind/m2_split.py", "--asof", asof], network=False)
    step("m2_corp_actions", ["kind/m2_corp_actions.py", "--asof", asof], network=False)

    # 3) 리포트 + 요약
    try:
        import html_report
        path, data = html_report.write_report(con, asof)
        st["html"] = path
        st["summary"] = summarize(con, data, asof)
        pd = data["price_date"]
        if not pd or (dt.date.fromisoformat(asof) - dt.date.fromisoformat(pd)).days > 7:
            st["warnings"].append(f"종가 기준일 {pd} — 기준일 {asof} 보다 7일 넘게 오래됨(주간 갱신 필요), 시총 변동 추정이 낡았을 수 있음")
    except Exception as e:  # noqa: BLE001 — 리포트 실패도 DART 쪽을 막지 않는다
        st["ok"] = False
        st["warnings"].append(f"리포트 생성 실패: {type(e).__name__}: {e}")
    st["secs"] = round(time.time() - t0, 1)
    p = write_status(tag, st)
    print(p, "ok" if st["ok"] else "FAIL", f"{st['secs']}s", f"경고 {len(st['warnings'])}건")


if __name__ == "__main__":
    main()
