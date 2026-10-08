"""Jev 실행기: 정답셋의 각 케이스에 질문 묶음을 한 요청으로 보내고 원응답을 저장한다.

사용법 (레포 루트에서, 환경 변수 TYPE_SAFE_AI_KEY 필요):
  python jev_test/run_jev.py <실험명> <설정,...> [--kinds judged,correction,rule_exclude] [--ver v0|v1] [--periods w0907,w0901,w0930]
  설정 = <입력>-<언어>  예: T-ko  TD-ko  T-en  TD-en     (T=제목만, TD=제목+본문 요약)
산출물: jev_test/runs/<실험명>/raw_<설정>.jsonl  (한 줄 = 케이스 1건의 응답; 이미 있으면 건너뜀)
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import build_state, call_jev, load_cases  # noqa: E402
from questions import QUESTIONS  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def run_config(exp, cfg, cases, key, ver):
    mode, lang = cfg.split("-")
    out = os.path.join(HERE, "runs", exp, f"raw_{cfg}.jsonl")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    done = set()
    if os.path.exists(out):
        done = {json.loads(l)["rcept_no"] for l in open(out, encoding="utf-8") if l.strip()}
    todo = [c for c in cases if c["rcept_no"] not in done]
    qs = QUESTIONS[ver][lang]
    # 정정 공시가 아니면 material_change는 항상 "아니오"라 보내지 않는다
    def one(c):
        q = {k: v for k, v in qs.items() if k != "material_change" or c["is_correction"]}
        res = call_jev(build_state(c, mode, ver), q, key)
        return dict(rcept_no=c["rcept_no"], cfg=cfg, resp=res)
    with ThreadPoolExecutor(max_workers=6) as ex, open(out, "a", encoding="utf-8") as f:
        for r in ex.map(one, todo):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
    errs = sum(1 for l in open(out, encoding="utf-8") if '"error"' in l)
    print(f"{cfg}: {len(todo)}건 실행 (누적 {len(done) + len(todo)}, 오류 {errs})", flush=True)


def main():
    exp, cfgs = sys.argv[1], sys.argv[2].split(",")
    kinds = {"judged", "correction", "rule_exclude"}
    if "--kinds" in sys.argv:
        kinds = set(sys.argv[sys.argv.index("--kinds") + 1].split(","))
    ver = sys.argv[sys.argv.index("--ver") + 1] if "--ver" in sys.argv else "v0"
    key = os.environ["TYPE_SAFE_AI_KEY"]
    periods = set(sys.argv[sys.argv.index("--periods") + 1].split(",")) if "--periods" in sys.argv else None
    cases = [c for c in load_cases() if c["kind"] in kinds and c["label"] and (periods is None or c["period"] in periods)]
    for cfg in cfgs:
        run_config(exp, cfg, cases, key, ver)


if __name__ == "__main__":
    main()
