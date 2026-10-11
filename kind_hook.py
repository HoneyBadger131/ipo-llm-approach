"""run_daily.py 용 KIND 일일 작업 격리 훅 — KIND 장애·지연이 DART 메일을 막지 않도록 모든 예외를 흡수한다.
  h = kind_hook.start("2026-10-08")                 # 백그라운드로 kind/run_kind_daily.py 시작(DART 단계와 병렬)
  r = kind_hook.collect(h, deadline=1200)            # 마감까지 기다려 결과를 모은다(초과 시 종료 후 실패로 기록)
r = {ok, asof, summary_path, html_path, note, warnings}.  note 는 메일 비고 박스용 한 줄(문제 있을 때만).
테스트용: 환경변수 KIND_DAILY_CMD 로 명령 교체(예: "sleep 5", "false") — 장애 주입.
"""
import json
import os
import shlex
import signal
import subprocess
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(ROOT, ".venv", "bin", "python")


def start(asof_iso):
    try:
        cmd = shlex.split(os.environ["KIND_DAILY_CMD"]) if os.environ.get("KIND_DAILY_CMD") else [PY, "kind/run_kind_daily.py", "--asof", asof_iso]
        os.makedirs("logs", exist_ok=True)
        log = open(f"logs/kind_{asof_iso.replace('-', '')}.log", "a", encoding="utf-8")
        env = dict(os.environ)
        if not os.environ.get("KIND_DAILY_CMD"):   # 운영에서는 테스트용 환경변수가 새어 들어가지 않게 한다
            for k in ("KIND_OFFLINE", "KIND_DB", "KIND_REPORT_DIR"):
                env.pop(k, None)
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)  # 새 세션: 타임아웃 때 단계 자식까지 killpg
        return {"proc": p, "asof": asof_iso, "t0": time.time(), "log": log}
    except Exception as e:  # noqa: BLE001
        return {"proc": None, "asof": asof_iso, "t0": time.time(), "error": f"{type(e).__name__}: {e}"}


def collect(h, deadline=1200):
    r = {"ok": False, "asof": h["asof"], "summary_path": None, "html_path": None, "note": "", "warnings": []}
    try:
        if h.get("disabled"):
            return r   # 비활성: 조용히 KIND 섹션 없음
        if h.get("proc") is None:
            r["note"] = "KIND 일일 작업 시작 실패: " + h.get("error", "?")
            return r
        left = max(1, deadline - (time.time() - h["t0"]))
        try:
            rc = h["proc"].wait(timeout=left)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(h["proc"].pid, signal.SIGKILL)
            except OSError:
                h["proc"].kill()
            h["proc"].wait()
            r["note"] = f"KIND 일일 작업이 {deadline}초 안에 끝나지 않아 중단(KIND 섹션 생략)"
            return r
        p = os.path.join(os.environ.get("KIND_REPORT_DIR") or os.path.join(ROOT, "kind", "reports"), f"kind_daily_{h['asof']}.json")
        if rc != 0 or not os.path.exists(p) or os.path.getmtime(p) < h["t0"] - 1:   # 이번 실행이 쓴 결과만 인정(건너뜀·재실행 시 낡은 파일 방지)
            r["note"] = f"KIND 일일 작업 실패(rc={rc}) 또는 결과 없음(KIND 섹션 생략)"
            return r
        st = json.load(open(p, encoding="utf-8"))
        r.update(ok=bool(st.get("ok")), summary_path=p, html_path=st.get("html"), warnings=st.get("warnings", []))
        if not r["ok"]:
            r["note"] = "KIND: " + "; ".join(r["warnings"][:3])
        elif r["warnings"]:
            r["note"] = "KIND 경고 " + str(len(r["warnings"])) + "건: " + "; ".join(r["warnings"][:2])
        return r
    except Exception as e:  # noqa: BLE001
        r["note"] = f"KIND 결과 수집 오류: {type(e).__name__}: {e}"
        return r
    finally:
        try:
            h["log"].close()
        except Exception:  # noqa: BLE001
            pass
