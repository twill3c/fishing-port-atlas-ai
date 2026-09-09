/**
 * 海域の水温系列に対する純粋関数。
 *
 * `olsTrend` は Python 側(`data-pipeline/integrate/build_ocean.py`)と**同じ式を独立に**
 * 実装したものである。出荷した年系列から同じ傾きを再現できることを
 * `tests/frontend/ocean.test.ts` で確かめる(SPEC G-12 二実装照合)。
 * 結論だけでなく、中間量(Sxx / Sxy / 残差平方和)も比べる。
 */

export interface OceanYear {
  y: number;
  mean: number;
  min: number;
  max: number;
  anomaly: number | null;
}

export interface OceanTrend {
  slope_per_decade: number;
  se_per_decade: number;
  t: number;
  p: number;
  r2: number | null;
  n_years: number;
  first_year: number;
  last_year: number;
}

export interface OceanArea {
  area_no: string;
  area_name: string;
  region: string;
  has_normal: boolean;
  normal_period: string | null;
  monthly_normal: (number | null)[];
  last_observation: string;
  trend: OceanTrend;
  series: OceanYear[];
}

/** 長期系列とみなす年数。これ未満は 10 年しかない瀬戸内海の 5 海域である。 */
export const LONG_SERIES_MIN_YEARS = 40;

export interface TrendParts {
  slopePerDecade: number;
  intercept: number;
  sxx: number;
  sxy: number;
  sse: number;
  sePerDecade: number;
  t: number;
  r2: number | null;
  n: number;
}

/** 最小二乗回帰。傾きは ℃/10年。中間量も返す(経路まで照合するため)。 */
export function olsTrend(years: readonly number[], values: readonly number[]): TrendParts {
  const n = years.length;
  if (n !== values.length) throw new Error("年と値の長さが違う");
  if (n < 3) throw new Error(`年数が ${n} 件では回帰しない`);

  let xSum = 0;
  let ySum = 0;
  for (let i = 0; i < n; i += 1) {
    xSum += years[i];
    ySum += values[i];
  }
  const xMean = xSum / n;
  const yMean = ySum / n;

  let sxx = 0;
  let sxy = 0;
  let syy = 0;
  for (let i = 0; i < n; i += 1) {
    const dx = years[i] - xMean;
    const dy = values[i] - yMean;
    sxx += dx * dx;
    sxy += dx * dy;
    syy += dy * dy;
  }
  const slope = sxy / sxx;
  const intercept = yMean - slope * xMean;

  let sse = 0;
  for (let i = 0; i < n; i += 1) {
    const r = values[i] - (slope * years[i] + intercept);
    sse += r * r;
  }
  const se = Math.sqrt(sse / (n - 2) / sxx);

  return {
    slopePerDecade: slope * 10,
    intercept,
    sxx,
    sxy,
    sse,
    sePerDecade: se * 10,
    t: se > 0 ? slope / se : Infinity,
    r2: syy > 0 ? 1 - sse / syy : null,
    n,
  };
}

/**
 * 中央値。件数が偶数のときは中央 2 つの平均を返す。
 *
 * `sorted[n/2]` で済ませない —— 海域は 102 件(偶数)なので、
 * それだと「中央値」と呼びながら上側の値を出すことになる。
 * Python 側(`export_web.py`)も同じ定義にしてある。
 */
export function median(values: readonly number[]): number {
  if (values.length === 0) throw new Error("空の配列に中央値は無い");
  const s = [...values].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 === 1 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

/** 平年値の年平均(緯度の代理)。平年値の無い海域は null。 */
export function annualNormal(area: OceanArea): number | null {
  const months = area.monthly_normal.filter((m): m is number => m !== null);
  if (months.length !== 12) return null;
  return months.reduce((a, b) => a + b, 0) / 12;
}

/** スパークラインの path。y は値域を上下に少し余らせて切れないようにする。 */
export function sparklinePath(
  series: readonly OceanYear[],
  width: number,
  height: number,
  pad = 1.5,
): string {
  if (series.length < 2) return "";
  const xs = series.map((s) => s.y);
  const ys = series.map((s) => s.mean);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const y0 = Math.min(...ys);
  const y1 = Math.max(...ys);
  const spanY = y1 - y0 || 1;
  const sx = (x: number) => ((x - x0) / (x1 - x0)) * (width - pad * 2) + pad;
  const sy = (y: number) => height - pad - ((y - y0) / spanY) * (height - pad * 2);
  return series
    .map((s, i) => `${i === 0 ? "M" : "L"}${sx(s.y).toFixed(1)},${sy(s.mean).toFixed(1)}`)
    .join("");
}

export function formatSlope(slope: number): string {
  return `${slope >= 0 ? "+" : "−"}${Math.abs(slope).toFixed(3)}`;
}

/** p 値の見せ方。極小の値を 0 と書かない。 */
export function formatP(p: number): string {
  if (p < 1e-6) return "< 0.000001";
  if (p < 0.001) return p.toExponential(1);
  return p.toFixed(3);
}
