// V2 공시 대시보드 렌더러: JSON -> HTML -> PDF (A4 1쪽)
// 사용법: node report_v2/render.js <data.json> [outBase]   (outBase 기본값: data.json 경로에서 .json 제거)
// 예) node report_v2/render.js trial_case/20260910/reports/329180_20260910800161_v2.json
const fs = require("fs");
const path = require("path");
const { chromium } = require("/opt/node22/lib/node_modules/playwright");

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// 투심 영향 태그: 색만이 아니라 아이콘+글자로도 구분
const SENTIMENT = {
  "긍정적": { cls: "pos", icon: "▲" },
  "부정적": { cls: "neg", icon: "▼" },
  "혼재됨": { cls: "mix", icon: "◆" },
  "알수 없음": { cls: "unk", icon: "?" },
};
const POINT_ICON = { pos: "＋", neg: "－", unk: "?" };
const POINT_LABEL = { pos: "긍정", neg: "리스크", unk: "미확인" };

function barChart(fin) {
  // fin.years: ["2023",...], fin.rows[0]: 막대로 그릴 대표 지표(예: 매출)
  const bars = fin.rows[0];
  const max = Math.max(...bars.values.map((x) => Math.abs(x.v)), 1);
  return `<div class="bars">${fin.years
    .map((y, i) => {
      const x = bars.values[i];
      const h = Math.max(4, Math.round((Math.abs(x.v) / max) * 70));
      return `<div class="bar-col"><div class="bar-val">${esc(x.d)}</div><div class="bar" style="height:${h}px"></div></div>`;
    })
    .join("")}</div>`;
}

