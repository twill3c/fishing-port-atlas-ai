/**
 * 漁港データの純粋関数群。
 *
 * 画面の都合(色・ラベル)と、検索・絞り込みの規則をここに集める。
 * DOM にも MapLibre にも依存させない —— 規則を検品器や UI の中に書くと、
 * 壊れたときに誰も気づかないため(HC-080)。
 */

export type PortClass = "1" | "2" | "3" | "special_3" | "4";

export const PORT_CLASS_ORDER: readonly PortClass[] = [
  "1",
  "2",
  "3",
  "special_3",
  "4",
] as const;

export const PORT_CLASS_LABEL: Record<PortClass, string> = {
  "1": "第1種",
  "2": "第2種",
  "3": "第3種",
  special_3: "特定第3種",
  "4": "第4種",
};

/** 種別の説明(水産庁 総括表の脚注より。出典を画面に出すため定数ではなく文言で持つ) */
export const PORT_CLASS_NOTE: Record<PortClass, string> = {
  "1": "利用範囲が地元の漁業を主とするもの",
  "2": "第1種より広く、第3種に属しないもの",
  "3": "利用範囲が全国的なもの",
  special_3: "第3種のうち水産業の振興上とくに重要で政令で定めるもの",
  "4": "離島その他辺地にあって漁場の開発又は漁船の避難上とくに必要なもの",
};

/**
 * 種別の配色。
 *
 * 色だけに依存させない(SPEC N-05 / 実装仕様書 §3.4)。地図では半径も変え、
 * 凡例では種別名を必ず文字で出す。
 */
export const PORT_CLASS_COLOR: Record<PortClass, string> = {
  "1": "#7fb3d5",
  "2": "#4a90c2",
  "3": "#1f6f9c",
  special_3: "#d97706",
  "4": "#6b7f8c",
};

export const PORT_CLASS_RADIUS: Record<PortClass, number> = {
  "1": 2.6,
  "2": 3.4,
  "3": 5.0,
  special_3: 7.0,
  "4": 4.2,
};

/** 座標の突合段階(SPEC §6.2)。画面では「どうやって座標が付いたか」を出す。 */
export type GeometryMethod =
  | "code_name_pref"
  | "code_pref"
  | "name_pref"
  | "boundary_centroid"
  | null;

export const GEOMETRY_METHOD_LABEL: Record<string, string> = {
  code_name_pref: "漁港番号・港名・都道府県が一致",
  code_pref: "漁港番号と都道府県が一致(港名は2006年以降に変化)",
  name_pref: "同一県に同名の港が1つだけ",
  boundary_centroid: "漁港区域線の重心",
};

/** public/data/ports.min.json の 1 行。キーは配信量のため 1 文字。 */
export interface PortMin {
  id: string;
  n: string;
  k: string;
  p: string;
  m: string;
  c: PortClass;
  x: number | null;
  y: number | null;
  g: GeometryMethod;
}

const HIRAGANA_START = 0x3041;
const HIRAGANA_END = 0x3096;
const KANA_OFFSET = 0x60;

/**
 * 検索語・検索対象の正規化。
 *
 * NFKC で全角/半角と半角カナを畳み、ひらがなをカタカナへ寄せ、空白を落とす。
 * 読みの欄は PDF 由来で半角カナ(NFKC 済みで全角カナ)なので、
 * 利用者がひらがなで打っても引けるようにする。
 */
export function normalizeSearch(input: string): string {
  const nfkc = input.normalize("NFKC").toLowerCase();
  let out = "";
  for (const ch of nfkc) {
    const code = ch.codePointAt(0)!;
    if (code >= HIRAGANA_START && code <= HIRAGANA_END) {
      out += String.fromCodePoint(code + KANA_OFFSET);
    } else if (!/\s/.test(ch)) {
      out += ch;
    }
  }
  return out;
}

/** 1 港ぶんの検索対象文字列(港名・読み・都道府県・市町村)。 */
export function searchKey(port: PortMin): string {
  return normalizeSearch(`${port.n} ${port.k} ${port.p} ${port.m}`);
}

export interface FilterOptions {
  /** 空集合は「絞り込まない」。UI で全解除したときに 0 件にしない。 */
  classes?: ReadonlySet<PortClass>;
  query?: string;
  /** true なら座標を持つ港だけ返す(地図用) */
  requireCoordinates?: boolean;
}

export function filterPorts(
  ports: readonly PortMin[],
  options: FilterOptions = {},
): PortMin[] {
  const { classes, requireCoordinates } = options;
  const query = normalizeSearch(options.query ?? "");
  return ports.filter((port) => {
    if (classes && classes.size > 0 && !classes.has(port.c)) return false;
    if (requireCoordinates && (port.x === null || port.y === null)) return false;
    if (query && !searchKey(port).includes(query)) return false;
    return true;
  });
}

export interface PortFeature {
  type: "Feature";
  id: number;
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: {
    port_no: string;
    name: string;
    prefecture: string;
    municipality: string;
    port_class: PortClass;
    color: string;
    radius: number;
  };
}

export interface PortFeatureCollection {
  type: "FeatureCollection";
  features: PortFeature[];
}

/**
 * 地図用の GeoJSON。
 *
 * 座標を持たない港は feature を作らない —— (0, 0) に置くと
 * ギニア湾に日本の漁港が並ぶ(SPEC G-08: 欠損を 0 で埋めない)。
 */
export function toGeoJSON(ports: readonly PortMin[]): PortFeatureCollection {
  const features: PortFeature[] = [];
  let index = 0;
  for (const port of ports) {
    if (port.x === null || port.y === null) continue;
    features.push({
      type: "Feature",
      id: index++,
      geometry: { type: "Point", coordinates: [port.x, port.y] },
      properties: {
        port_no: port.id,
        name: port.n,
        prefecture: port.p,
        municipality: port.m,
        port_class: port.c,
        color: PORT_CLASS_COLOR[port.c],
        radius: PORT_CLASS_RADIUS[port.c],
      },
    });
  }
  return { type: "FeatureCollection", features };
}

/** 都道府県ごとの件数(一覧の見出し用)。順序は入力の出現順を保つ。 */
export function countByPrefecture(ports: readonly PortMin[]): Map<string, number> {
  const out = new Map<string, number>();
  for (const port of ports) out.set(port.p, (out.get(port.p) ?? 0) + 1);
  return out;
}

export function countByClass(ports: readonly PortMin[]): Record<PortClass, number> {
  const out = { "1": 0, "2": 0, "3": 0, special_3: 0, "4": 0 } as Record<
    PortClass,
    number
  >;
  for (const port of ports) out[port.c] += 1;
  return out;
}
