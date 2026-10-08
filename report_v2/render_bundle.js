// 통합 리포트(기본 산출물): 날짜 하나 → ① 통합 PDF(브리프 1~2쪽 + 중요도순 공시별 1쪽 리포트, 페이지 내 링크·북마크)
//                                  ② 오프라인 단일 HTML(요약 화면 → 공시 클릭 → 상세 → TOP으로 버튼)
// 사용법: node report_v2/render_bundle.js <YYYYMMDD> [reports 디렉터리] [출력 디렉터리]
//   기본: trial_case/<날짜>/reports  →  trial_case/<날짜>/bundle_<YYYY-MM-DD>.{pdf,html}
//   선행: reports/*_v2.json + *_v2.pdf (render.js 산출), summary_meta.json(선택, funnel/top_order)
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const { chromium } = require("/opt/node22/lib/node_modules/playwright");
const { buildSummary, loadItems } = require("./render_summary");
const { html: reportHtml } = require("./render");

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const day = process.argv[2];
if (!day) throw new Error("usage: node render_bundle.js YYYYMMDD [reportsDir] [outDir]");
const date = `${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6)}`;
const root = path.join(__dirname, "..");
const reportsDir = path.resolve(process.argv[3] || path.join(root, "trial_case", day, "reports"));
const outDir = path.resolve(process.argv[4] || path.join(root, "trial_case", day));
const metaPath = path.join(outDir, "summary_meta.json");
const meta = fs.existsSync(metaPath) ? JSON.parse(fs.readFileSync(metaPath, "utf-8")) : {};
// 알림(NOTIFY): trial_case/<날짜>/triage.json 의 NOTIFY 라벨을 브리프 맨 위에 한 줄씩 표시(분석 없음)
const triPath = path.join(root, "trial_case", day, "triage.json");
if (fs.existsSync(triPath)) {
  meta.notify = JSON.parse(fs.readFileSync(triPath, "utf-8")).filter((r) => r.label === "NOTIFY")
    .map((r) => ({ corp_name: r.corp_name, stock_code: r.stock_code, report_nm: r.report_nm, note: r.rule === "R-CEO" ? "대표이사 변경" : r.reason }));
}
const { items, top, rest } = loadItems(reportsDir, date, meta);
const ordered = items;                                // 상세 페이지 순서 = 전체 중요도순(중요도 → 점수). 브리프 카드에 '상세 p.N'으로 표시
const shortTitle = (d) => `${d.corp_name} · ${String(d.disclosure_title).replace(/\s+/g, " ").slice(0, 28)}`;
const PW = 794, PH = 1123;                            // A4 @96dpi (CSS px)

async function pdfOf(browser, htmlText, tmp) {
  fs.writeFileSync(tmp + ".html", htmlText, "utf-8");
  const page = await browser.newPage();
  await page.goto("file://" + tmp + ".html");
  await page.pdf({ path: tmp + ".pdf", format: "A4", printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 } });
  await page.close();
  return tmp + ".pdf";
}

