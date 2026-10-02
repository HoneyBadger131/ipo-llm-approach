// 통합 리포트 렌더러: 날짜별 *_v2.json 전체 -> 간결한 대시보드(HTML/PDF)
// 사용법: node report_v2/render_summary.js <reports 디렉터리> <공시일 YYYY-MM-DD> [meta.json] [outBase]
//  - 중요도(importance) 내림차순으로 정렬, TOP 카드(최대 10건, 회사당 1건)는 중요도 3 이상만(5건 미만이면 5건까지 채움), 나머지는 한 줄 표.
//  - meta.json(선택): {"funnel":[["전체 공시",1096],...], "top_order":["접수번호",...]}  top_order는 동점 정렬/수동 순서.
const fs = require("fs");
const path = require("path");
const { chromium } = require("/opt/node22/lib/node_modules/playwright");

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SENT = { "긍정적": ["pos", "▲"], "부정적": ["neg", "▼"], "혼재됨": ["mix", "◆"], "알수 없음": ["unk", "?"] };

const dir = process.argv[2], date = process.argv[3];
const metaPath = process.argv[4] && process.argv[4] !== "-" ? process.argv[4] : null;
const outBase = process.argv[5] || path.join(path.dirname(path.resolve(dir)), `summary_${date}`);
const meta = metaPath ? JSON.parse(fs.readFileSync(metaPath, "utf-8")) : {};

let items = fs.readdirSync(dir).filter((f) => f.endsWith("_v2.json"))
  .map((f) => JSON.parse(fs.readFileSync(path.join(dir, f), "utf-8")))
  .filter((d) => d.disclosure_date === date);
const order = meta.top_order || [];
items.sort((a, b) => {
  const ia = order.indexOf(a.rcept_no), ib = order.indexOf(b.rcept_no);
  if (ia !== -1 || ib !== -1) return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  return (b.importance || 0) - (a.importance || 0) || (b.importance_score || 0) - (a.importance_score || 0) || String(a.corp_name).localeCompare(b.corp_name, "ko");
});
// TOP은 최대 10건·회사당 1건(같은 회사의 다른 공시는 아래 표로). 중요도 3 미만은 TOP에서 뺀다(단 최소 5건은 채운다).
const TOP_MAX = 10, TOP_MIN = 5, TOP_IMP = 3;
const top = [], seen = new Set();
for (const d of items) {
  if (top.length >= TOP_MAX || seen.has(d.stock_code)) continue;
  if ((d.importance || 0) < TOP_IMP && top.length >= TOP_MIN) continue;
  top.push(d); seen.add(d.stock_code);
}
const rest = items.filter((d) => !top.includes(d));

const cnt = (f) => items.filter(f).length;
const chip = (d) => { const [c, i] = SENT[d.sentiment.label] || SENT["알수 없음"]; return `<span class="chip ${c}">${i} ${esc(d.sentiment.label)}</span>`; };
const dots = (n) => `<span class="dots" title="중요도 ${n}/5">${"●".repeat(n)}${"○".repeat(Math.max(0, 5 - n))}</span>`;
const shortTitle = (s) => { s = String(s).replace(/\s+/g, " "); return s.length > 26 ? s.slice(0, 25) + "…" : s; };

const card = (d, i) => `<div class="card"><div class="rank">${i + 1}</div><div class="cb">
<div class="l1"><b>${esc(d.corp_name)}</b> <span class="code">${esc(d.stock_code)}</span><span class="ttl">${esc(shortTitle(d.disclosure_title))}</span></div>
<div class="l2"><span class="chip tag">${esc(d.tag)}</span>${chip(d)}${dots(d.importance || 0)}</div>
<div class="brief">${esc(d.brief || d.impact_summary)}</div></div></div>`;
const row = (d) => `<tr><td class="n"><b>${esc(d.corp_name)}</b><span class="code">${esc(d.stock_code)}</span></td><td class="t">${esc(shortTitle(d.disclosure_title))}</td><td class="c"><span class="chip tag">${esc(d.tag)}</span> ${chip(d)}</td><td class="b">${esc(d.brief || d.impact_summary)}</td></tr>`;

