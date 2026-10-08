"""DART 공시 원문(document.xml) 다운로드 및 text body 정리."""
import html
import io
import re
import zipfile

import requests

from dart_list_test import BASE, KEY


def fetch_document_raw(rcept_no):
    """원문 zip을 받아 {파일명: 문자열} 반환. 에러면 RuntimeError."""
    r = requests.get(f"{BASE}/document.xml", params={"crtfc_key": KEY, "rcept_no": rcept_no}, timeout=120)
    r.raise_for_status()
    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
    except zipfile.BadZipFile:
        raise RuntimeError(r.content.decode("utf-8", "replace")[:300])
    return {n: z.read(n).decode("utf-8", "replace") for n in z.namelist()}


def html_to_text(raw):
    """스타일/헤더 제거, 표는 행 단위(셀은 ' | ')로 보존, 태그 제거 후 공백 정리."""
    s = re.sub(r"(?is)<(style|script|head)\b.*?</\1>", " ", raw)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</title>|</div>", "\n", s)
    s = re.sub(r"(?i)</t[dh]>", " | ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ")
    lines = []
    for ln in s.split("\n"):
        ln = re.sub(r"[ \t]+", " ", ln).strip()
        ln = re.sub(r"(\| ?)+$", "", ln).strip()   # 줄 끝의 빈 셀 구분자 제거
        ln = re.sub(r"^(\| ?)+", "", ln).strip()
        if ln:
            lines.append(ln)
    return "\n".join(lines)


def fetch_body_text(rcept_no):
    """첨부 파일까지 포함해 text body 반환 (파일이 여럿이면 구분선으로 이어붙임)."""
    parts = fetch_document_raw(rcept_no)
    return "\n\n".join(html_to_text(v) for _, v in sorted(parts.items()))