function html(d) {
  const s = SENTIMENT[d.sentiment.label] || SENTIMENT["알수 없음"];
  const fin = d.financials;
  const finRows = fin.rows
    .map((r) => `<tr><th>${esc(r.label)}</th>${r.values.map((x) => `<td>${esc(x.d)}</td>`).join("")}</tr>`)
    .join("");
  const val = d.valuation && d.valuation.items && d.valuation.items.length
    ? `<section class="card"><h2>가치평가 · 추정치</h2><div class="mini">${d.valuation.items
        .map((k) => `<div><span class="k">${esc(k.label)}</span><b>${esc(k.value)}</b>${k.sub ? `<small>${esc(k.sub)}</small>` : ""}</div>`)
        .join("")}</div>${d.valuation.note ? `<p class="note">${esc(d.valuation.note)}</p>` : ""}</section>`
    : "";
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>${esc(d.corp_name)} 공시 대시보드</title>
<style>
:root{--bg:#f4f6f9;--card:#fff;--ink:#1c2430;--mute:#6a7686;--line:#e3e8ef;--brand:#26457a;
--pos:#127a4a;--pos-bg:#e3f4eb;--neg:#b3261e;--neg-bg:#fbe7e5;--mix:#8a5a00;--mix-bg:#fdf0d5;--unk:#4f5b6b;--unk-bg:#e8ebf0}
@page{size:A4;margin:0}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"WenQuanYi Zen Hei","Noto Sans CJK KR","Malgun Gothic",sans-serif;font-size:11px;line-height:1.5}
.page{width:210mm;height:297mm;padding:12mm 12mm 9mm;display:flex;flex-direction:column;gap:9px;overflow:hidden}
header{background:var(--brand);color:#fff;border-radius:10px;padding:12px 14px}
header .top{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
header h1{margin:0;font-size:19px;letter-spacing:-.3px}
header .sub{opacity:.85;font-size:10.5px;margin-top:2px}
.chips{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.chip{border-radius:999px;padding:3px 10px;font-size:10.5px;font-weight:700;white-space:nowrap}
.chip.tag{background:rgba(255,255,255,.18);color:#fff}
.chip.pos{background:var(--pos-bg);color:var(--pos)}.chip.neg{background:var(--neg-bg);color:var(--neg)}
.chip.mix{background:var(--mix-bg);color:var(--mix)}.chip.unk{background:var(--unk-bg);color:var(--unk)}
.headline{margin-top:9px;font-size:13.5px;font-weight:700;line-height:1.45}
.kpis{display:grid;grid-template-columns:repeat(${Math.min(Math.max(d.kpis.length,1),4)},1fr);gap:8px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 11px}
.kpi .l{color:var(--mute);font-size:10px}.kpi .v{font-size:19px;font-weight:800;color:var(--brand);letter-spacing:-.5px;margin:1px 0}
.kpi .s{color:var(--mute);font-size:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
h2{margin:0 0 7px;font-size:12px;color:var(--brand)}
.row2{display:grid;grid-template-columns:1.15fr 1fr;gap:8px}
.bars{display:flex;align-items:flex-end;justify-content:space-around;height:104px;border-bottom:1px solid var(--line);margin-bottom:6px}
.bar-col{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:2px;width:30%}
.bar{width:60%;background:var(--brand);border-radius:4px 4px 0 0;opacity:.85}.bar-val{font-weight:700;font-size:10.5px}
table{width:100%;border-collapse:collapse;margin-top:2px;font-size:10.5px}
th,td{padding:3px 4px;border-bottom:1px solid var(--line);text-align:right}th{text-align:left;color:var(--mute);font-weight:400}
thead th{color:var(--ink);font-weight:700;text-align:right}thead th:first-child{text-align:left}
.mini{display:grid;grid-template-columns:1fr 1fr;gap:6px 10px}
.mini div{display:flex;flex-direction:column;border-left:3px solid var(--line);padding-left:7px}
.mini .k{color:var(--mute);font-size:10px}.mini b{font-size:14px}.mini small{color:var(--mute);font-size:9.5px}
.note{margin:7px 0 0;color:var(--mute);font-size:9.5px}
.sent{display:flex;gap:10px;align-items:center}
.sent .chip{font-size:13px;padding:5px 14px}
.sent .why{font-size:11px}
.points{display:flex;flex-direction:column;gap:6px;margin:0;padding:0;list-style:none}
.points li{display:flex;gap:8px;align-items:flex-start}
.pt{flex:none;border-radius:6px;padding:1px 7px;font-size:10px;font-weight:700}
.pt.pos{background:var(--pos-bg);color:var(--pos)}.pt.neg{background:var(--neg-bg);color:var(--neg)}.pt.unk{background:var(--unk-bg);color:var(--unk)}
.news{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:5px}
.news li{display:flex;gap:6px;align-items:baseline}
.news .o{flex:none;color:var(--mute);font-size:10px;min-width:92px}
.news a{color:var(--brand);text-decoration:none;border-bottom:1px solid #b8c6e0}
footer{margin-top:auto;color:var(--mute);font-size:8.5px;line-height:1.45}
</style></head><body><div class="page">
<header><div class="top"><div><h1>${esc(d.corp_name)} <span style="font-weight:400;font-size:13px">${esc(d.stock_code)}</span></h1>
<div class="sub">${esc(d.disclosure_date)} · ${esc(d.disclosure_title)} · 접수번호 ${esc(d.rcept_no)}</div></div>
<div class="chips"><span class="chip tag">${esc(d.tag)}</span><span class="chip ${s.cls}">투심 ${s.icon} ${esc(d.sentiment.label)}</span></div></div>
<div class="headline">${esc(d.headline)}</div></header>
<div class="kpis">${d.kpis.slice(0, 4).map((k) => `<div class="kpi"><div class="l">${esc(k.label)}</div><div class="v">${esc(k.value)}</div><div class="s">${esc(k.sub || "")}</div></div>`).join("")}</div>
<div class="row2"><section class="card"><h2>최근 3년 실적 <span style="font-weight:400;color:var(--mute)">(${esc(fin.basis)})</span></h2>${barChart(fin)}
<table><thead><tr><th></th>${fin.years.map((y) => `<th>${esc(y)}</th>`).join("")}</tr></thead><tbody>${finRows}</tbody></table></section>
<div style="display:flex;flex-direction:column;gap:8px">${val}
<section class="card"><h2>투자심리 영향</h2><div class="sent"><span class="chip ${s.cls}">${s.icon} ${esc(d.sentiment.label)}</span><span class="why">${esc(d.sentiment.reason)}</span></div></section></div></div>
<section class="card"><h2>핵심 포인트</h2><ul class="points">${d.points.map((p) => `<li><span class="pt ${p.type}">${POINT_LABEL[p.type]}</span><span>${esc(p.text)}</span></li>`).join("")}</ul></section>
<section class="card"><h2>뉴스 근거 <span style="font-weight:400;color:var(--mute)">(링크)</span></h2><ul class="news">${d.news.map((n) => `<li><span class="o">${esc(n.outlet)} · ${esc(n.date)}</span><a href="${esc(n.url)}">${esc(n.title)}</a></li>`).join("")}</ul></section>
<footer>${esc(d.sources_note)}<br>DART <a href="${esc(d.dart_url)}">${esc(d.dart_url)}</a> · 정보 제공용이며 투자 권유가 아닙니다.</footer>
</div></body></html>`;
}

(async () => {
  const src = process.argv[2];
  if (!src) throw new Error("usage: node render.js data.json [outBase]");
  const base = process.argv[3] || src.replace(/\.json$/, "");
  const data = JSON.parse(fs.readFileSync(src, "utf-8"));
  fs.writeFileSync(base + ".html", html(data), "utf-8");
  const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium", args: ["--no-sandbox"] }).catch(() =>
    chromium.launch({ args: ["--no-sandbox"] })
  );
  const page = await browser.newPage();
  await page.goto("file://" + path.resolve(base + ".html"));
  await page.pdf({ path: base + ".pdf", format: "A4", printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 } });
  await browser.close();
  console.log("wrote", base + ".html", base + ".pdf");
})();
