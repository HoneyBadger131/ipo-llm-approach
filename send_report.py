"""일일 공시 리포트 메일 발송 (Gmail SMTP, 앱 비밀번호).

사용법:
  python send_report.py <리포트 폴더> <YYYY-MM-DD>            # 드라이런: 발송 없이 .eml 파일만 만든다
  python send_report.py <리포트 폴더> <YYYY-MM-DD> --send     # 실제 발송
  python send_report.py <폴더> <날짜> --note "비고 문구" --send   # 본문 하단에 노란 비고 박스
  python send_report.py --alert "제목" "본문" --send          # 실패 알림 메일

폴더 구조: <폴더>/bundle_<날짜>.html, bundle_<날짜>.pdf, reports/*.json
환경변수(.env): GMAIL_USER, GMAIL_APP_PASSWORD, MAIL_TO(없으면 GMAIL_USER)
본문은 브리프 표(인라인 CSS), 첨부는 번들 HTML·PDF. 비밀번호는 출력·저장하지 않는다.
"""
import glob
import html
import json
import os
import smtplib
import sys
from email.message import EmailMessage

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_env():
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def body_html(folder, date, note=""):
    rows = []
    for f in glob.glob(os.path.join(folder, "reports", "*.json")):
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
        '<p style="margin:0 0 14px;color:#6b7280;font-size:13px">중요도 순 · 상세 리포트는 첨부(HTML·PDF)를 확인하세요.</p>'
        f'<table style="border-collapse:collapse;width:100%">{tr}</table>'
        + (f'<p style="margin-top:12px;padding:8px 10px;background:#fef3c7;color:#92400e;font-size:12px">{html.escape(note)}</p>' if note else "")
        +
        '<p style="margin-top:16px;color:#9ca3af;font-size:11px">DART 공시와 공개 자료 기반 자동 생성 문서이며 투자 권유가 아닙니다.</p></div>'
    )


def build(folder, date, note=""):
    load_env()
    user = os.environ.get("GMAIL_USER", "")
    msg = EmailMessage()
    msg["Subject"] = f"[AI Agent 공시 브리핑] {date}"
    msg["From"] = user
    msg["To"] = os.environ.get("MAIL_TO", user)
    msg.set_content(f"공시 브리프 {date} — HTML 메일을 지원하는 클라이언트에서 확인하세요. 첨부: 통합 리포트(HTML·PDF).")
    msg.add_alternative(body_html(folder, date, note), subtype="html")
    for ext, mt in (("html", "text/html"), ("pdf", "application/pdf")):
        p = os.path.join(folder, f"bundle_{date}.{ext}")
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
    if a and a[0] == "--alert":
        load_env()
        msg = EmailMessage()
        msg["Subject"], msg["From"] = a[1], os.environ.get("GMAIL_USER", "")
        msg["To"] = os.environ.get("MAIL_TO", msg["From"])
        msg.set_content(a[2])
    else:
        msg = build(a[0], a[1], note)
    if send:
        deliver(msg)
        print("발송 완료 →", msg["To"])
    else:
        out = os.environ.get("EML_OUT", "dryrun.eml")
        open(out, "wb").write(bytes(msg))
        print("드라이런: 발송하지 않음 →", out, "| 수신:", msg["To"] or "(GMAIL_USER 미설정)")


if __name__ == "__main__":
    main()
