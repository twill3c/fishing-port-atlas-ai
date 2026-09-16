/**
 * 地図に重ねる津波浸水想定の区域の面(SPEC G-31〜G-34、loop_009)。
 *
 * 区分の刻みは都道府県・年度で違う(全国で 20 種)。地図の塗りは**区間の下限**で 5 段に束ねる。
 * 5 段の色は一つの色相の階調で、dataviz の検証(明度の単調・隣接差 ≥ 0.06・淡い端のコントラスト 2.06:1)を通した。
 * 7 段(〜0.3 / 0.3〜1 / 1〜3 / 3〜5 / 5〜10 / 10〜20 / 20〜)は隣接差が足りず不合格だった。
 * 正確な区分は港の「防災」タブの表で読む。
 */

export interface AreaFeature {
  type: "Feature";
  properties: { rank: string; vintage: number };
  geometry: { type: "Polygon" | "MultiPolygon"; coordinates: unknown };
}

export interface AreaCollection {
  type: "FeatureCollection";
  features: AreaFeature[];
}

export const DEPTH_BINS = [
  { label: "0.3 m 未満", color: "#86b6ef" },
  { label: "0.3〜1 m", color: "#5598e7" },
  { label: "1〜3 m", color: "#2a78d6" },
  { label: "3〜10 m", color: "#1c5cab" },
  { label: "10 m 以上", color: "#104281" },
] as const;

const BIN_LOWER_BOUNDS = [0.3, 1, 3, 10];

/**
 * 表示ラベル(build_tsunami.py の canonical_label が作る形: `〜0.3m` / `0.3〜1m` / `5m〜`)から区間の下限を読む。
 * 読めない形は例外にする(黙って最も浅い段に落とさない)。
 */
export function lowerBound(rank: string): number {
  if (/^〜\d+(\.\d+)?m$/.test(rank)) return 0;
  const m = rank.match(/^(\d+(?:\.\d+)?)(?:〜\d+(?:\.\d+)?)?m〜?$/);
  if (!m) throw new Error(`浸水深の区分が読めない: ${rank}`);
  return Number(m[1]);
}

/** 区間の下限による段(0〜4)。 */
export function depthBin(rank: string): number {
  const low = lowerBound(rank);
  let bin = 0;
  for (const bound of BIN_LOWER_BOUNDS) if (low >= bound) bin += 1;
  return bin;
}

/** 地図に渡す形: 各面に段の番号を付ける。 */
export function withBins(collection: AreaCollection): AreaCollection & {
  features: (AreaFeature & { properties: { bin: number } })[];
} {
  return {
    type: "FeatureCollection",
    features: collection.features.map((f) => ({ ...f, properties: { ...f.properties, bin: depthBin(f.properties.rank) } })),
  };
}

const M_PER_DEG_LAT = 110_574;
const mPerDegLon = (lat: number) => 111_320 * Math.cos((lat * Math.PI) / 180);

/** 港の局所平面での半径 r m の円を、経緯度の輪(64 点)にする。防災タブの半径と同じ平面。 */
export function ring(lon: number, lat: number, radiusM: number, segments = 64): [number, number][] {
  const mx = mPerDegLon(lat);
  const points: [number, number][] = [];
  for (let i = 0; i <= segments; i++) {
    const t = (2 * Math.PI * i) / segments;
    points.push([lon + (radiusM * Math.cos(t)) / mx, lat + (radiusM * Math.sin(t)) / M_PER_DEG_LAT]);
  }
  return points;
}

/** 港を中心にした半径 r m の範囲の外接矩形 [[西, 南], [東, 北]]。 */
export function bounds(lon: number, lat: number, radiusM: number): [[number, number], [number, number]] {
  const dx = radiusM / mPerDegLon(lat);
  const dy = radiusM / M_PER_DEG_LAT;
  return [
    [lon - dx, lat - dy],
    [lon + dx, lat + dy],
  ];
}
