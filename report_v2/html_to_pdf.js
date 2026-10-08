// 단일 HTML → A4 PDF.  사용법: node report_v2/html_to_pdf.js <in.html> <out.pdf>
const path = require("path");
const { chromium } = require("/opt/node22/lib/node_modules/playwright");
(async () => {
  const [src, out] = process.argv.slice(2);
  const b = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium", args: ["--no-sandbox"] }).catch(() => chromium.launch({ args: ["--no-sandbox"] }));
  const p = await b.newPage();
  await p.goto("file://" + path.resolve(src));
  await p.pdf({ path: out, format: "A4", printBackground: true, margin: { top: 0, right: 0, bottom: 0, left: 0 } });
  await b.close();
  console.log("wrote", out);
})();
