"""일일 공시 리포트 메일 발송 (Gmail SMTP, 앱 비밀번호).

사용법:
  python send_report.py <리포트 폴더> <YYYY-MM-DD>            # 드라이런: 발송 없이 .eml 파일만 만든다
  python send_report.py <리포트 폴더> <YYYY-MM-DD> --send     # 실제 발송
  --kind-json <kind_daily_*.json>   # KIND 섹션·첨부 추가.  번들이 없으면(DART 통과 0건) KIND 요약만 보낸다.  --test: 제목 앞에 [테스트]  --no-dart: 폴더의 DART 산출물을 무시(통과 0건인 날)  --kind-note "문구": KIND 섹션 대신 안내 한 줄
  python send_report.py <폴더> <날짜> --note "비고 문구" --send   # 본문 하단에 노란 비고 박스
  python send_report.py --alert "제목" "본문" --send          # 실패 알림 메일

폴더 구조: <폴더>/bundle_<날짜>.html, bundle_<날짜>.pdf, reports/*.json
환경변수(.env): GMAIL_USER, GMAIL_APP_PASSWORD, MAIL_TO(없으면 GMAIL_USER). 리포트 메일은 EXTRA_TO(쉼표로 구분, .env 에만 둠 — git 에 올리지 않는다)가 항상 추가 수신
본문은 브리프 표(인라인 CSS), 첨부는 통합 리포트 HTML 하나(KIND 리포트 + DART 공시분석 첫 탭; 없을 때만 번들 HTML·PDF). 비밀번호는 출력·저장하지 않는다.
"""
import glob
import html
import json
import os
import smtplib
import sys
from email.message import EmailMessage

ROOT = os.path.dirname(os.path.abspath(__file__))


def recipients(default):
    """MAIL_TO(없으면 발신 계정) + 기본 추가 수신인, 중복 제거"""
    base = [x.strip() for x in (os.environ.get("MAIL_TO") or default or "").split(",") if x.strip()]
    extra = [x.strip() for x in os.environ.get("EXTRA_TO", "").split(",") if x.strip()]   # 정규 수신자 명단은 .env 에만 둔다(레포가 public). 실패 알림에는 쓰지 않는다
    if not extra:
        print("경고: .env 에 EXTRA_TO 가 없어 추가 수신자 없이 발송합니다.", file=sys.stderr)
    return ", ".join(dict.fromkeys(base + extra))


def load_env():
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def kind_section(kind_json):
    """KIND 지수 주식수 변동 요약(kind/run_kind_daily.py 산출 JSON) → 메일 본문 HTML. 읽기 실패·내용 없음이면 빈 문자열."""
    try:
        sm = (json.load(open(kind_json, encoding="utf-8")) or {}).get("summary")
    except Exception:  # noqa: BLE001 — KIND 쪽 형식 오류가 DART 메일을 막으면 안 된다
        return ""
    if not sm:
        return ""
    etf = sm.get("etf")
    etf_html = ""
    if etf and etf.get("lines"):
        etf_html = ('<h3 style="margin:22px 0 2px;padding-top:10px;border-top:2px solid #e5e7eb">KIND · ETF 설정/환매 흐름</h3>'
                    + "".join(f'<p style="margin:4px 0;font-size:13px">{html.escape(x)}</p>' for x in etf["lines"])
                    + '<p style="margin:2px 0;color:#6b7280;font-size:12px">상세(테마·종목별 압력)는 첨부 HTML의 ETF 흐름 탭</p>')
    th = 'style="padding:6px 8px;border-bottom:1px solid #e5e7eb;vertical-align:top;font-size:12px"'

    def tbl(title, items):
        if not items:
            return ""
        tr = "".join(
            f'<tr><td {th}><b>{html.escape(x["issuer"])}</b><br><span style="color:#6b7280">{html.escape(x["type"])}</span></td>'
            f'<td {th}>{html.escape(x.get("delta_txt") or "")} ({x.get("pct") if x.get("pct") is not None else "-"}%)<br>{html.escape(x.get("mc_txt") or "")}</td>'
            f'<td {th}>{html.escape(x.get("right") or "")}<br><span style="color:#6b7280">{html.escape(x.get("dd") or "")}</span></td></tr>' for x in items)
        return f'<h4 style="margin:12px 0 4px;font-size:13px">{title}</h4><table style="border-collapse:collapse;width:100%">{tr}</table>'
    try:
        body = tbl("신규 이벤트(직전 영업일 공시)", sm["new"]) + tbl("5영업일 내 일정(권리락·상장·변경상장일 기준)", sm["upcoming"]) + tbl("시총 변동 상위(일정 확정, 미반영)", sm["important"][:5])
    except Exception:  # noqa: BLE001
        return ""
    if not body:
        return ('<h3 style="margin:22px 0 2px;padding-top:10px;border-top:2px solid #e5e7eb">KIND · 지수 주식수 변동</h3>'
                '<p style="margin:4px 0;color:#6b7280;font-size:13px">직전 영업일 신규 이벤트와 5영업일 내 일정이 없습니다.</p>') + etf_html
    return ('<h3 style="margin:22px 0 2px;padding-top:10px;border-top:2px solid #e5e7eb">KIND · 지수 주식수 변동</h3>'
            f'<p style="margin:0;color:#6b7280;font-size:12px">상장주식수 기준(유동비율 미적용), 시총 변동은 종가({sm.get("price_date")}) 기준 추정 · 상세는 첨부 HTML</p>{body}' + etf_html)


