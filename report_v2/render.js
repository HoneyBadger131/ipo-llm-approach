// V2 공시 대시보드 렌더러: JSON -> HTML -> PDF(A4 1쪽) + 인덱싱용 MD
// 사용법: node report_v2/render.js <data.json> [outBase]   (outBase 기본값: data.json 경로에서 .json 제거)
// 예) node report_v2/render.js trial_case/20260910/reports/329180_20260910800161_v2.json
const fs = require("fs");
const path = require("path");
const { chromium } = require("/opt/node22/lib/node_modules/playwright");
const { toMarkdown } = require("./to_md");

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// 투심 영향 태그: 색만이 아니라 아이콘+글자로도 구분
const SENTIMENT = {
  "긍정적": { cls: "pos", icon: "▲" },
  "부정적": { cls: "neg", icon: "▼" },
  "혼재됨": { cls: "mix", icon: "◆" },
  "알수 없음": { cls: "unk", icon: "?" },
};
const POINT_LABEL = { pos: "긍정", neg: "리스크", unk: "미확인" };

// 막대가 표의 연도 열과 정확히 맞도록 표 안의 한 행으로 그린다.
function finTable(fin) {
  const bars = fin.rows[0];
  const max = Math.max(...bars.values.map((x) => Math.abs(x.v)), 1);
  const chartRow = `<tr class="chart"><th></th>${bars.values
    .map((x) => `<td><div class="bv">${esc(x.d)}</div><div class="bar" style="height:${Math.max(4, Math.round((Math.abs(x.v) / max) * 64))}px"></div></td>`)
    .join("")}</tr>`;
  const rows = fin.rows.map((r) => `<tr><th>${esc(r.label)}</th>${r.values.map((x) => `<td>${esc(x.d)}</td>`).join("")}</tr>`).join("");
  return `<table><thead><tr><th></th>${fin.years.map((y) => `<th>${esc(y)}</th>`).join("")}</tr></thead><tbody>${chartRow}${rows}</tbody></table>`;
}

