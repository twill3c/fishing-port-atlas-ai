/**
 * 地図に重ねる区域の面の塗り分け(SPEC G-34)。
 *
 * 期待値の出所: 配信メタの rank_order(全国 20 種、build_tsunami.py が区間から作り直した表示ラベル)。
 * 段は区間の下限で決める: 0.3 未満 / 0.3〜1 / 1〜3 / 3〜10 / 10 以上。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { DEPTH_BINS, depthBin, lowerBound, ring } from "../../lib/tsunamiArea";

const ROOT = join(__dirname, "..", "..");
const META: { rank_order: string[] } = JSON.parse(
  readFileSync(join(ROOT, "public", "data", "hazards", "tsunami-meta.json"), "utf-8"),
);

describe("区分ラベルの下限と段", () => {
  it("配信メタの全区分が読め、段は下限の順に並ぶ(下がらない)", () => {
    expect(META.rank_order.length).toBeGreaterThanOrEqual(20);
    const bins = META.rank_order.map(depthBin);
    for (let i = 1; i < bins.length; i++) expect(bins[i]).toBeGreaterThanOrEqual(bins[i - 1]);
    expect(new Set(bins)).toEqual(new Set([0, 1, 2, 3, 4]));
  });

  it("境界の区分を正しい段に入れる", () => {
    expect([lowerBound("〜0.3m"), depthBin("〜0.3m")]).toEqual([0, 0]);
    expect([lowerBound("0.01〜0.3m"), depthBin("0.01〜0.3m")]).toEqual([0.01, 0]);
    expect(depthBin("0.3〜0.5m")).toBe(1);
    expect(depthBin("1〜2m")).toBe(2);
    expect(depthBin("2〜5m")).toBe(2); // 下限 2 なので 1〜3 の段(上限は見ない)
    expect(depthBin("5m〜")).toBe(3);
    expect(depthBin("10m〜")).toBe(4);
    expect(depthBin("20〜50m")).toBe(4);
    expect(DEPTH_BINS).toHaveLength(5);
  });

  it("陽性対照: 読めない形は例外にする(黙って最も浅い段に落とさない)", () => {
    expect(() => depthBin("浅い")).toThrow();
    expect(() => depthBin("1m以上 ～ 3m未満")).toThrow(); // 生のラベルは表示ラベルに直してから来る
  });
});

describe("半径の輪", () => {
  it("輪は閉じていて、中心から半径ぶん離れている(港の局所平面)", () => {
    const lon = 136.2;
    const lat = 35.6;
    const points = ring(lon, lat, 500);
    expect(points[0][0]).toBeCloseTo(points[points.length - 1][0], 12);
    expect(points[0][1]).toBeCloseTo(points[points.length - 1][1], 12);
    const mx = 111_320 * Math.cos((lat * Math.PI) / 180);
    for (const [x, y] of points) {
      expect(Math.hypot((x - lon) * mx, (y - lat) * 110_574)).toBeCloseTo(500, 6);
    }
  });
});
