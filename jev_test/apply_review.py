"""사람이 채운 검토 CSV를 정답셋에 반영한다.

사용법: python jev_test/apply_review.py <채워진.csv> [원본큐.csv]
  - 인코딩(UTF-8/CP949/UTF-16)과 구분자(콤마/탭)를 자동 감지한다. 엑셀이 '텍스트(탭으로 분리)'로 저장한 파일도 읽는다.
  - 엑셀이 접수번호를 과학 표기(2.02609E+13)로 망가뜨린 경우, 원본 큐(기본 review/human_review_queue.csv)와
    행 순서로 맞춰 복구한다. 회사·공시명·날짜가 한 행이라도 다르면 중단한다.
  - '사람 판정'이 PASS / PASS_CHECK / HOLD / DROP 인 행만 읽는다.
  - 구분:  explicit = Claude 라벨과 다르거나 메모가 있는 행 → cases/labels_human.json (정답을 덮어씀)
           default  = Claude 라벨과 같고 메모도 없는 행 → cases/labels_human_default.json (덮어쓰지 않음.
                      사람이 기본값을 그대로 둔 것일 수 있어, 정책 답변과 충돌하면 정책이 우선한다)
"""
import csv
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VALID = {"PASS", "PASS_CHECK", "HOLD", "DROP"}


def read_table(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp949", "utf-16"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit("인코딩을 알 수 없습니다")
    delim = "\t" if text.split("\n", 1)[0].count("\t") > text.split("\n", 1)[0].count(",") else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=delim))


def main():
    src = sys.argv[1]
    orig_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "review", "human_review_queue.csv")
    rows = read_table(src)
    orig = read_table(orig_path)
    col = next(k for k in rows[0] if k and k.startswith("사람 판정"))
    labcol = next(k for k in orig[0] if k in ("Claude 현재 라벨", "현재 라벨"))
    by_id = {b["행ID"]: b for b in orig} if "행ID" in orig[0] else None
    broken = any(re.search(r"E\+", (r.get("접수번호") or "")) for r in rows) or by_id is not None
    if len(rows) != len(orig):
        raise SystemExit(f"행 수가 다릅니다: {len(rows)} vs 원본 {len(orig)}")
    explicit, default, skipped = {}, {}, 0
    for a, b0 in zip(rows, orig):
        b = by_id[a["행ID"].strip()] if by_id and a.get("행ID") else b0   # 행ID가 있으면 행 순서가 바뀌어도 복구된다
        if not (a["회사"] == b["회사"] and a["공시명"] == b["공시명"] and a["날짜"] == b["날짜"]):
            raise SystemExit(f"행이 원본과 어긋납니다(정렬을 바꾸셨나요?): {a['회사']} / {b['회사']}")
        rid = b["접수번호"].strip() if broken else (a["접수번호"].strip() or b["접수번호"].strip())
        v = (a.get(col) or "").strip().upper().replace("-", "_")
        memo = (a.get("사람 메모") or "").strip()
        if not v:
            continue
        if v not in VALID:
            skipped += 1
            print("무시(허용 값 아님):", rid, a["회사"], repr(v))
            continue
        rec = {"label": v, "memo": memo, "company": a["회사"], "title": a["공시명"], "claude_label": b[labcol]}
        (explicit if (v != b[labcol] or memo) else default)[rid] = rec
    for name, d in (("labels_human.json", explicit), ("labels_human_default.json", default)):
        path = os.path.join(HERE, "cases", name)
        cur = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
        cur.update(d)
        json.dump(cur, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"접수번호 복구={'예' if broken else '아니오'} | 명시적 사람 판정 {len(explicit)}건 → labels_human.json | "
          f"기본값 유지 {len(default)}건 → labels_human_default.json | 무시 {skipped}건")


if __name__ == "__main__":
    main()
