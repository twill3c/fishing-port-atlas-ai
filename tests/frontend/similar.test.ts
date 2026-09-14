/**
 * SPEC G-27 二実装照合 — 類似漁港の上位 10。
 *
 * Python(`data-pipeline/ml/similar.py`)が出荷した近傍を、TypeScript の独立実装が
 * **出荷された生の特徴から**(標準化も自前で)再現できることを全港で確かめる。
 *
 * 同距離の並びは規則を揃えないと食い違う(学習表には特徴がまったく同じ行がある)。
 * 規則: 距離を 1e-9 の格子に丸めた値の昇順、同じなら港番号の昇順。
 * 陽性対照として、同点を港番号の降順で並べる変異体が食い違いを出すことも確かめる。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { nearestPorts, standardize, type SimilarFeatures } from "../../lib/similar";

const ROOT = join(__dirname, "..", "..");
const DIR = join(ROOT, "public", "data", "similar");
const FEATURES: SimilarFeatures = JSON.parse(readFileSync(join(DIR, "features.json"), "utf-8"));
const SHIPPED: Record<string, { port_no: string; distance: number }[]> = JSON.parse(
  readFileSync(join(DIR, "neighbors.json"), "utf-8"),
);
const K = 10;

describe("フィクスチャの前提", () => {
  it("特徴の行列と港の並びが揃い、配信した近傍と港が一致する", () => {
    expect(FEATURES.ports.length).toBeGreaterThan(2000);
    expect(FEATURES.matrix.length).toBe(FEATURES.ports.length);
    expect(FEATURES.matrix.every((row) => row.length === FEATURES.features.length)).toBe(true);
    expect(Object.keys(SHIPPED).sort()).toEqual([...FEATURES.ports].sort());
  });

  it("特徴がまったく同じ行がある(同点の規則が実際に効く)", () => {
    const seen = new Map<string, number>();
    for (const row of FEATURES.matrix) {
      const key = row.join(",");
      seen.set(key, (seen.get(key) ?? 0) + 1);
    }
    expect([...seen.values()].some((n) => n > 1)).toBe(true);
  });
});

describe("G-27 近傍の二実装照合", () => {
  const z = standardize(FEATURES.matrix);

  // 全港の総当たり(2,533 港 × 2,532 候補の並べ替え)。並行して学習が走る機では 7.4 秒かかり、
  // 既定の 5 秒で時間切れになった(2026-09-15、kofun-atlas-ai と同じ型 HC-278)。
  // 照合を間引かず、この検査だけ上限を明示して延ばす。同期のループなので時間切れは結果を隠す
  it("全港で港番号と順序が一致し、距離が 1e-9 以内", { timeout: 60_000 }, () => {
    const mismatches: string[] = [];
    for (let i = 0; i < FEATURES.ports.length; i++) {
      const portNo = FEATURES.ports[i];
      const ours = nearestPorts(z, FEATURES.ports, i, K);
      const theirs = SHIPPED[portNo];
      const sameOrder = ours.every((e, j) => e.port_no === theirs[j].port_no);
      const closeDistance = ours.every((e, j) => Math.abs(e.distance - theirs[j].distance) <= 1e-9);
      if (!sameOrder || !closeDistance) mismatches.push(portNo);
    }
    expect(mismatches).toEqual([]);
  });

  it("陽性対照: 同点を港番号の降順で並べる変異体は食い違いを出す", () => {
    let differs = false;
    for (let i = 0; i < FEATURES.ports.length && !differs; i++) {
      const mutant = nearestPorts(z, FEATURES.ports, i, K, "desc");
      const theirs = SHIPPED[FEATURES.ports[i]];
      differs = mutant.some((e, j) => e.port_no !== theirs[j].port_no);
    }
    expect(differs).toBe(true);
  });
});