def kind_note(text):
    return ('<h3 style="margin:22px 0 2px;padding-top:10px;border-top:2px solid #e5e7eb">KIND · 지수 주식수 변동</h3>'
            f'<p style="margin:4px 0;color:#6b7280;font-size:13px">{html.escape(text)}</p>')


def body_html(folder, date, note="", kind_json=None, kind_text=None, no_dart=False):
    rows = []
    for f in ([] if no_dart else glob.glob(os.path.join(folder, "reports", "*.json"))):
        rows.append(json.load(open(f, encoding="utf-8")))
    rows.sort(key=lambda r: (-r.get("importance", 0), -r.get("importance_score", 0)))
    tr = ""
    for r in rows:
        stars = "●" * r.get("importance", 0) + "○" * (5 - r.get("importance", 0))
        tr += (
            '<tr><td style="padding:10px 8px;border-bottom:1px solid #e5e7eb;vertical-align:top">'
            f'<b>{html.escape(r["corp_name"])}</b><br><span style="color:#6b7280;font-size:12px">{r["stock_code"]}</span></td>'
            '<td style="padding:10px 8px;border-bottom:1px solid #e5e7eb;vertical-align:top;font-size:13px">'
            f'<a href="{html.escape(r["dart_url"])}" style="color:#1d4ed8;text-decoration:none">{html.escape(r["disclosure_title"])}</a><br>'
            f'{html.escape(r.get("brief", ""))}</td>'
            f'<td style="padding:10px 8px;border-bottom:1px solid #e5e7eb;vertical-align:top;white-space:nowrap;color:#b45309">{stars}</td></tr>'
        )
    return (
        '<div style="font-family:-apple-system,\'Apple SD Gothic Neo\',\'Malgun Gothic\',sans-serif;max-width:680px;margin:0 auto;color:#111827">'
        f'<h2 style="margin:0 0 4px">AI Agent 공시 브리핑 · {date}</h2>'
        + ('<p style="margin:0 0 14px;color:#6b7280;font-size:13px">중요도 순 · 상세 리포트는 첨부 HTML 한 파일에서 확인하세요(첫 탭이 DART 공시분석).</p>' if rows else
         ('<p style="margin:0 0 14px;color:#6b7280;font-size:13px">상세는 첨부 HTML 한 파일에서 확인하세요.</p>' if kind_json else ""))
        + (f'<table style="border-collapse:collapse;width:100%">{tr}</table>' if rows else
           '<p style="margin:8px 0;padding:10px;background:#f3f4f6;color:#374151;font-size:13px">DART: 오늘은 중요 공시(심화 분석 대상)가 없습니다.</p>')
        + ((kind_section(kind_json) or kind_note("KIND 요약을 읽지 못했습니다.")) if kind_json else (kind_note(kind_text) if kind_text else ""))
        + (f'<p style="margin-top:12px;padding:8px 10px;background:#fef3c7;color:#92400e;font-size:12px">{html.escape(note)}</p>' if note else "")
        +
        '<p style="margin-top:16px;color:#9ca3af;font-size:11px">DART 공시와 공개 자료 기반 자동 생성 문서이며 투자 권유가 아닙니다.</p></div>'
    )


