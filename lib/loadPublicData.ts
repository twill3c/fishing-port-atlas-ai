/**
 * ビルド時に public/data を読む(Server Component 用)。
 *
 * 画面に出す数はすべてここを通す —— 文書に手で書いた数は、実装のテストでは守られない
 * (HC-152)。生成物から読めば、パイプラインが動いたときに一緒に動く。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

const DATA_DIR = join(process.cwd(), "public", "data");

function read<T>(name: string): T {
  return JSON.parse(readFileSync(join(DATA_DIR, name), "utf-8")) as T;
}

export interface Stats {
  official: {
    as_of: string;
    total: number;
    by_class: Record<string, number>;
    special_class_3_names: string[];
  };
  built: {
    total: number;
    with_coordinates: number;
    by_geometry_method: Record<string, number>;
    by_class: Record<string, number>;
    by_prefecture: Record<string, number>;
  };
}

export interface SourceEntry {
  id: string;
  title: string;
  provider: string;
  url: string;
  retrieved: string;
  coverage: string;
  processed: boolean;
  processing: string;
  license: string;
  attribution: string;
}

export interface Manifest {
  build: string;
  schemaVersion: string;
  statusVocabulary: string[];
  datasets: Record<string, unknown>;
}

export const loadStats = () => read<Stats>("stats.json");
export const loadSources = () => read<SourceEntry[]>("sources.json");
export const loadManifest = () => read<Manifest>("manifest.json");

/** build_tsunami.py の meta と対応(SPEC §7.4) */
export interface TsunamiMeta {
  radii_m: number[];
  rank_order: string[];
  disclaimer: string;
  attribution: string;
  source_page: string;
  policy: Record<string, { page_class: string; policy: string; reason: string }>;
  vintages_by_prefecture: Record<string, number[]>;
}

export const loadTsunamiMeta = () => read<TsunamiMeta>("hazards/tsunami-meta.json");
