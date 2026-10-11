"""KIND 축 공용 함수 — 달력 연산·이벤트 슬롯 관리·본문 텍스트·공시 토큰 유틸. import 시 부작용 없음."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import kind_client as kc


def dday(con, asof, d):
    """기준일 대비 영업일 D-day 표기. 휴장일은 '*'."""
    a = con.execute("SELECT tseq FROM calendar_day WHERE cal_date=?", (asof,)).fetchone()[0]
    b = con.execute("SELECT tseq FROM calendar_day WHERE cal_date=?", (d,)).fetchone()[0]
    n = b - a
    nt = con.execute("SELECT is_trading FROM calendar_day WHERE cal_date=?", (d,)).fetchone()[0]
    if d == asof:
        return "D-day"
    return (f"D-{n}" if n > 0 else (f"D+{-n}" if n < 0 else "D-day")) + ("" if nt else "*")


# ───────────── 달력 ─────────────
def cal(con, d, col):
    r = con.execute(f"SELECT {col} FROM calendar_day WHERE cal_date=?", (d,)).fetchone()
    return r[0] if r else None


def ex_from_record(con, rec):
    """권리락일 = (T+2 결제 기준) 신주배정기준일 직전 영업일. 기준일이 휴장이면 직전 영업일 L 의 직전 영업일."""
    L = rec if cal(con, rec, "is_trading") else cal(con, rec, "prev_trading_date")
    return cal(con, L, "prev_trading_date")


def tdiff(con, a, b):
    """영업일 수 차 (b - a). 비영업일은 직전 영업일 번호로 본다."""
    return cal(con, b, "tseq") - cal(con, a, "tseq")


# ───────────── 이벤트 슬롯 ─────────────
def set_slot(con, eid, role, d, est, src, cond=None):
    cur = con.execute("SELECT * FROM event_date WHERE event_id=? AND role=? AND superseded_by IS NULL", (eid, role)).fetchone()
    if d is None:
        if cur:  # 철회: 자기 자신으로 supersede
            con.execute("UPDATE event_date SET superseded_by=event_date_id WHERE event_date_id=?", (cur["event_date_id"],))
        return
    if cur and cur["the_date"] == d and cur["is_estimated"] == est and cur["condition_note"] == cond:
        return
    if con.execute("SELECT 1 FROM calendar_day WHERE cal_date=?", (d,)).fetchone() is None:
        print(f"  ⚠ 달력 범위 밖/잘못된 날짜 슬롯 생략: event {eid} {role} {d}", file=sys.stderr)  # 예: 만기 2040년 이후, 날짜 파싱 오류
        return
    new = con.execute("INSERT INTO event_date(event_id,role,the_date,is_estimated,condition_note,source_filing_id) VALUES (?,?,?,?,?,?)",
                      (eid, role + "~", d, est, cond, src)).lastrowid
    if cur:
        con.execute("UPDATE event_date SET superseded_by=? WHERE event_date_id=?", (new, cur["event_date_id"]))
    con.execute("UPDATE event_date SET role=? WHERE event_date_id=?", (role, new))


def prune(con, prefix, keep_keys):
    """이번 실행에서 구성되지 않은(병합·삭제된) 스레드를 정리한다. 스레드 키는 접두 + 최초 결정일이라 규칙 변경 시 옛 키가 남을 수 있다."""
    for (eid, k) in con.execute("SELECT event_id, thread_key FROM event WHERE thread_key LIKE ?", (prefix + "%",)).fetchall():
        if k not in keep_keys:
            for tb in ("index_share_adj", "event_date", "event_filing"):
                con.execute(f"DELETE FROM {tb} WHERE event_id=?", (eid,))
            con.execute("UPDATE share_ledger SET event_id=NULL WHERE event_id=?", (eid,))
            con.execute("DELETE FROM event WHERE event_id=?", (eid,))


# ───────────── 본문·토큰 ─────────────
def text_of(f):
    return kc._html_to_text(open(os.path.join(db.HERE, f["body_path"]), encoding="utf-8").read())


def kdate(s):
    m = re.search(r"(\d{4})\D{0,2}(\d{1,2})\D{0,2}(\d{1,2})", s or "")
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def after(vals, label, n=1):
    for i, v in enumerate(vals):
        if v.startswith(label):
            return vals[i + n] if i + n < len(vals) else None
    return None


def link_filing(con, eid, f, is_decision, first, S):
    """스레드 replay 의 공시 한 건을 event_filing 에 연결(결정 최초=initial, 결정 정정=amend, 그 외=follow)하고 S['sources'] 에 근거를 쌓는다."""
    fid = f["filing_id"]
    con.execute("INSERT OR IGNORE INTO event_filing VALUES (?,?,?)", (eid, fid, "initial" if (is_decision and first) else ("amend" if is_decision else "follow")))
    S["sources"].append({"filing": fid, "at": f["filed_at"], "title": f["title"]})
