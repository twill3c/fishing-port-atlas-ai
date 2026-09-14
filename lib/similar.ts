/**
 * 類似漁港の上位 k(SPEC F-08 / G-27)。`data-pipeline/ml/similar.py` と独立に同じ規則で計算する。
 *
 * - 特徴は列ごとに母標準偏差で標準化する(Python の numpy.std と同じ定義)
 * - 距離はユークリッド距離
 * - 並びは、距離を 1e-9 の格子に丸めた整数の昇順、同じなら港番号の昇順。
 *   丸めずに比べると、計算の順序で 1e-16 だけずれた「ほぼ同点」が二実装で入れ替わる
 */

export interface SimilarFeatures {
  features: string[];
  ports: string[];
  /** 生の特徴(標準化前)。行は ports と同じ並び */
  matrix: number[][];
}

export interface Neighbor {
  port_no: string;
  distance: number;
}

const DISTANCE_GRID = 1e-9;

export function standardize(matrix: number[][]): number[][] {
  const n = matrix.length;
  const width = matrix[0]?.length ?? 0;
  const mean = new Array<number>(width).fill(0);
  const sd = new Array<number>(width).fill(0);
  for (const row of matrix) for (let j = 0; j < width; j++) mean[j] += row[j];
  for (let j = 0; j < width; j++) mean[j] /= n;
  for (const row of matrix) for (let j = 0; j < width; j++) sd[j] += (row[j] - mean[j]) ** 2;
  for (let j = 0; j < width; j++) {
    sd[j] = Math.sqrt(sd[j] / n);
    if (sd[j] === 0) throw new Error(`分散 0 の列がある: ${j}`);
  }
  return matrix.map((row) => row.map((v, j) => (v - mean[j]) / sd[j]));
}

/**
 * i 番目の港に近い順の k 港(自分を除く)。
 * tieOrder は陽性対照のためだけにある("desc" は宣言した規則に反する変異体)。
 */
export function nearestPorts(
  z: number[][],
  ports: string[],
  i: number,
  k: number,
  tieOrder: "asc" | "desc" = "asc",
): Neighbor[] {
  const origin = z[i];
  const candidates: { index: number; distance: number; grid: number }[] = [];
  for (let j = 0; j < z.length; j++) {
    if (j === i) continue;
    let sum = 0;
    for (let c = 0; c < origin.length; c++) sum += (z[j][c] - origin[c]) ** 2;
    const distance = Math.sqrt(sum);
    candidates.push({ index: j, distance, grid: Math.floor(distance / DISTANCE_GRID + 0.5) });
  }
  const sign = tieOrder === "asc" ? 1 : -1;
  candidates.sort((a, b) => a.grid - b.grid || sign * (Number(ports[a.index]) - Number(ports[b.index])));
  return candidates.slice(0, k).map((c) => ({ port_no: ports[c.index], distance: c.distance }));
}
