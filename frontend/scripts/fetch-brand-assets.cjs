// Fetch the official BMW logo SVGs and the BMW Type Next web font from bmw.de for LOCAL use.
//
// The BMW roundel is a trademark and BMW Type Next is a licensed typeface. Only the colour
// roundel (public/brand/bmw-logo-colour.svg) is committed, so the deployed header shows it; the
// white logo and the fonts are git-ignored and must not be redistributed. Without the fonts the
// app falls back to Barlow.
//
// bmw.de sits behind bot protection that drops plain HTTP clients, so a real browser loads
// the home page first and downloads each file from inside it.
//
//   npm i -D playwright && npx playwright install chromium     (or point NODE_PATH at an existing install)
//   node scripts/fetch-brand-assets.cjs                         (run from frontend/)

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const ORIGIN = "https://www.bmw.de";
const FONT_DIR = "/etc.clientlibs/bmw-web/clientlibs/clientlib-site/resources/fonts/";
const ASSETS = [
  ["public/brand/bmw-logo-colour.svg", "/content/dam/bmw/common/images/logo-icons/BMW/BMW_Grey-Colour_RGB.svg.asset.1756199978277.svg"],
  ["public/brand/bmw-logo-white.svg", "/content/dam/bmw/common/images/logo-icons/BMW/BMW_White_Logo.svg.asset.1670245093434.svg"],
  ["public/fonts/BMWTypeNext-Light.woff2", FONT_DIR + "BMWTypeNext-Light.woff2"],
  ["public/fonts/BMWTypeNext-Regular.woff2", FONT_DIR + "BMWTypeNext-Regular.woff2"],
  ["public/fonts/BMWTypeNext-Medium.woff2", FONT_DIR + "BMWTypeNext-Medium.woff2"],
  ["public/fonts/BMWTypeNext-Bold.woff2", FONT_DIR + "BMWTypeNext-Bold.woff2"],
];

(async () => {
  const root = path.resolve(__dirname, "..");
  const browser = await chromium.launch({ headless: true, args: ["--disable-blink-features=AutomationControlled"] });
  const context = await browser.newContext({
    userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  });
  const page = await context.newPage();
  await page.goto(ORIGIN + "/de/index.html", { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(3000);
  let failed = 0;
  for (const [target, url] of ASSETS) {
    const res = await page.evaluate(async (u) => {
      const r = await fetch(u, { credentials: "include" });
      const buf = new Uint8Array(await r.arrayBuffer());
      let bin = "";
      for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
      return { status: r.status, type: r.headers.get("content-type"), b64: btoa(bin) };
    }, ORIGIN + url);
    const body = Buffer.from(res.b64, "base64");
    const isSvg = target.endsWith(".svg");
    const ok = res.status === 200 && body.length > 500 &&
      (isSvg ? /<svg[\s>]/.test(body.toString("utf8")) && !/<script/i.test(body.toString("utf8")) : body.subarray(0, 4).toString() === "wOF2");
    if (!ok) {
      failed++;
      console.error(`FAILED ${target}: HTTP ${res.status}, ${res.type}, ${body.length} bytes`);
      continue;
    }
    const out = path.join(root, target);
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, body);
    console.log(`ok ${target} (${body.length.toLocaleString()} bytes)`);
  }
  await browser.close();
  process.exit(failed ? 1 : 0);
})();
