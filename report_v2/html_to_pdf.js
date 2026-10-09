// 단일 HTML → A4 PDF.  사용법: node report_v2/html_to_pdf.js <in.html> <out.pdf>
const path = require("path");
const { chromium } = (() => {
  try { return require("playwright"); } catch (e) { return require("/opt/node22/lib/node_modules/playwright"); } // 로컬: npm i playwright / 클라우드: 전역 경로
})();
const launchOpts = { args: ["--no-sandbox"], ...(require("fs").existsSync("/opt/pw-browsers/chromium") ? { executablePath: "/opt/pw-browsers/chromium" } : {}) };
(async () => {
  const [src, out] = process.argv.slice(2);
  const b = await chromium.launch(launchOpts);
  const p = await b.newPage();
  await p.goto("file://" + path.resolve(src));
  await p.pdf({ path: out, format: "A4", printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 } });
  await b.close();
  console.log("wrote", out);
})();
