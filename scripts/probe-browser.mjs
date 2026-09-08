/** 検品器が落ちたときの切り分け用。ページで何が起きているかを素で出す。 */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { extname, join, normalize } from "node:path";

import { chromium } from "playwright";

const OUT = join(process.cwd(), "out");
const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
};

const server = createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  const pathname = decodeURIComponent(url.pathname);
  const path = normalize(pathname).replace(/^(\.\.[/\\])+/, "");
  let file = join(OUT, path);
  if (pathname.endsWith("/")) file = join(file, "index.html");
  else if (!extname(file)) file = `${file}.html`;
  if (!existsSync(file)) {
    console.log("404", url.pathname);
    res.writeHead(404).end("nf");
    return;
  }
  res.writeHead(200, { "content-type": MIME[extname(file)] ?? "application/octet-stream" });
  res.end(await readFile(file));
});

await new Promise((r) => server.listen(0, "127.0.0.1", r));
const port = server.address().port;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
page.on("console", (m) => console.log(`[console.${m.type()}]`, m.text()));
page.on("pageerror", (e) => console.log("[pageerror]", String(e)));
page.on("requestfailed", (r) => console.log("[reqfail]", r.url(), r.failure()?.errorText));

await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "networkidle" });
await page.waitForTimeout(6000);

console.log(
  "state:",
  await page.evaluate(() => ({
    hasMap: Boolean(window.__atlasMap),
    mapRoot: Boolean(document.querySelector('[data-testid="map-root"]')),
    resultCount: document.querySelector('[data-testid="result-count"]')?.textContent,
    canvases: document.querySelectorAll("canvas").length,
    webgl: (() => {
      try {
        const c = document.createElement("canvas");
        return Boolean(c.getContext("webgl2") || c.getContext("webgl"));
      } catch (e) {
        return String(e);
      }
    })(),
    bodyStart: document.body.innerText.slice(0, 200),
  })),
);

await page.screenshot({ path: join(process.cwd(), "shots", "probe.png") });
await browser.close();
server.close();