def build(folder, date, note="", kind_json=None, test=False, kind_text=None, no_dart=False):
    load_env()
    user = os.environ.get("GMAIL_USER", "")
    msg = EmailMessage()
    has_bundle = (not no_dart) and os.path.exists(os.path.join(folder, f"bundle_{date}.pdf"))
    msg["Subject"] = ("[테스트] " if test else "") + f"[AI Agent 공시 브리핑] {date}" + ("" if has_bundle else " · DART 중요 공시 없음")
    msg["From"] = user
    msg["To"] = ", ".join(x.strip() for x in (os.environ.get("MAIL_TO") or user).split(",") if x.strip()) if test else recipients(user)   # --test 는 본인(MAIL_TO)에게만
    msg.set_content(f"공시 브리프 {date} — HTML 메일을 지원하는 클라이언트에서 확인하세요. 첨부: 통합 리포트(HTML).")
    msg.add_alternative(body_html(folder, date, note, kind_json, kind_text, no_dart), subtype="html")
    # 첨부는 통합 리포트(KIND 리포트 + DART 공시분석 첫 탭) HTML 하나. 통합 HTML 이 없을 때만(KIND 실패 등) DART 번들 HTML·PDF 로 대체한다.
    kp = None
    if kind_json:
        try:
            kp = (json.load(open(kind_json, encoding="utf-8")) or {}).get("html")
        except Exception:  # noqa: BLE001
            kp = None
    if kp and os.path.exists(kp):
        msg.add_attachment(open(kp, "rb").read(), maintype="text", subtype="html", filename=os.path.basename(kp))
    else:
        for ext, mt in (("html", "text/html"), ("pdf", "application/pdf")):
            p = os.path.join(folder, f"bundle_{date}.{ext}")
            if no_dart or not os.path.exists(p):   # DART 통과 0건인 날은 번들이 없다
                continue
            maintype, subtype = mt.split("/")
            msg.add_attachment(open(p, "rb").read(), maintype=maintype, subtype=subtype, filename=os.path.basename(p))
    return msg


def deliver(msg):
    user, pw = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not pw:
        sys.exit("GMAIL_USER / GMAIL_APP_PASSWORD 가 .env 에 없습니다.")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, pw)
        s.send_message(msg)


def main():
    a = sys.argv[1:]
    send = "--send" in a
    a = [x for x in a if x != "--send"]
    note = ""
    if "--note" in a:
        i = a.index("--note")
        note = a[i + 1]
        del a[i:i + 2]
    test = "--test" in a
    no_dart = "--no-dart" in a
    a = [x for x in a if x not in ("--test", "--no-dart")]
    kind_text = None
    if "--kind-note" in a:
        i = a.index("--kind-note")
        kind_text = a[i + 1]
        del a[i:i + 2]
    kind_json = None
    if "--kind-json" in a:
        i = a.index("--kind-json")
        kind_json = a[i + 1]
        del a[i:i + 2]
    if a and a[0] == "--alert":
        load_env()
        msg = EmailMessage()
        msg["Subject"], msg["From"] = a[1], os.environ.get("GMAIL_USER", "")
        msg["To"] = os.environ.get("MAIL_TO", msg["From"])   # 실패 알림은 운영자(본인)에게만
        msg.set_content(a[2])
    else:
        msg = build(a[0], a[1], note, kind_json, test, kind_text, no_dart)
    if send:
        deliver(msg)
        print("발송 완료 →", msg["To"])
    else:
        out = os.environ.get("EML_OUT", "dryrun.eml")
        open(out, "wb").write(bytes(msg))
        print("드라이런: 발송하지 않음 →", out, "| 수신:", msg["To"] or "(GMAIL_USER 미설정)")


if __name__ == "__main__":
    main()
