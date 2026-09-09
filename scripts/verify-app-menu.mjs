/**
 * app-menu(フリートの玄関口)に自分のカードが出ていることを実ブラウザで確かめる。
 *
 * apps.json が配られていることと、**カードが描かれること**は別である。
 * 分類語彙が合わなかったり必須欄が空だったりすると、データは 200 で返るのに
 * カードだけが出ない。ここは在存ではなく**描画と到達**を測る(HC-138)。
 */
import { chromium } from "playwright";

const BASE = process.argv[2] ?? "https://app-menu-amber.vercel.app";
const APP_ID = process.argv[3] ?? "fishing-port-atlas-ai";
const APP_URL = "https://fishing-port-atlas-ai.vercel.app";

const failures = [];
function check(name, ok, detail = "") {
  console.log(`  ${ok ? "OK  " : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
  if (!ok) failures.push(name);
  return ok;
}

const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`${BASE}/`, { waitUntil: "networkidle" });

  // カードが描かれるまで待つ(固定待ちにしない — HC-245)
  await page
    .waitForFunction(() => document.querySelectorAll("a[href]").length > 50, null, {
      timeout: 30_000,
    })
    .catch(() => {});

  const found = await page.evaluate(
    ({ appId, appUrl }) => {
      const anchors = [...document.querySelectorAll("a[href]")];
      const hit = anchors.find((a) => a.href.startsWith(appUrl));
      if (!hit) {
        return {
          ok: false,
          totalAnchors: anchors.length,
          sample: anchors.slice(0, 3).map((a) => a.href),
        };
      }
      const card = hit.closest("[data-repo], article, li, .card") ?? hit;
      const rect = card.getBoundingClientRect();
      return {
        ok: true,
        text: (card.innerText || "").replace(/\s+/g, " ").slice(0, 220),
        width: rect.width,
        height: rect.height,
        href: hit.href,
        appId,
      };
    },
    { appId: APP_ID, appUrl: APP_URL },
  );

  if (check("自分のカードが描かれている", found.ok, JSON.stringify(found.sample ?? ""))) {
    check("カードに面積がある(潰れていない)", found.width > 100 && found.height > 40,
      `${Math.round(found.width)}×${Math.round(found.height)}`);
    check("カードの行き先が本番 URL", found.href.startsWith(APP_URL), found.href);
    check("カードに要約が出ている", found.text.includes("漁港"), found.text.slice(0, 80));
  }

  // 陽性対照: 実在しないアプリの URL では見つからないこと
  const bogus = await page.evaluate(() =>
    [...document.querySelectorAll("a[href]")].some((a) =>
      a.href.startsWith("https://this-app-does-not-exist-9x7.vercel.app"),
    ),
  );
  check("陽性対照: 実在しない URL を見つけたと言わない", bogus === false);

  check("ページのエラーが出ていない", errors.length === 0, errors.slice(0, 2).join(" | "));
} finally {
  await browser.close();
}

if (failures.length) {
  console.error(`\napp-menu 検品 NG: ${failures.length} 件`);
  process.exit(1);
}
console.log("\napp-menu 検品 OK");
