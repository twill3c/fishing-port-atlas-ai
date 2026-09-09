/**
 * SPEC G-12 二実装照合 — 海域の水温トレンド。
 *
 * Python(`build_ocean.py`)が出荷した傾きを、TypeScript の独立実装が
 * **出荷された年系列から**再現できることを確かめる。
 *
 * 結論(傾き)だけでなく**経路**も比べる(HC-065)。同じ数に別の理由で着いた場合、
 * 結論だけを見る照合は緑のまま何も言わない。ここでは中間量 Sxx / Sxy / 残差平方和から
 * 導かれる標準誤差・t 値・決定係数も突き合わせる。
 *
 * 陽性対照として、系列をわざとずらした実装が照合に落ちることも確かめる。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  LONG_SERIES_MIN_YEARS,
  annualNormal,
  formatP,
  formatSlope,
  median,
  olsTrend,
  sparklinePath,
  type OceanArea,
} from "../../lib/ocean";

const ROOT = join(__dirname, "..", "..");
const AREAS: OceanArea[] = JSON.parse(
  readFileSync(join(ROOT, "public", "data", "ocean", "areas.json"), "utf-8"),
);

describe("フィクスチャの前提", () => {
  it("海域が 100 以上あり、長期と短期の両方が含まれる", () => {
    expect(AREAS.length).toBeGreaterThan(100);
    expect(AREAS.some((a) => a.trend.n_years >= LONG_SERIES_MIN_YEARS)).toBe(true);
    expect(AREAS.some((a) => a.trend.n_years < LONG_SERIES_MIN_YEARS)).toBe(true);
  });

  it("各海域の年系列が昇順で、重複が無い", () => {
    for (const area of AREAS) {
      const years = area.series.map((s) => s.y);
      expect(years).toEqual([...years].sort((a, b) => a - b));
      expect(new Set(years).size).toBe(years.length);
    }
  });
});

describe("T-024 / G-12 二実装照合: 傾き", () => {
  it("出荷された全 107 海域で Python の傾きを TS が再現する", () => {
    const diffs: number[] = [];
    for (const area of AREAS) {
      const got = olsTrend(
        area.series.map((s) => s.y),
        area.series.map((s) => s.mean),
      );
      expect(got.n).toBe(area.trend.n_years);
      // 出荷 JSON は小数 4 桁に丸めてあるので、丸めの幅を閾値にする。
      // 「一致する量」と「一致させるために揃える規則」を分けて書く(HC-073)。
      expect(got.slopePerDecade).toBeCloseTo(area.trend.slope_per_decade, 4);
      diffs.push(Math.abs(got.slopePerDecade - area.trend.slope_per_decade));
    }
    expect(Math.max(...diffs)).toBeLessThan(5e-5);
  });

  it("経路も一致する(標準誤差・t 値・決定係数)", () => {
    for (const area of AREAS) {
      const got = olsTrend(
        area.series.map((s) => s.y),
        area.series.map((s) => s.mean),
      );
      expect(got.sePerDecade).toBeCloseTo(area.trend.se_per_decade, 4);
      expect(got.t).toBeCloseTo(area.trend.t, 2);
      if (area.trend.r2 !== null) {
        expect(got.r2).toBeCloseTo(area.trend.r2, 4);
      }
      // 中間量そのものの健全性(これが崩れていれば経路が違う)
      expect(got.sxx).toBeGreaterThan(0);
      expect(got.sse).toBeGreaterThanOrEqual(0);
    }
  });

  it("陽性対照: 系列を 1 年ずらした実装は照合に落ちる", () => {
    // 対照が成り立つ前提を assert で固定する: 傾きが 0 でない海域を選ぶ
    const area = AREAS.find((a) => Math.abs(a.trend.slope_per_decade) > 0.2)!;
    expect(area).toBeDefined();
    const shifted = olsTrend(
      area.series.map((s) => s.y),
      // 値を 1 年ぶんずらす = 経路を意図的に違えた実装
      area.series.map((_, i) => area.series[Math.min(i + 1, area.series.length - 1)].mean),
    );
    expect(Math.abs(shifted.slopePerDecade - area.trend.slope_per_decade)).toBeGreaterThan(
      5e-5,
    );
  });

  it("陽性対照: 傾きの計算が定数系列で 0 を返す", () => {
    const got = olsTrend([2000, 2001, 2002, 2003], [10, 10, 10, 10]);
    expect(got.slopePerDecade).toBe(0);
    expect(got.sse).toBe(0);
  });
});

describe("T-025 海域データの整合", () => {
  it("長期系列は 1982 年に始まり、短期系列は 2016 年に始まる", () => {
    // 期待値の出所: 気象庁 eg_info.html の記載(瀬戸内海の 5 海域は 2016 年から)。
    // その 5 海域は平年値も持たない。実装とは独立に文書が言っていることを確かめる。
    const short = AREAS.filter((a) => a.trend.n_years < LONG_SERIES_MIN_YEARS);
    expect(short).toHaveLength(5);
    for (const area of short) {
      expect(area.trend.first_year).toBe(2016);
      expect(area.has_normal).toBe(false);
    }
    for (const area of AREAS.filter((a) => a.trend.n_years >= LONG_SERIES_MIN_YEARS)) {
      expect(area.trend.first_year).toBe(1982);
      expect(area.has_normal).toBe(true);
    }
  });

  it("平年値の期間が全海域で同一である", () => {
    const periods = new Set(
      AREAS.filter((a) => a.has_normal).map((a) => a.normal_period),
    );
    expect(periods.size).toBe(1);
    expect([...periods][0]).toBe("1991-2020");
  });

  it("部分年が入っていない(取得時点の当年は落ちている)", () => {
    const lastObs = AREAS.map((a) => a.last_observation).sort().at(-1)!;
    const currentYear = Number(lastObs.slice(0, 4));
    for (const area of AREAS) {
      expect(area.trend.last_year).toBeLessThan(currentYear);
    }
  });

  it("平年値の年平均が計算でき、緯度の代理として意味のある幅を持つ", () => {
    const normals = AREAS.map(annualNormal).filter((v): v is number => v !== null);
    expect(normals.length).toBe(AREAS.filter((a) => a.has_normal).length);
    expect(Math.max(...normals) - Math.min(...normals)).toBeGreaterThan(15);
  });
});

describe("T-026 表示用の関数", () => {
  it("スパークラインが viewBox に収まる", () => {
    const w = 120;
    const h = 28;
    for (const area of AREAS) {
      const d = sparklinePath(area.series, w, h);
      expect(d.length).toBeGreaterThan(0);
      const coords = [...d.matchAll(/([ML])(-?[\d.]+),(-?[\d.]+)/g)];
      expect(coords).toHaveLength(area.series.length);
      for (const [, , x, y] of coords) {
        expect(Number(x)).toBeGreaterThanOrEqual(0);
        expect(Number(x)).toBeLessThanOrEqual(w);
        expect(Number(y)).toBeGreaterThanOrEqual(0);
        expect(Number(y)).toBeLessThanOrEqual(h);
      }
    }
  });

  it("p 値を 0 と書かない", () => {
    expect(formatP(0)).toBe("< 0.000001");
    expect(formatP(1e-12)).toBe("< 0.000001");
    expect(formatP(0.0312)).toBe("0.031");
  });

  it("傾きの符号が読める形で出る", () => {
    expect(formatSlope(0.275)).toBe("+0.275");
    expect(formatSlope(-0.075)).toBe("−0.075");
  });

  it("中央値が偶数件でも中央 2 つの平均になる", () => {
    expect(median([3, 1, 2])).toBe(2);
    expect(median([4, 1, 3, 2])).toBe(2.5);
    // 陽性対照: 上側を返す実装との違いが出る配列で確かめる
    expect(median([1, 2, 10, 20])).not.toBe(10);
    expect(median([1, 2, 10, 20])).toBe(6);
  });

  it("画面の中央値が stats.json の中央値と一致する(二経路)", () => {
    const stats = JSON.parse(
      readFileSync(join(ROOT, "public", "data", "stats.json"), "utf-8"),
    );
    const long = AREAS.filter((a) => a.trend.n_years >= LONG_SERIES_MIN_YEARS);
    expect(long).toHaveLength(stats.ocean.long_series_areas);
    expect(median(long.map((a) => a.trend.slope_per_decade))).toBeCloseTo(
      stats.ocean.median_slope_per_decade,
      4,
    );
    expect(long.filter((a) => a.trend.slope_per_decade > 0)).toHaveLength(
      stats.ocean.rising,
    );
    expect(
      long.filter((a) => a.trend.slope_per_decade > 0 && a.trend.p < 0.05),
    ).toHaveLength(stats.ocean.rising_significant);
  });
});
