/**
 * lib/ports.ts の規則。
 *
 * 期待値は**実データから導く**。合成の例だけで確かめると、
 * 「こう書いたつもり」と実際の性質がずれたまま緑になる(HC-068)。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  PORT_CLASS_COLOR,
  PORT_CLASS_LABEL,
  PORT_CLASS_ORDER,
  countByClass,
  filterPorts,
  normalizeSearch,
  searchKey,
  toGeoJSON,
  type PortClass,
  type PortMin,
} from "../../lib/ports";

const ROOT = join(__dirname, "..", "..");
const PORTS: PortMin[] = JSON.parse(
  readFileSync(join(ROOT, "public", "data", "ports.min.json"), "utf-8"),
);
const STATS = JSON.parse(
  readFileSync(join(ROOT, "public", "data", "stats.json"), "utf-8"),
);

describe("フィクスチャの前提", () => {
  it("実データが空でない(この前提が崩れると以下の検査は何も言わない)", () => {
    expect(PORTS.length).toBeGreaterThan(2000);
    expect(PORTS.some((p) => p.x === null)).toBe(true); // 座標なしの港が実在する
    expect(PORTS.some((p) => p.x !== null)).toBe(true);
  });
});

describe("T-017 検索語の正規化", () => {
  it("全角/半角・大小文字・空白を畳む", () => {
    expect(normalizeSearch("ＡＢＣ")).toBe("abc");
    expect(normalizeSearch(" 焼 津 ")).toBe("焼津");
  });

  it("ひらがなをカタカナへ寄せる(読みの欄はカタカナ)", () => {
    expect(normalizeSearch("やいづ")).toBe("ヤイヅ");
    expect(normalizeSearch("ｼｬﾅｲ")).toBe("シャナイ");
  });

  it("実データの読みが、ひらがな入力で引ける", () => {
    // 期待値の出所: 実データ(2026-09-08 時点の public/data)。港名ではなく読みで引く。
    const withKana = PORTS.find((p) => /^[ァ-ヶー]+$/.test(p.k));
    expect(withKana).toBeDefined();
    const hiragana = withKana!.k.replace(/[ァ-ヶ]/g, (ch) =>
      String.fromCodePoint(ch.codePointAt(0)! - 0x60),
    );
    expect(searchKey(withKana!)).toContain(normalizeSearch(hiragana));
  });
});

describe("T-016 検索", () => {
  it("港名・都道府県・市町村のいずれでも引ける", () => {
    const sample = PORTS.find((p) => p.m.length > 0)!;
    for (const q of [sample.n, sample.p, sample.m]) {
      const hits = filterPorts(PORTS, { query: q });
      expect(hits.map((p) => p.id)).toContain(sample.id);
    }
  });

  it("該当しない語では 0 件になる(何でも返してしまわない)", () => {
    expect(filterPorts(PORTS, { query: "ZZZ該当なしZZZ" })).toHaveLength(0);
  });

  it("都道府県名での検索件数が stats.json の県別件数と一致する", () => {
    // 期待値の出所: 生成物 stats.json(パイプライン側の集計)。
    // 検索の実装とは別経路で数えた値との突合になっている。
    const byPref: Record<string, number> = STATS.built.by_prefecture;
    const pref = "秋田県";
    expect(byPref[pref]).toBeGreaterThan(0);
    const hits = filterPorts(PORTS, { query: pref });
    expect(hits.filter((p) => p.p === pref)).toHaveLength(byPref[pref]);
  });
});

describe("T-019 種別フィルタ", () => {
  it("選んだ種別だけが残る", () => {
    const only = new Set<PortClass>(["special_3"]);
    const hits = filterPorts(PORTS, { classes: only });
    expect(hits.length).toBeGreaterThan(0);
    expect(hits.every((p) => p.c === "special_3")).toBe(true);
    expect(hits).toHaveLength(STATS.built.by_class.special_3);
  });

  it("空選択は絞り込まない(全解除で 0 件にしない)", () => {
    expect(filterPorts(PORTS, { classes: new Set() })).toHaveLength(PORTS.length);
  });

  it("種別ごとの件数が stats.json と一致する", () => {
    const got = countByClass(PORTS);
    for (const c of PORT_CLASS_ORDER) {
      expect(got[c]).toBe(STATS.built.by_class[c]);
    }
  });
});

describe("T-018 GeoJSON 化", () => {
  it("座標なしの港は feature にしない(0,0 に置かない)", () => {
    const fc = toGeoJSON(PORTS);
    const withCoords = PORTS.filter((p) => p.x !== null && p.y !== null).length;
    expect(fc.features).toHaveLength(withCoords);
    expect(withCoords).toBe(STATS.built.with_coordinates);
    for (const f of fc.features) {
      const [lon, lat] = f.geometry.coordinates;
      expect(lon).toBeGreaterThan(122);
      expect(lon).toBeLessThan(154);
      expect(lat).toBeGreaterThan(20);
      expect(lat).toBeLessThan(46);
    }
  });

  it("陽性対照: 座標なしを混ぜても features に現れない", () => {
    const fake: PortMin = {
      id: "0000000",
      n: "対照",
      k: "タイショウ",
      p: "架空県",
      m: "",
      c: "1",
      x: null,
      y: null,
      g: null,
    };
    const fc = toGeoJSON([fake]);
    expect(fc.features).toHaveLength(0);
  });

  it("feature の id が一意である(MapLibre の feature-state に使う)", () => {
    const fc = toGeoJSON(PORTS);
    expect(new Set(fc.features.map((f) => f.id)).size).toBe(fc.features.length);
  });
});

describe("凡例の表", () => {
  it("すべての種別にラベルと色がある(色だけに依存させないため文字も要る)", () => {
    for (const c of PORT_CLASS_ORDER) {
      expect(PORT_CLASS_LABEL[c]).toBeTruthy();
      expect(PORT_CLASS_COLOR[c]).toMatch(/^#[0-9a-f]{6}$/i);
    }
    expect(new Set(Object.values(PORT_CLASS_COLOR)).size).toBe(
      PORT_CLASS_ORDER.length,
    );
  });

  it("実データに現れる種別が、すべて凡例に載っている", () => {
    const seen = new Set(PORTS.map((p) => p.c));
    for (const c of seen) expect(PORT_CLASS_ORDER).toContain(c);
    expect(seen.size).toBe(PORT_CLASS_ORDER.length);
  });
});
