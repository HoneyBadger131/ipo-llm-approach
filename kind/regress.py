"""회귀 스냅샷 — 리팩터링 전후 DB·산출물이 같은지 내용 해시로 비교한다(건수만으로는 값 변화를 못 잡는다).
  .venv/bin/python kind/regress.py snap <이름> [DB경로]     # 현재 DB(또는 지정 DB)를 kind/data/regress/<이름>.json 으로 저장
  .venv/bin/python kind/regress.py diff <이름> [<이름2>]    # 저장본 vs 현재 DB(또는 저장본 2) 비교. 다르면 종료코드 1
  .venv/bin/python kind/regress.py html <파일>              # HTML 리포트 해시(기준일 고정 비교용)
비교에서 시각 컬럼(*_at)은 제외한다(재실행마다 바뀜). 행 순서는 무시하되 id 는 포함(생성 순서가 바뀌어도 잡는다).
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

OUT = os.path.join(db.HERE, "data", "regress")
DETAIL_MAX = 5000  # 이 행 수 이하인 표는 행 문자열을 저장해 어떤 행이 달라졌는지 보여준다


# 생성 순서(autoincrement id)에 따라 달라지는 컬럼은 내용으로 환원해 비교한다(증분 실행 DB vs 재생성 DB 비교용)
DROP_COLS = {"event_date": {"event_date_id"}}


def table_rows(con, tb):
    cols = [r["name"] for r in con.execute(f"PRAGMA table_info({tb})") if not r["name"].endswith("_at") and r["name"] not in DROP_COLS.get(tb, ())]
    out = []
    for r in con.execute(f"SELECT {','.join(cols)}{', event_date_id AS _id' if tb == 'event_date' else ''} FROM {tb}"):
        v = [r[c] for c in cols]
        if tb == "event_date":  # superseded_by 는 id 대신 '없음/자기/후속'
            i = cols.index("superseded_by")
            v[i] = None if r["superseded_by"] is None else ("SELF" if r["superseded_by"] == r["_id"] else "NEXT")
        elif tb == "meta" and r[cols[0]].endswith("_built_at"):
            continue
        out.append(json.dumps(v, ensure_ascii=False, default=str))
    return sorted(out)


def snapshot(dbpath=db.DB_PATH):
    con = db.connect(dbpath)
    snap = {"tables": {}}
    for (tb,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        rows = table_rows(con, tb)
        t = {"n": len(rows), "sha": hashlib.sha256("\n".join(rows).encode()).hexdigest()[:16]}
        if len(rows) <= DETAIL_MAX:
            t["rows"] = rows
        snap["tables"][tb] = t
    snap["fk_violations"] = len(con.execute("PRAGMA foreign_key_check").fetchall())
    snap["integrity"] = con.execute("PRAGMA integrity_check").fetchone()[0]
    return snap


def compare(a, b, la, lb):
    bad = 0
    for tb in sorted(set(a["tables"]) | set(b["tables"])):
        ta, tb_ = a["tables"].get(tb), b["tables"].get(tb)
        if ta is None or tb_ is None:
            print(f"✗ {tb}: 한쪽에만 존재 ({la}={bool(ta)}, {lb}={bool(tb_)})")
            bad += 1
        elif ta["sha"] != tb_["sha"]:
            bad += 1
            print(f"✗ {tb}: {ta['n']} → {tb_['n']}행, 내용 다름")
            if "rows" in ta and "rows" in tb_:
                sa, sb = set(ta["rows"]), set(tb_["rows"])
                for lab, ss in ((f"{la} 에만", sa - sb), (f"{lb} 에만", sb - sa)):
                    for r in sorted(ss)[:5]:
                        print(f"    {lab}: {r[:220]}")
                    if len(ss) > 5:
                        print(f"    … {lab} {len(ss) - 5}행 더")
        else:
            print(f"✓ {tb}: {ta['n']}행")
    for k in ("fk_violations", "integrity"):
        if a[k] != b[k]:
            bad += 1
            print(f"✗ {k}: {a[k]} → {b[k]}")
    print("\n회귀 OK — 모든 표 동일" if not bad else f"\n불일치 {bad}건")
    return bad


def path(name):
    return os.path.join(OUT, name + ".json")


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("snap", "diff", "html"):
        print(__doc__)
        sys.exit(2)
    cmd, name = sys.argv[1], sys.argv[2]
    if cmd == "html":
        import re
        txt = re.sub(r'"generated": "[^"]*"', '"generated": ""', open(name, encoding="utf-8").read())  # 생성 시각 제외
        print(hashlib.sha256(txt.encode()).hexdigest()[:16], name)
        return
    os.makedirs(OUT, exist_ok=True)
    if cmd == "snap":
        s = snapshot(sys.argv[3]) if len(sys.argv) > 3 else snapshot()
        json.dump(s, open(path(name), "w"), ensure_ascii=False)
        print(f"저장: {path(name)}  ({len(s['tables'])}개 표, 총 {sum(t['n'] for t in s['tables'].values()):,}행)")
        return
    a = json.load(open(path(name)))
    if len(sys.argv) > 3:
        b, lb = json.load(open(path(sys.argv[3]))), sys.argv[3]
    else:
        b, lb = snapshot(), "현재"
    sys.exit(1 if compare(a, b, name, lb) else 0)


if __name__ == "__main__":
    main()