(async () => {
  const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium", args: ["--no-sandbox"] }).catch(() => chromium.launch({ args: ["--no-sandbox"] }));
  const tmp = fs.mkdtempSync(path.join(require("os").tmpdir(), "bundle-"));
  const idx = new Map(ordered.map((d, i) => [d.rcept_no, i]));

  // ---- ① 통합 PDF ----
  let briefPages = 1, briefPdf;
  for (let tries = 0; tries < 3; tries++) {
    const h = buildSummary(date, meta, items, top, rest, {
      link: (d) => `https://bundle.invalid/#r${idx.get(d.rcept_no)}`,
      goLabel: (d) => `상세 p.${briefPages + idx.get(d.rcept_no) + 1} ›`,
      footer: "카드·행을 누르면 해당 공시 리포트로 이동합니다. 정보 제공용이며 투자 권유가 아닙니다.",
    });
    briefPdf = await pdfOf(browser, h, path.join(tmp, "brief"));
    const n = require("child_process").execFileSync("python3", ["-c", "import sys;from pypdf import PdfReader;print(len(PdfReader(sys.argv[1]).pages))", briefPdf]).toString().trim();
    if (Number(n) === briefPages) break;
    briefPages = Number(n);
  }
  // 각 공시 페이지 하단 우측 '↑ 브리프' 버튼(오버레이). 위치(pt) = CSS px × 0.75
  const pill = { r: 26, b: 14, w: 118, h: 24 };
  const ovHtml = `<!doctype html><meta charset="utf-8"><style>@page{size:A4;margin:0}*{box-sizing:border-box}body{margin:0;background:transparent;font-family:"WenQuanYi Zen Hei","Noto Sans CJK KR","Malgun Gothic",sans-serif}
.pg{width:${PW}px;height:${PH}px;position:relative;overflow:hidden;page-break-after:always}.pg:last-child{page-break-after:auto}
.pill{position:absolute;right:${pill.r}px;bottom:${pill.b}px;width:${pill.w}px;height:${pill.h}px;border-radius:12px;background:#26457a;color:#fff;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;opacity:.92}</style>
${ordered.map((d, i) => `<div class="pg"><div class="pill">↑ 브리프 · ${i + 1}/${ordered.length}</div></div>`).join("")}`;
  const ovPdf = await pdfOf(browser, ovHtml, path.join(tmp, "overlay"));
  const plan = {
    brief: briefPdf, overlay: ovPdf, out: path.join(outDir, `bundle_${date}.pdf`), title: `공시 통합 리포트 ${date}`,
    pill: [(PW - pill.r - pill.w) * 0.75, pill.b * 0.75, (PW - pill.r) * 0.75, (pill.b + pill.h) * 0.75],
    reports: ordered.map((d) => ({ pdf: path.join(reportsDir, `${d.stock_code}_${d.rcept_no}_v2.pdf`), title: shortTitle(d) })),
  };
  for (const r of plan.reports) if (!fs.existsSync(r.pdf)) throw new Error("PDF 없음: " + r.pdf);
  fs.writeFileSync(path.join(tmp, "plan.json"), JSON.stringify(plan));
  console.log(execFileSync("python3", [path.join(__dirname, "merge_pdf.py"), path.join(tmp, "plan.json")]).toString().trim());

  // ---- ② 오프라인 단일 HTML ----
  const sum = buildSummary(date, meta, items, top, rest, { web: true, link: (d) => `#d-${d.rcept_no}`, goLabel: () => "상세 ›", footer: "카드·행을 누르면 상세 리포트가 열립니다. 정보 제공용이며 투자 권유가 아닙니다." });
  const css = sum.match(/<style>([\s\S]*?)<\/style>/)[1];
  const body = sum.match(/<body>([\s\S]*)<\/body>/)[1];
  const details = ordered.map((d, i) => {
    const doc = reportHtml(d).replace("<head>", '<head><base target="_blank">');
    const prev = i > 0 ? `<a class="nb" href="#d-${ordered[i - 1].rcept_no}">◀ 이전</a>` : "";
    const next = i < ordered.length - 1 ? `<a class="nb" href="#d-${ordered[i + 1].rcept_no}">다음 ▶</a>` : "";
    return `<section class="detail" id="d-${d.rcept_no}" hidden><div class="bar"><a class="top" href="#">↑ TOP</a><span class="bt">${esc(shortTitle(d))}</span><span class="nbs">${prev}${next}</span></div>
<div class="frame"><iframe title="${esc(d.corp_name)}" scrolling="no" srcdoc="${esc(doc)}"></iframe></div></section>`;
  }).join("\n");
  const page = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>공시 통합 리포트 ${esc(date)}</title><style>${css}
.detail{background:var(--bg)}.bar{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:10px;background:var(--brand);color:#fff;padding:8px 14px;font-size:12px}
.bar a{color:#fff;text-decoration:none;background:rgba(255,255,255,.18);border-radius:999px;padding:3px 12px;font-weight:700;white-space:nowrap}.bar a:hover{background:rgba(255,255,255,.32)}
.bar .bt{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.nbs{display:flex;gap:6px}
.frame{overflow-x:auto;padding:12px 0 40px}.frame iframe{display:block;margin:0 auto;border:0;width:${PW}px;height:${PH + 8}px;background:#fff;box-shadow:0 2px 14px rgba(0,0,0,.15)}
</style></head><body>
<div id="summary">${body}</div>
${details}
<script>
(function(){
  var sum=document.getElementById('summary'), ds=document.querySelectorAll('.detail');
  function route(){
    var id=location.hash.slice(1), found=false;
    ds.forEach(function(s){var on=s.id===id;s.hidden=!on;if(on)found=true;});
    sum.hidden=found; window.scrollTo(0,0);
  }
  window.addEventListener('hashchange',route); route();
})();
</script></body></html>`;
  fs.writeFileSync(path.join(outDir, `bundle_${date}.html`), page, "utf-8");
  console.log("wrote", path.join(outDir, `bundle_${date}.html`), "details", ordered.length);
  await browser.close();
})();
