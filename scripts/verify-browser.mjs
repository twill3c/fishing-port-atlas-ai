/**
 * 実ブラウザ検品(TEST_SPEC T-023)。
 *
 * 方針(HC-138 / HC-080):
 * - **在存ではなく幾何と到達**を測る。「点が何件あるか」はソースの件数ではなく
 *   `queryRenderedFeatures` で数える(描かれていないのに緑になる故障を捕まえるため)
 * - 座標を使う操作は、**操作が届いた証拠**(状態変化)を確かめてから結果を判定する
 * - 検品器自身に**陽性対照**を置く。異常なしを返したとき、その検品器が実際に
 *   異常を捕まえられることを一度確かめる
 * - 複数の画面幅で見る。横の溢れと、固定フッタの高さ < 逃げ を各幅で測る
 *
 * 失敗は終了コードで知らせる。取得に失敗した画面を撮っても「撮影しました」と出るので、
 * 道具の側の沈黙を残さない。
 */
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { extname, join, normalize } from "node:path";

import { chromium } from "playwright";

const ROOT = process.cwd();
const OUT = join(ROOT, "out");
const SHOTS = join(ROOT, "shots");
const WIDTHS = [1440, 1024, 768, 414, 360];

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".txt": "text/plain; charset=utf-8",
};

const failures = [];
function check(name, ok, detail = "") {
  if (ok) {
    console.log(`  OK   ${name}`);
  } else {
    console.log(`  FAIL ${name}${detail ? ` — ${detail}` : ""}`);
    failures.push(`${name}${detail ? `: ${detail}` : ""}`);
  }
  return ok;
}

function serve(dir) {
  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url, "http://localhost");
      const pathname = decodeURIComponent(url.pathname);
      const path = normalize(pathname).replace(/^(\.\.[/\\])+/, "");
      let file = join(dir, path);
      // 判定は URL の側で行う。normalize は Windows で "/" を "\" にするので、
      // 正規化後の文字列で "/" 終わりを見ると必ず外れる(2026-09-08 に踏んだ)。
      if (pathname.endsWith("/")) file = join(file, "index.html");
      else if (!extname(file)) file = `${file}.html`;
      if (!existsSync(file)) {
        res.writeHead(404).end("not found");
        return;
      }
      const body = await readFile(file);
      res.writeHead(200, { "content-type": MIME[extname(file)] ?? "application/octet-stream" });
      res.end(body);
    } catch (error) {
      res.writeHead(500).end(String(error));
    }
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port }));
  });
}