const funnel = (meta.funnel || []).map(([k, v]) => `<span class="f"><b>${esc(v)}</b>${esc(k)}</span>`).join('<span class="ar">›</span>');
const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>공시 브리프 ${esc(date)}</title><style>
:root{--bg:#f4f6f9;--card:#fff;--ink:#1c2430;--mute:#6a7686;--line:#e3e8ef;--brand:#26457a;
--pos:#127a4a;--pos-bg:#e3f4eb;--neg:#b3261e;--neg-bg:#fbe7e5;--mix:#8a5a00;--mix-bg:#fdf0d5;--unk:#4f5b6b;--unk-bg:#e8ebf0}
@page{size:A4;margin:0}*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"WenQuanYi Zen Hei","Noto Sans CJK KR","Malgun Gothic",sans-serif;font-size:11px;line-height:1.5}
.page{width:210mm;min-height:297mm;padding:9mm 11mm 6mm;display:flex;flex-direction:column;gap:7px}
header{background:var(--brand);color:#fff;border-radius:10px;padding:10px 15px}
header h1{margin:0;font-size:19px}header .sub{opacity:.85;font-size:10.5px;margin-top:2px}
.stats{display:flex;gap:7px;margin-top:9px;flex-wrap:wrap;align-items:center}
.stats .s{background:rgba(255,255,255,.16);border-radius:999px;padding:2px 10px;font-size:10.5px}
.funnel{margin-top:7px;font-size:10px;opacity:.9}.funnel .f{margin-right:4px}.funnel b{margin-right:3px;font-size:11px}.funnel .ar{margin:0 6px;opacity:.7}
h2{margin:2px 0 0;font-size:12.5px;color:var(--brand)}
.chip{border-radius:999px;padding:1px 8px;font-size:10px;font-weight:700;white-space:nowrap;display:inline-block}
.chip.tag{background:#e8edf6;color:var(--brand)}.chip.pos{background:var(--pos-bg);color:var(--pos)}.chip.neg{background:var(--neg-bg);color:var(--neg)}.chip.mix{background:var(--mix-bg);color:var(--mix)}.chip.unk{background:var(--unk-bg);color:var(--unk)}
.card{display:flex;gap:10px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:5px 12px;align-items:stretch;break-inside:avoid}
.rank{flex:none;width:26px;height:26px;border-radius:50%;background:var(--brand);color:#fff;font-weight:800;display:flex;align-items:center;justify-content:center;margin-top:2px}
.cb{flex:1}.l1{display:flex;align-items:baseline;gap:6px}.l1 b{font-size:13px}.code{color:var(--mute);font-size:10px;margin-left:3px}.ttl{color:var(--mute);font-size:10px;margin-left:auto}
.l2{display:flex;gap:6px;align-items:center;margin:3px 0 4px}.dots{margin-left:auto;color:var(--brand);font-size:10px;letter-spacing:1px}
.brief{font-size:11.5px;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:10.5px}
td{padding:3.5px 7px;border-bottom:1px solid var(--line);vertical-align:top}tr:last-child td{border-bottom:0}
td.n{width:21%}td.n b{display:block;font-size:11px}td.t{width:21%;color:var(--mute)}td.c{width:17%}td.c .chip{margin-bottom:2px}td.b{width:41%}
footer{margin-top:auto;color:var(--mute);font-size:8.5px}
</style></head><body><div class="page">
<header><h1>공시 브리프 · ${esc(date)}</h1><div class="sub">핵심 공시 ${items.length}건 · 중요도 상위 ${top.length}건을 먼저 보여줍니다</div>
<div class="stats"><span class="s">사업 변동 ${cnt((d) => d.tag === "사업 변동")}</span><span class="s">기타 사항 ${cnt((d) => d.tag !== "사업 변동")}</span>
<span class="s">▲ 긍정 ${cnt((d) => d.sentiment.label === "긍정적")}</span><span class="s">▼ 부정 ${cnt((d) => d.sentiment.label === "부정적")}</span><span class="s">◆ 혼재 ${cnt((d) => d.sentiment.label === "혼재됨")}</span><span class="s">? 미확인 ${cnt((d) => d.sentiment.label === "알수 없음")}</span></div>
${funnel ? `<div class="funnel">${funnel}</div>` : ""}</header>
<h2>TOP ${top.length}</h2>${top.map(card).join("")}
${rest.length ? `<h2>그 외 공시</h2><table><tbody>${rest.map(row).join("")}</tbody></table>` : ""}
<footer>세부 내용은 공시별 대시보드(PDF)·MD 참조. 정보 제공용이며 투자 권유가 아닙니다.</footer></div></body></html>`;

(async () => {
  fs.writeFileSync(outBase + ".html", html, "utf-8");
  const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium", args: ["--no-sandbox"] }).catch(() => chromium.launch({ args: ["--no-sandbox"] }));
  const page = await browser.newPage();
  await page.goto("file://" + path.resolve(outBase + ".html"));
  await page.pdf({ path: outBase + ".pdf", format: "A4", printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 } });
  await browser.close();
  console.log("wrote", outBase + ".html", outBase + ".pdf", "items", items.length);
})();
