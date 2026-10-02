// 공시 대시보드 JSON -> 인덱싱·유사도 검색용 MD (YAML frontmatter + 섹션별 본문)
// 목적: 추후 새 공시와 유사한 과거 공시를 찾아 요약/핵심 포인트에 활용하고, 공시 간 유사·상관 관계를 파악한다.
// 설계 원칙
//  - frontmatter는 필터/조인용 구조화 필드(날짜, 종목, 태그, 투심, 키워드, 관련 공시 id).
//  - 본문은 섹션마다 종목·사건이 드러나는 자기완결형 문장(청크 단위로 임베딩해도 의미가 유지되도록).
//  - 문자열은 JSON.stringify로 인용해 YAML 호환을 유지한다.
const q = (s) => JSON.stringify(String(s ?? ""));
const list = (a) => (a && a.length ? "[" + a.map(q).join(", ") + "]" : "[]");

const sent = (t) => { t = String(t || "").trim(); return /[.!?。]$/.test(t) ? t : t + "."; };

function toMarkdown(d) {
  const fin = d.financials;
  const urls = (d.news || []).map((n) => n.url);
  const fm = [
    "---",
    "schema_version: 1",
    `id: ${q(d.rcept_no)}`,
    `corp_name: ${q(d.corp_name)}`,
    `stock_code: ${q(d.stock_code)}`,
    `disclosure_date: ${q(d.disclosure_date)}`,
    `disclosure_title: ${q(d.disclosure_title)}`,
    `event_type: ${q(d.event_type || "")}`,
    `tag: ${q(d.tag)}`,
    `sentiment: ${q(d.sentiment.label)}`,
    `impact_summary: ${q(d.impact_summary)}`,
    `brief: ${q(d.brief || "")}`,
    `importance: ${Number(d.importance) || 0}`,
    `keywords: ${list(d.keywords)}`,
    `themes: ${list(d.themes)}`,
    `related_ids: ${list(d.related_ids)}   # 같은 날/같은 회사 등 직접 관련된 공시(접수번호). 유사도 기반 연결은 이후 단계에서 채움`,
    `dart_url: ${q(d.dart_url)}`,
    `news_urls: ${list(urls)}`,
    `generated_from: "report_v2/render.js"`,
    "---",
    "",
  ].join("\n");

  const kpis = (d.kpis || []).map((k) => `- ${k.label}: ${k.value}${k.sub ? ` (${k.sub})` : ""}`).join("\n");
  const pts = (d.points || []).map((p) => `- [${{ pos: "긍정", neg: "리스크", unk: "미확인" }[p.type]}] ${p.text}`).join("\n");
  const finLines = fin.rows
    .map((r) => `- ${r.label}: ` + fin.years.map((y, i) => `${y} ${r.values[i].d}`).join(", "))
    .join("\n");
  const val = d.valuation && d.valuation.items && d.valuation.items.length
    ? d.valuation.items.map((k) => `- ${k.label}: ${k.value}${k.sub ? ` (${k.sub})` : ""}`).join("\n") + (d.valuation.note ? `\n- 비고: ${d.valuation.note}` : "")
    : "- 확인되지 않음";
  const c = d.consensus;
  let cons = "- 확인되지 않음";
  if (c && c.series && c.series.length) {
    const vs = c.series.map((x) => x.v);
    const pct = vs[0] ? ((vs[vs.length - 1] - vs[0]) / Math.abs(vs[0])) * 100 : null;
    cons = `- 지표: ${c.metric} (${c.window})\n- 추이: ` + c.series.map((x) => `${x.label} ${x.d}`).join(" → ") +
      (pct === null ? "" : `\n- 변동: ${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`) + (c.note ? `\n- 비고: ${c.note}` : "") + (c.meta ? `\n- 산출 메모: ${c.meta}` : "");
  }
  const news = (d.news || []).map((n) => `- ${n.outlet} (${n.date}): [${n.title}](${n.url})`).join("\n");

  const body = [
    `# ${d.corp_name}(${d.stock_code}) — ${d.disclosure_title} (${d.disclosure_date})`,
    "",
    "## 검색용 요약",
    `${d.disclosure_date} ${d.corp_name}(${d.stock_code})의 ${d.disclosure_title} 공시. ${sent(d.headline)} ${sent(d.impact_summary)} 투자심리 영향: ${d.sentiment.label}(${d.sentiment.reason}). 분류: ${d.tag}.` +
      (d.keywords && d.keywords.length ? ` 키워드: ${d.keywords.join(", ")}.` : ""),
    "",
    "## 한줄 영향",
    `${d.impact_summary} (투심 ${d.sentiment.label}: ${d.sentiment.reason})`,
    "",
    "## 핵심 포인트",
    pts,
    "",
    "## 핵심 수치",
    kpis,
    "",
    `## 실적 추이 (${fin.basis})`,
    finLines,
    "",
    "## 가치평가·추정치",
    val,
    "",
    "## 컨센서스 추이",
    cons,
    "",
    "## 뉴스 근거",
    news || "- 없음",
    "",
    "## 데이터 출처·한계",
    d.sources_note,
    "",
  ].join("\n");
  return fm + body;
}

module.exports = { toMarkdown };
