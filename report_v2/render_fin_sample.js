// 금융 운용역용 레이아웃 시안(B안): 고밀도 표 + 큰 숫자. 실제 데이터(기본 10/2)로 브리프 1쪽 + 상세 1쪽 예시를 만든다.
// 사용법: node report_v2/render_fin_sample.js [YYYYMMDD=20261002] [출력 디렉터리=docs/design]
const fs = require("fs");
const path = require("path");
const { chromium } = (() => {
  try { return require("playwright"); } catch (e) { return require("/opt/node22/lib/node_modules/playwright"); } // 로컬: npm i playwright / 클라우드: 전역 경로
})();
const launchOpts = { args: ["--no-sandbox"], ...(require("fs").existsSync("/opt/pw-browsers/chromium") ? { executablePath: "/opt/pw-browsers/chromium" } : {}) };
const { loadItems } = require("./render_summary");
const day = process.argv[2] || "20261002";
const date = `${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6)}`;
const out = path.resolve(process.argv[3] || path.join(__dirname, "..", "docs", "design"));
fs.mkdirSync(out, { recursive: true });
const { items } = loadItems(path.join(__dirname, "..", "trial_case", day, "reports"), date, {});
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const S = { "긍정적": ["pos", "▲"], "부정적": ["neg", "▼"], "혼재됨": ["mix", "◆"], "알수 없음": ["unk", "?"] };
const bar = (n) => `<span class="imp">${[1, 2, 3, 4, 5].map((i) => `<i class="${i <= n ? "on" : ""}"></i>`).join("")}</span>`;
const cnt = (f) => items.filter(f).length;
const rows = items.map((d, i) => {
  const [c, ic] = S[d.sentiment.label] || S["알수 없음"];
  const k0 = d.kpis[0] || {}, k1 = d.kpis[1] || {};
  return `<tr class="${c}"><td class="r">${i + 1}</td><td class="im">${bar(d.importance)}</td><td class="co"><b>${esc(d.corp_name)}</b><small>${esc(d.stock_code)}</small></td>
<td class="ty">${esc(String(d.disclosure_title).replace(/\(.*$/, "").slice(0, 16))}<small>${esc(d.tag)}</small></td>
<td class="num"><b>${esc(k0.value)}</b><small>${esc(k0.label)}</small></td><td class="num"><b>${esc(k1.value)}</b><small>${esc(k1.label)}</small></td>
<td class="se"><span class="chip ${c}">${ic} ${esc(d.sentiment.label)}</span></td><td class="sm">${esc(d.brief)}</td></tr>`;
}).join("");
const d0 = items[0];
const [c0, ic0] = S[d0.sentiment.label] || S["알수 없음"];
const css = `:root{--navy:#14264d;--royal:#2f5fd0;--ink:#142033;--mute:#5a6678;--line:#d8dfeb;--bg:#eef1f6;--pos:#0b7a46;--neg:#c2281f;--mix:#9a6200;--unk:#55606f}
@page{size:A4;margin:0}*{box-sizing:border-box}body{margin:0;background:#fff;color:var(--ink);font-family:"WenQuanYi Zen Hei","Apple SD Gothic Neo","Noto Sans CJK KR","Malgun Gothic",sans-serif;font-size:11px;line-height:1.5}
.pg{width:210mm;height:297mm;padding:0;page-break-after:always;overflow:hidden;position:relative}.pg:last-child{page-break-after:auto}
.top{background:var(--navy);color:#fff;padding:12px 16px 10px;display:flex;align-items:flex-end;justify-content:space-between}
.top h1{margin:0;font-size:20px}.top .sub{font-size:10.5px;opacity:.8}.top .dt{font-size:22px;font-weight:800;letter-spacing:.02em}
.tiles{display:grid;grid-template-columns:repeat(5,1fr);gap:0;border-bottom:1px solid var(--line)}
.tile{padding:9px 14px;border-right:1px solid var(--line)}.tile:last-child{border-right:0}.tile b{display:block;font-size:23px;line-height:1.1}.tile span{font-size:10px;color:var(--mute)}
.tile.pos b{color:var(--pos)}.tile.neg b{color:var(--neg)}.tile.mix b{color:var(--mix)}
.sec{padding:8px 16px 4px;font-weight:800;color:var(--navy);font-size:12px}
table{width:calc(100% - 32px);margin:0 16px;border-collapse:collapse;font-size:10.5px}
th{background:#e8edf6;color:var(--navy);font-size:9.5px;text-align:left;padding:4px 6px;border-bottom:2px solid var(--navy)}
td{padding:5px 6px;border-bottom:1px solid var(--line);vertical-align:middle}td small{display:block;color:var(--mute);font-size:9px}
tr.pos td:first-child{box-shadow:inset 4px 0 var(--pos)}tr.neg td:first-child{box-shadow:inset 4px 0 var(--neg)}tr.mix td:first-child{box-shadow:inset 4px 0 var(--mix)}tr.unk td:first-child{box-shadow:inset 4px 0 var(--unk)}
td.r{width:22px;color:var(--mute);font-weight:700;text-align:center}td.im{width:58px}td.co{width:82px}td.co b{font-size:11.5px}td.ty{width:86px}td.num{width:76px}td.num b{font-size:12.5px;color:var(--navy)}td.se{width:70px}td.sm{font-size:10.5px}
.imp{display:inline-flex;gap:2px}.imp i{display:block;width:8px;height:14px;background:#d3dae6;border-radius:1px}.imp i.on{background:var(--royal)}
.chip{font-weight:800;font-size:10px;white-space:nowrap}.chip.pos{color:var(--pos)}.chip.neg{color:var(--neg)}.chip.mix{color:var(--mix)}.chip.unk{color:var(--unk)}
.legend{padding:8px 16px;color:var(--mute);font-size:9.5px}
.bar2{background:var(--navy);color:#fff;padding:10px 16px;display:flex;justify-content:space-between;align-items:center}
.bar2 .co{font-size:19px;font-weight:800}.bar2 .co small{font-weight:400;opacity:.75;margin-left:8px;font-size:12px}.bar2 .ti{font-size:10.5px;opacity:.85}
.head{padding:12px 16px 8px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center}.head h2{margin:0;font-size:17px;flex:1}
.head .chip{border:1.5px solid currentColor;border-radius:4px;padding:2px 8px;font-size:11px}
.kp{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid var(--line)}.kp div{padding:10px 14px;border-right:1px solid var(--line)}.kp div:last-child{border-right:0}
.kp span{font-size:10px;color:var(--mute)}.kp b{display:block;font-size:22px;color:var(--navy);line-height:1.2}.kp small{color:var(--mute);font-size:9.5px}
.two{display:grid;grid-template-columns:1.25fr 1fr;gap:14px;padding:12px 16px}
.box h3{margin:0 0 5px;font-size:12px;color:var(--navy);border-bottom:2px solid var(--navy);padding-bottom:3px}
.pt{display:flex;gap:7px;padding:4px 0;border-bottom:1px solid var(--line);font-size:11px}.pt em{flex:none;font-style:normal;font-weight:800;font-size:10px;width:34px}.pt .pos{color:var(--pos)}.pt .neg{color:var(--neg)}.pt .unk{color:var(--unk)}
.news a{color:var(--royal);text-decoration:none}.news li{margin:4px 0;font-size:10.5px}.news ul{margin:0;padding-left:14px}
.why{margin:0 16px;padding:8px 12px;background:var(--bg);border-left:4px solid var(--royal);font-size:11px}
.foot{position:absolute;bottom:8mm;left:16px;right:16px;font-size:9px;color:var(--mute)}`;
const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>금융 레이아웃 시안</title><style>${css}</style></head><body>
<section class="pg"><div class="top"><div><h1>공시 브리프</h1><div class="sub">핵심 공시 ${items.length}건 · 중요도 높은 순</div></div><div class="dt">${esc(date)}</div></div>
<div class="tiles"><div class="tile"><b>${items.length}</b><span>리포트 대상</span></div><div class="tile"><b>${cnt((d) => d.importance >= 4)}</b><span>중요도 4 이상</span></div><div class="tile pos"><b>${cnt((d) => d.sentiment.label === "긍정적")}</b><span>▲ 긍정</span></div><div class="tile neg"><b>${cnt((d) => d.sentiment.label === "부정적")}</b><span>▼ 부정</span></div><div class="tile mix"><b>${cnt((d) => d.sentiment.label === "혼재됨" || d.sentiment.label === "알수 없음")}</b><span>◆ 혼재 · ? 미확인</span></div></div>
<div class="sec">오늘의 공시</div>
<table><thead><tr><th>#</th><th>중요도</th><th>종목</th><th>공시</th><th>핵심 수치 ①</th><th>핵심 수치 ②</th><th>투심</th><th>요약</th></tr></thead><tbody>${rows}</tbody></table>
<div class="legend">왼쪽 색 띠 = 투심(초록 긍정 · 빨강 부정 · 갈색 혼재 · 회색 미확인) / 중요도 막대 5칸 / 핵심 수치는 공시의 첫 두 지표를 그대로 올립니다.</div></section>
<section class="pg"><div class="bar2"><div class="co">${esc(d0.corp_name)}<small>${esc(d0.stock_code)}</small></div><div class="ti">${esc(d0.disclosure_title)} · ${esc(d0.disclosure_date)}</div></div>
<div class="head"><h2>${esc(d0.headline)}</h2>${bar(d0.importance)}<span class="chip ${c0}">${ic0} ${esc(d0.sentiment.label)}</span></div>
<div class="kp">${d0.kpis.slice(0, 4).map((k) => `<div><span>${esc(k.label)}</span><b>${esc(k.value)}</b><small>${esc(k.sub || "")}</small></div>`).join("")}</div>
<div class="two"><div class="box"><h3>핵심 포인트</h3>${d0.points.map((p) => `<div class="pt"><em class="${p.type}">${{ pos: "긍정", neg: "리스크", unk: "미확인" }[p.type] || ""}</em><span>${esc(p.text)}</span></div>`).join("")}</div>
<div class="box"><h3>뉴스</h3><div class="news"><ul>${(d0.news || []).map((n) => `<li><a href="${esc(n.url)}">${esc(n.title)}</a><br><small style="color:#5a6678">${esc(n.outlet)} · ${esc(n.date)}</small></li>`).join("")}</ul></div></div></div>
<div class="why"><b>중요도 ${d0.importance}</b> · ${esc(d0.importance_reason)}</div>
<div class="foot">${esc(d0.sources_note)} · DART ${esc(d0.dart_url)} · 정보 제공용이며 투자 권유가 아닙니다.</div></section></body></html>`;
(async () => {
  const f = path.join(out, "finance_layout_sample.html");
  fs.writeFileSync(f, html, "utf-8");
  const b = await chromium.launch(launchOpts);
  const p = await b.newPage(); await p.goto("file://" + f);
  await p.pdf({ path: path.join(out, "finance_layout_sample.pdf"), format: "A4", printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 } });
  await b.close(); console.log("wrote", f);
})();