async function main() {
  // 本番に対する検品を別に持つ。手元でビルドが通ることと、配られている木が
  // 正しいことは別である(--url で本番の実 URL に当てる)。
  const urlArg = process.argv.indexOf("--url");
  const remote = urlArg >= 0 ? process.argv[urlArg + 1]?.replace(/\/$/, "") : null;

  let server = null;
  let base = remote;
  if (!remote) {
    if (!existsSync(OUT)) {
      console.error("out/ が無い。先に `npm run build` を実行すること。");
      process.exit(2);
    }
    const started = await serve(OUT);
    server = started.server;
    base = `http://127.0.0.1:${started.port}`;
  }
  console.log(`対象: ${base}${remote ? "(本番)" : "(手元の out/)"}`);
  await mkdir(SHOTS, { recursive: true });

  const browser = await chromium.launch();
  const consoleErrors = [];

  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (error) => consoleErrors.push(String(error)));

    console.log("\n[1] トップ画面と地図");
    await page.goto(`${base}/`, { waitUntil: "networkidle" });
    await page.waitForFunction(() => Boolean(window.__atlasMap), null, { timeout: 30_000 });
    await page.waitForFunction(
      () => {
        const map = window.__atlasMap;
        return map && map.isStyleLoaded() && map.querySourceFeatures("ports").length > 0;
      },
      null,
      { timeout: 30_000 },
    );
    // タイルの読み込み待ち(idle にならない環境があるので上限つき)
    await page
      .waitForFunction(() => window.__atlasMap?.loaded?.() === true, null, { timeout: 20_000 })
      .catch(() => {});

    const rendered = await page.evaluate(() => {
      const map = window.__atlasMap;
      return map.queryRenderedFeatures({ layers: ["port-points"] }).length;
    });
    check("地図に漁港が描かれている(queryRenderedFeatures > 0)", rendered > 0, `${rendered} 件`);

    const countText = await page.getByTestId("result-count").innerText();
    const total = Number(countText.replace(/[^\d/]/g, "").split("/")[1]);
    check("件数表示が全港数を出している", total > 2000, countText);

    console.log("\n[2] 幾何: 同じ場所に二重に描かれていないか");
    const geometry = await page.evaluate(() => {
      const map = window.__atlasMap;
      const feats = map.queryRenderedFeatures({ layers: ["port-points"] });
      const seen = new Map();
      let duplicatePositions = 0;
      let outsideViewport = 0;
      const { width, height } = map.getCanvas();
      const dpr = window.devicePixelRatio || 1;
      for (const f of feats) {
        const [lon, lat] = f.geometry.coordinates;
        const p = map.project([lon, lat]);
        if (p.x < -50 || p.y < -50 || p.x > width / dpr + 50 || p.y > height / dpr + 50) {
          outsideViewport += 1;
        }
        const key = `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
        const prev = seen.get(key);
        if (prev && prev !== f.properties.port_no) duplicatePositions += 1;
        seen.set(key, f.properties.port_no);
      }
      return { total: feats.length, duplicatePositions, outsideViewport };
    });
    check(
      "描かれた点が表示域の中にある",
      geometry.outsideViewport === 0,
      `域外 ${geometry.outsideViewport} 件`,
    );
    console.log(
      `       (同一画素に別の港が重なった数: ${geometry.duplicatePositions} — 全国表示では起こりうる)`,
    );

    console.log("\n[3] 到達: 点をクリックすると詳細が開く");
    const target = await page.evaluate(() => {
      const map = window.__atlasMap;
      const canvas = map.getCanvas();
      const rect = canvas.getBoundingClientRect();
      const feats = map.queryRenderedFeatures({ layers: ["port-points"] });
      // 特定第3種は半径が大きく、確実に当てられる
      const candidates = [
        ...feats.filter((f) => f.properties.port_class === "special_3"),
        ...feats,
      ];
      for (const pick of candidates) {
        const p = map.project(pick.geometry.coordinates);
        // map.project はキャンバス内の座標を返す。地図はヘッダと左レールの分だけ
        // ずれた位置にあるので、ビューポート座標へ直す(HC-138)。
        const x = rect.left + p.x;
        const y = rect.top + p.y;
        // さらに、その画素で**一番上にある要素がキャンバスであること**を確かめる。
        // 凡例や出典表示が覆っていると、クリックは地図に届かないまま沈黙する ——
        // 沈黙は「操作したが変化なし」と区別できない。
        if (document.elementFromPoint(x, y) !== canvas) continue;
        // その画素で**先頭に来る**のがこの港であること。
        // 隣り合う港は重なるので(鹿児島の枕崎と坊泊で踏んだ)、
        // 「候補に含まれる」では不十分 —— アプリは features[0] を開く。
        const hits = map.queryRenderedFeatures([p.x, p.y], { layers: ["port-points"] });
        if (hits[0]?.properties.port_no !== pick.properties.port_no) continue;
        return { x, y, name: pick.properties.name, portNo: pick.properties.port_no };
      }
      return null;
    });
    if (!check("クリックできる点が見つかる(覆われていない)", target !== null)) {
      throw new Error("地図の点がすべて何かに覆われている");
    }
    // 操作が届いた証拠を先に取る: その座標で地図が先頭に同じ港を返すこと
    const hitSame = await page.evaluate(
      ({ x, y, portNo }) => {
        const map = window.__atlasMap;
        const rect = map.getCanvas().getBoundingClientRect();
        const hits = map.queryRenderedFeatures([x - rect.left, y - rect.top], {
          layers: ["port-points"],
        });
        return hits[0]?.properties.port_no === portNo;
      },
      target,
    );
    check("クリック座標が狙った港に当たっている", hitSame, `${target.name} (${target.portNo})`);
    await page.mouse.click(target.x, target.y);
    const drawerOpened = await page
      .getByTestId("port-drawer")
      .waitFor({ state: "visible", timeout: 10_000 })
      .then(() => true)
      .catch(() => false);
    check("クリックで Drawer が開く", drawerOpened);

    if (drawerOpened) {
      const nameShown = await page
        .getByTestId("drawer-port-name")
        .innerText()
        .catch(() => "");
      check(
        "開いた Drawer がクリックした港のものである",
        nameShown.startsWith(target.name),
        `期待 ${target.name} / 実際 ${nameShown}`,
      );
      const url = page.url();
      check("URL に選択した港が反映される", url.includes(`port=${target.portNo}`), url);
    }

    console.log("\n[4] 検索と絞り込み");
    await page.getByTestId("search-input").fill("焼津");
    await page.waitForFunction(
      () => {
        const el = document.querySelector('[data-testid="result-count"]');
        return el && Number(el.textContent.replace(/[^\d/]/g, "").split("/")[0]) < 50;
      },
      null,
      { timeout: 10_000 },
    );
    const searchCount = await page.getByTestId("result-count").innerText();
    check("検索で件数が絞られる", /^\s*[1-9]\d?\s*\//.test(searchCount), searchCount);

    await page.getByTestId("search-input").fill("");
    await page.getByTestId("class-special_3").check();
    await page.waitForFunction(
      () => {
        const el = document.querySelector('[data-testid="result-count"]');
        return el && el.textContent.trim().startsWith("13");
      },
      null,
      { timeout: 10_000 },
    );
    const specialCount = await page.getByTestId("result-count").innerText();
    check("特定第3種で絞ると 13 港になる", specialCount.trim().startsWith("13"), specialCount);
    await page.getByTestId("class-special_3").uncheck();

    console.log("\n[5] 検品器の陽性対照");
    // 「異常なし」を返したとき、この検品器が実際に異常を捕まえられるか確かめる。
    const bogusVisible = await page
      .getByTestId("__この test id は存在しない__")
      .isVisible({ timeout: 500 })
      .catch(() => false);
    check("陽性対照: 存在しない要素を「ある」と言わない", bogusVisible === false);
    const wrongName = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="drawer-port-name"]');
      return el ? el.textContent.startsWith("この港名は存在しない") : false;
    });
    check("陽性対照: 港名の照合が誤った名前を通さない", wrongName === false);

    console.log("\n[5b] 海の温度: 図の切れと絞り込み");
    await page.goto(`${base}/ocean/`, { waitUntil: "networkidle" });

    // 図の内側の切れは、ページの横溢れ検査では見えない(HC-159)。
    //
    // ここで `getBBox()` を使ってはならない —— あれは**要素自身の transform を含まない**
    // 座標を返すので、回転した軸ラベル(text-anchor=middle + rotate)が
    // 回転前の位置で負の x を持ち、切れていないのに切れたと言う(2026-09-10 に踏んだ)。
    // 実際に描かれた位置で測るため、client rect どうしを比べる。
    const svgFit = await page.evaluate(() => {
      const svg = document.querySelector(".scatter svg");
      if (!svg) return { found: false };
      const box = svg.getBoundingClientRect();
      const out = [];
      for (const el of svg.querySelectorAll("text, path, circle, line")) {
        const b = el.getBoundingClientRect();
        if (b.width === 0 && b.height === 0) continue;
        if (
          b.left < box.left - 0.5 ||
          b.top < box.top - 0.5 ||
          b.right > box.right + 0.5 ||
          b.bottom > box.bottom + 0.5
        ) {
          out.push(`${el.tagName}:${(el.textContent || "").slice(0, 12)}`);
        }
      }
      return { found: true, overflow: out, elements: svg.querySelectorAll("*").length };
    });
    check("散布図がある", svgFit.found === true);
    if (svgFit.found) {
      check(
        "散布図の要素が viewBox に収まっている",
        svgFit.overflow.length === 0,
        svgFit.overflow.slice(0, 4).join(", "),
      );
      check("散布図が空でない", svgFit.elements > 50, `${svgFit.elements} 要素`);

      // 陽性対照: 同じ測り方を、わざと狭めた枠に当てると溢れを検出すること。
      // これが無いと、測り方が壊れたときも「溢れ 0」で緑になる(HC-041)。
      const shrunk = await page.evaluate(() => {
        const svg = document.querySelector(".scatter svg");
        const box = svg.getBoundingClientRect();
        const inner = {
          left: box.left + box.width * 0.25,
          right: box.right - box.width * 0.25,
          top: box.top + box.height * 0.25,
          bottom: box.bottom - box.height * 0.25,
        };
        let n = 0;
        for (const el of svg.querySelectorAll("text, path, circle, line")) {
          const b = el.getBoundingClientRect();
          if (b.width === 0 && b.height === 0) continue;
          if (
            b.left < inner.left ||
            b.top < inner.top ||
            b.right > inner.right ||
            b.bottom > inner.bottom
          ) {
            n += 1;
          }
        }
        return n;
      });
      check("陽性対照: 狭めた枠なら溢れを検出する", shrunk > 0, `${shrunk} 件`);
    }

    const rowsBefore = await page.locator("table.ocean tbody tr").count();
    check("海域の表に行がある", rowsBefore > 50, `${rowsBefore} 行`);
    const countBefore = await page.getByTestId("ocean-count").innerText();
    await page.locator(".controls .check input").uncheck();
    await page.waitForFunction(
      (before) =>
        document.querySelector('[data-testid="ocean-count"]').textContent.trim() !== before,
      countBefore.trim(),
      { timeout: 5000 },
    );
    const rowsAfter = await page.locator("table.ocean tbody tr").count();
    check(
      "短期系列を出すと行が増える(絞り込みが効いている)",
      rowsAfter === rowsBefore + 5,
      `${rowsBefore} → ${rowsAfter}`,
    );

    console.log("\n[6] フッタ規約と幅ごとの見え方");
    for (const path of ["/", "/about/", "/data/", "/methodology/", "/ocean/"]) {
      await page.goto(`${base}${path}`, { waitUntil: "networkidle" });
      const footer = await page.evaluate(() => {
        const anchors = [...document.querySelectorAll("a")];
        const menu = anchors.find((a) => a.textContent.trim() === "App Menu");
        if (!menu) return null;
        const nav = menu.closest("nav") ?? menu.parentElement;
        const style = getComputedStyle(nav);
        const text = nav.innerText;
        return {
          text,
          position: style.position,
          bottom: style.bottom,
          separators: (text.match(/・/g) ?? []).length,
          links: [...nav.querySelectorAll("a")].map((a) => ({
            label: a.textContent.trim(),
            href: a.href,
          })),
          height: nav.getBoundingClientRect().height,
        };
      });
      if (!check(`${path} フッタが見つかる`, footer !== null)) continue;

      const labels = footer.links.map((l) => l.label);
      check(
        `${path} 5 項目がこの並びである`,
        JSON.stringify(labels) ===
          JSON.stringify([
            "MIT License",
            "GitHub",
            "漁港アトラスの歩き方",
            "漁港アトラス 設計図",
            "App Menu",
          ]),
        labels.join(" / "),
      );
      check(`${path} 区切りが 4 個ある`, footer.separators === 4, `${footer.separators} 個`);
      check(
        `${path} © がリンク文言の外にある`,
        footer.text.includes("© 2026 坂田哲朗") &&
          !labels.some((l) => l.includes("坂田哲朗")),
      );
      check(`${path} 下部固定である`, footer.position === "fixed" && footer.bottom === "0px");
      const mit = footer.links.find((l) => l.label === "MIT License");
      check(`${path} MIT License が LICENSE を指す`, /\/blob\/[^/]+\/LICENSE$/.test(mit.href), mit.href);
    }

    console.log("\n[7] 幅ごとの横溢れと逃げ");
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      for (const path of ["/", "/about/", "/data/", "/ocean/"]) {
        await page.goto(`${base}${path}`, { waitUntil: "networkidle" });
        const measured = await page.evaluate(() => {
          const menu = [...document.querySelectorAll("a")].find(
            (a) => a.textContent.trim() === "App Menu",
          );
          const nav = menu.closest("nav") ?? menu.parentElement;
          return {
            overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
            footerHeight: nav.getBoundingClientRect().height,
            padding: parseFloat(getComputedStyle(document.body).paddingBottom),
            pageHeight: document.documentElement.scrollHeight,
          };
        });
        check(
          `${width}px ${path} 横に溢れない`,
          measured.overflow <= 1,
          `${measured.overflow}px`,
        );
        check(
          `${width}px ${path} フッタの高さ < 逃げ`,
          measured.footerHeight <= measured.padding,
          `高さ ${measured.footerHeight.toFixed(0)} / 逃げ ${measured.padding.toFixed(0)}`,
        );
        check(
          `${width}px ${path} 縦に伸びすぎていない`,
          measured.pageHeight < 16_000,
          `${measured.pageHeight}px`,
        );
      }
    }

    console.log("\n[8] スクリーンショット");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${base}/`, { waitUntil: "networkidle" });
    await page.waitForFunction(() => Boolean(window.__atlasMap), null, { timeout: 30_000 });
    await page.waitForTimeout(2500);
    await page.screenshot({ path: join(SHOTS, "atlas-map.png") });
    await page.goto(`${base}/data/`, { waitUntil: "networkidle" });
    await page.screenshot({ path: join(SHOTS, "atlas-data.png") });
    await page.goto(`${base}/ocean/`, { waitUntil: "networkidle" });
    await page.screenshot({ path: join(SHOTS, "atlas-ocean.png") });
    console.log(`  shots/ に保存した`);

    if (remote) {
      console.log("\n[10] 本番だけの検査");
      const res = await page.request.get(`${base}/data/manifest.json`);
      check("manifest.json が配られている", res.ok(), `${res.status()}`);
      const manifest = res.ok() ? await res.json() : null;
      check(
        "配られている manifest の港数が 2,768 である",
        manifest?.datasets?.ports?.count === 2768,
        String(manifest?.datasets?.ports?.count),
      );
      console.log(`       (build: ${manifest?.build})`);
    }

    console.log("\n[9] コンソールエラー");
    const relevant = consoleErrors.filter((text) => !/favicon|ERR_/i.test(text));
    check("ページのエラーが出ていない", relevant.length === 0, relevant.slice(0, 3).join(" | "));
  } finally {
    await browser.close();
    server?.close();
  }

  console.log("");
  if (failures.length > 0) {
    console.error(`検品 NG: ${failures.length} 件`);
    for (const f of failures) console.error(`  - ${f}`);
    process.exit(1);
  }
  console.log("検品 OK");
}

main().catch((error) => {
  console.error("検品器そのものが落ちた:", error);
  process.exit(2);
});
