"""통합 PDF 병합: 브리프 PDF + 공시별 PDF → 한 파일. 페이지 내 링크·북마크 포함.
render_bundle.js 가 호출한다.  입력: plan.json
  {"brief": "brief.pdf", "reports": [{"pdf": "...", "title": "..."}], "overlay": "overlay.pdf", "out": "bundle.pdf", "pill": [x1,y1,x2,y2]}
 - 브리프의 'https://bundle.invalid/#rK' 링크(Chromium이 만든 URI 주석)를 K번째 공시 첫 페이지로 가는 내부 링크로 바꾼다.
 - 각 공시 페이지의 overlay(↑ 브리프 버튼) 위치에 브리프 1쪽으로 가는 링크를 추가한다.
"""
import json
import sys

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject

PREFIX = "https://bundle.invalid/#r"


def main(plan_path):
    plan = json.load(open(plan_path, encoding="utf-8"))
    w = PdfWriter()
    brief = PdfReader(plan["brief"])
    nb = len(brief.pages)
    for p in brief.pages:
        w.add_page(p)
    starts = []
    for r in plan["reports"]:
        rd = PdfReader(r["pdf"])
        starts.append(len(w.pages))
        for p in rd.pages:
            w.add_page(p)
    # 브리프 URI 링크 → 내부 이동
    for i in range(nb):
        page = w.pages[i]
        for a in page.get("/Annots", []) or []:
            o = a.get_object()
            act = o.get("/A")
            uri = act.get_object().get("/URI") if act else None
            if uri and str(uri).startswith(PREFIX):
                k = int(str(uri)[len(PREFIX):])
                del o["/A"]
                o[NameObject("/Dest")] = ArrayObject([w.pages[starts[k]].indirect_reference, NameObject("/Fit")])
                o[NameObject("/Border")] = ArrayObject([NumberObject(0), NumberObject(0), NumberObject(0)])
    # 공시 페이지: 오버레이 + '브리프로' 링크
    ov = PdfReader(plan["overlay"]) if plan.get("overlay") else None
    for k, s in enumerate(starts):
        if ov is not None and k < len(ov.pages):
            w.pages[s].merge_page(ov.pages[k])
        x1, y1, x2, y2 = plan["pill"]
        w.add_annotation(page_number=s, annotation=Link(rect=(x1, y1, x2, y2), target_page_index=0))
    # 북마크
    w.add_outline_item("공시 브리프", 0)
    for k, r in enumerate(plan["reports"]):
        w.add_outline_item(f"{k + 1}. {r['title']}", starts[k])
    w.add_metadata({"/Title": plan.get("title", "공시 통합 리포트")})
    w.page_mode = "/UseOutlines"
    w.write(plan["out"])
    print("merged", plan["out"], "pages", len(w.pages), "brief pages", nb)


main(sys.argv[1])