// 컨센서스 추이: series(과거->현재)를 막대 + 첫 시점 대비 변동률로 표시
function consensusCard(c) {
  if (!c || !c.series || !c.series.length) return "";
  const vs = c.series.map((x) => x.v);
  const max = Math.max(...vs.map(Math.abs), 1);
  const first = vs[0], last = vs[vs.length - 1];
  const pct = first ? ((last - first) / Math.abs(first)) * 100 : null;
  const chg = pct === null ? "" : `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
  const cls = pct === null ? "" : pct > 0.5 ? "up" : pct < -0.5 ? "down" : "flat";
  const arrow = cls === "up" ? "▲" : cls === "down" ? "▼" : "▬";
  const cols = c.series
    .map((x) => `<div class="cs"><div class="bv">${esc(x.d)}</div><div class="cbar" style="height:${Math.max(4, Math.round((Math.abs(x.v) / max) * 46))}px"></div><div class="cl">${esc(x.label)}</div></div>`)
    .join("");
  return `<section class="card"><h2>컨센서스 추이 <span class="sub">${esc(c.metric)} · ${esc(c.window)}</span></h2>
<div class="cons"><div class="cbars">${cols}</div>
<div class="cdelta ${cls}"><span class="big">${arrow} ${esc(chg)}</span><span class="sm">${esc(c.window_label || "기간 변동")}</span></div></div>
${c.note ? `<p class="note">${esc(c.note)}</p>` : ""}</section>`;
}

function html(d) {
  const s = SENTIMENT[d.sentiment.label] || SENTIMENT["알수 없음"];
  const fin = d.financials;
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
body{margin:0;background:var(--bg);color:var(--ink);font-family:"WenQuanYi Zen Hei","Noto Sans CJK KR","Malgun Gothic",sans-serif;font-size:11.5px;line-height:1.55}
.page{width:210mm;height:297mm;padding:12mm 12mm 9mm;display:flex;flex-direction:column;gap:11px;overflow:hidden}
header{background:var(--brand);color:#fff;border-radius:10px;padding:14px 16px}
header .top{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
header h1{margin:0;font-size:20px;letter-spacing:-.3px}
header .sub{opacity:.85;font-size:10.5px;margin-top:2px}
.chips{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.chip{border-radius:999px;padding:3px 10px;font-size:10.5px;font-weight:700;white-space:nowrap}
.chip.tag{background:rgba(255,255,255,.18);color:#fff}
.chip.pos{background:var(--pos-bg);color:var(--pos)}.chip.neg{background:var(--neg-bg);color:var(--neg)}
.chip.mix{background:var(--mix-bg);color:var(--mix)}.chip.unk{background:var(--unk-bg);color:var(--unk)}
.headline{margin-top:10px;font-size:14px;font-weight:700;line-height:1.45}
.kpis{display:grid;grid-template-columns:repeat(${Math.min(Math.max(d.kpis.length, 1), 4)},1fr);gap:9px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.kpi .l{color:var(--mute);font-size:10px}.kpi .v{font-size:20px;font-weight:800;color:var(--brand);letter-spacing:-.5px;margin:1px 0}
.kpi .s{color:var(--mute);font-size:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:11px 13px}
h2{margin:0 0 8px;font-size:12.5px;color:var(--brand)}
h2 .sub{font-weight:400;color:var(--mute);font-size:10.5px;margin-left:4px}
.impact{display:flex;gap:10px;align-items:center;border-radius:8px;padding:9px 11px;margin-bottom:9px}
.impact.pos{background:var(--pos-bg)}.impact.neg{background:var(--neg-bg)}.impact.mix{background:var(--mix-bg)}.impact.unk{background:var(--unk-bg)}
.impact .chip{background:#fff}
.impact.pos .chip{color:var(--pos)}.impact.neg .chip{color:var(--neg)}.impact.mix .chip{color:var(--mix)}.impact.unk .chip{color:var(--unk)}
.impact .t{font-size:12.5px;font-weight:700;line-height:1.45}
.impact .why{font-size:10.5px;color:var(--mute);font-weight:400;display:block;margin-top:1px}
.points{display:flex;flex-direction:column;gap:7px;margin:0;padding:0;list-style:none}
.points li{display:flex;gap:8px;align-items:flex-start}
.pt{flex:none;border-radius:6px;padding:1px 7px;font-size:10px;font-weight:700}
.pt.pos{background:var(--pos-bg);color:var(--pos)}.pt.neg{background:var(--neg-bg);color:var(--neg)}.pt.unk{background:var(--unk-bg);color:var(--unk)}
.row2{display:grid;grid-template-columns:1.1fr 1fr;gap:9px}
table{width:100%;border-collapse:collapse;font-size:10.5px;table-layout:fixed}
th,td{padding:3px 4px;border-bottom:1px solid var(--line);text-align:right}th{text-align:left;color:var(--mute);font-weight:400;width:24%}
thead th{color:var(--ink);font-weight:700;text-align:right}thead th:first-child{text-align:left}
tr.chart td{vertical-align:bottom;text-align:center;border-bottom:1px solid var(--line);padding-bottom:0;height:88px}
.bv{font-weight:700;font-size:10.5px;margin-bottom:2px}
.bar{width:55%;margin:0 auto;background:var(--brand);border-radius:4px 4px 0 0;opacity:.85}
.mini{display:grid;grid-template-columns:1fr 1fr;gap:8px 10px}
.mini div{display:flex;flex-direction:column;border-left:3px solid var(--line);padding-left:7px}
.mini .k{color:var(--mute);font-size:10px}.mini b{font-size:15px}.mini small{color:var(--mute);font-size:9.5px}
.note{margin:8px 0 0;color:var(--mute);font-size:9.5px}
.cons{display:flex;align-items:flex-end;gap:14px}
.cbars{display:flex;flex:1;gap:8px;align-items:flex-end;justify-content:space-around;border-bottom:1px solid var(--line);padding-bottom:0}
.cs{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;width:20%}
.cbar{width:55%;background:var(--brand);opacity:.7;border-radius:4px 4px 0 0}
.cl{color:var(--mute);font-size:9.5px;margin:3px 0 -1px;white-space:nowrap}
.cdelta{flex:none;width:96px;text-align:center;border-radius:8px;padding:8px 6px;background:var(--unk-bg);color:var(--unk)}
.cdelta.up{background:var(--pos-bg);color:var(--pos)}.cdelta.down{background:var(--neg-bg);color:var(--neg)}
.cdelta .big{display:block;font-size:16px;font-weight:800}.cdelta .sm{display:block;font-size:9.5px}
.news{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:6px}
.news li{display:flex;gap:6px;align-items:baseline}
.news .o{flex:none;color:var(--mute);font-size:10px;min-width:98px}
.news a{color:var(--brand);text-decoration:none;border-bottom:1px solid #b8c6e0}
footer{margin-top:auto;color:var(--mute);font-size:8.5px;line-height:1.45}
</style></head><body><div class="page">
<header><div class="top"><div><h1>${esc(d.corp_name)} <span style="font-weight:400;font-size:13px">${esc(d.stock_code)}</span></h1>
<div class="sub">${esc(d.disclosure_date)} · ${esc(d.disclosure_title)} · 접수번호 ${esc(d.rcept_no)}</div></div>
<div class="chips"><span class="chip tag">${esc(d.tag)}</span><span class="chip ${s.cls}">투심 ${s.icon} ${esc(d.sentiment.label)}</span></div></div>
<div class="headline">${esc(d.headline)}</div></header>
<div class="kpis">${d.kpis.slice(0, 4).map((k) => `<div class="kpi"><div class="l">${esc(k.label)}</div><div class="v">${esc(k.value)}</div><div class="s">${esc(k.sub || "")}</div></div>`).join("")}</div>
<section class="card"><h2>핵심 포인트</h2>
<div class="impact ${s.cls}"><span class="chip">${s.icon} ${esc(d.sentiment.label)}</span><span class="t">${esc(d.impact_summary)}<span class="why">${esc(d.sentiment.reason)}</span></span></div>
<ul class="points">${d.points.map((p) => `<li><span class="pt ${p.type}">${POINT_LABEL[p.type]}</span><span>${esc(p.text)}</span></li>`).join("")}</ul></section>
<div class="row2"${val ? "" : ' style="grid-template-columns:1fr"'}><section class="card"><h2>최근 3년 실적 <span class="sub">${esc(fin.basis)}</span></h2>${finTable(fin)}</section>${val}</div>
${consensusCard(d.consensus)}
<section class="card"><h2>뉴스 근거 <span class="sub">링크</span></h2><ul class="news">${d.news.map((n) => `<li><span class="o">${esc(n.outlet)} · ${esc(n.date)}</span><a href="${esc(n.url)}">${esc(n.title)}</a></li>`).join("")}</ul></section>
<footer>${esc(d.sources_note)}<br>DART <a href="${esc(d.dart_url)}">${esc(d.dart_url)}</a> · 정보 제공용이며 투자 권유가 아닙니다.</footer>
</div></body></html>`;
}

(async () => {
  const src = process.argv[2];
  if (!src) throw new Error("usage: node render.js data.json [outBase]");
  const base = process.argv[3] || src.replace(/\.json$/, "");
  const data = JSON.parse(fs.readFileSync(src, "utf-8"));
  fs.writeFileSync(base + ".html", html(data), "utf-8");
  // 인덱싱용 MD (disclosure_md/<공시일>/<종목코드>_<접수번호>.md)
  const mdDir = path.join(__dirname, "..", "disclosure_md", data.disclosure_date);
  fs.mkdirSync(mdDir, { recursive: true });
  const mdPath = path.join(mdDir, `${data.stock_code}_${data.rcept_no}.md`);
  fs.writeFileSync(mdPath, toMarkdown(data), "utf-8");
  const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium", args: ["--no-sandbox"] }).catch(() =>
    chromium.launch({ args: ["--no-sandbox"] })
  );
  const page = await browser.newPage();
  await page.goto("file://" + path.resolve(base + ".html"));
  await page.pdf({ path: base + ".pdf", format: "A4", printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 } });
  await browser.close();
  console.log("wrote", base + ".html", base + ".pdf", mdPath);
})();
