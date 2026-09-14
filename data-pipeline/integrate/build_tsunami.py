"""漁港ごとの津波浸水想定(半径 100 / 200 / 500 m の最大浸水深区分)を作る。SPEC §7.4 / G-19〜G-22。

## 何を出し、何を出さないか

- **代表点が区域の内か外かは出さない**(G-19)。福井県で代表点の 42/44 が区域外(中央値 47 m)だった
- **半径を一つに決めない**(G-20)。100 / 200 / 500 m の最大区分を並べる
- 使うのは**その港の都道府県のデータだけ**。県境の近くでは隣県の区域を見ていない(注記する)

## 計算の決めごと(実測より前に固定した)

- 距離は**港ごとの局所平面**で測る。港の緯度で経度方向を縮め、港を原点にした平面へ面を移して、
  半径の円と交わるかを見る
- 年度違いは、**新しい年度の面が覆う範囲を優先**し、古い年度の面はそこから切り取った残りだけを使う
  (A40 ページ「重複する箇所は最新年度を」)。県ごとに面の集合を一つにしてから半径で引くので、
  半径が大きいほど最大区分は下がらない(G-20 の単調性)が構造上成り立つ
- 区分ラベルは**浸水深の区間(下限・上限)に読み**、表示は区間から作り直した一つの書き方にそろえる。
  並びは下限、次に上限の順。**読めない書式は、その記録を読んだ時点で止める**

## 区分ラベルの書式(実測 2026-09-14、全 51 ファイル・60 種)

`～0.3m` / `0.3～0.5m` / `5m～` / `0.01～0.3m` / `5.0m～` / `1m以上 ～ 3m未満` / `20m以上` /
`0.3m未満` / `～ 0.3m未満` / `0.01m以上 0.3m未満`(波ダッシュ無し)/ `0.01m以上～0.3m未満\\n`(末尾に改行)。
最初は福井県 1 県の語彙だけで規則を書き、北海道の `1m以上 ～ 3m未満` で止まった(PROC-SKIP)。

## 速さ

面は全体で 5,303,091 ある。形を全部読むと遅いので、`.shx` から各レコードの位置を取り、
`.shp` から**外接矩形の 4 数だけ**をまとめて読み、港の 500 m 圏の矩形に掛かる面だけ形を読む。
県ごとの途中結果を data/interim/tsunami/ に保存し、再実行では済んだ県を飛ばす。
"""

from __future__ import annotations

import collections
import json
import math
import re
import sys
import time
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import shapefile
from shapely import ops
from shapely.geometry import Point, box, shape
from shapely.strtree import STRtree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.licenses import A40_ATTRIBUTION, A40_PAGE_URL, TSUNAMI_POLICY  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "ksj" / "A40"
INTERIM = ROOT / "data" / "interim" / "tsunami"
CANON = ROOT / "data" / "canonical"

RADII_M = (100, 200, 500)
M_PER_DEG_LAT = 110_574
EXPECTED_FIELDS = ["A40_001", "A40_002", "A40_003"]


def m_per_deg_lon(lat: float) -> float:
    return 111_320 * math.cos(math.radians(lat))


DISCLAIMER = (
    "この情報は国土数値情報の津波浸水想定を加工した参考情報で、被害を予測するものではない。"
    "津波浸水想定は、最大クラスの津波が悪条件下で発生した場合に想定される浸水の区域と深さで、"
    "これより大きな津波が起きないというものではない。第二波以降に最大となる場所もある。"
    "避難の判断には、自治体・気象庁・国土交通省の最新の公式な防災情報を使うこと。"
)

NOTE_WITH_VALUES = (
    "漁港の代表点から半径 100 / 200 / 500 m の円に、津波浸水想定の区域が掛かるかと、"
    "掛かる区域の最大浸水深の区分。代表点が区域の内か外かは出していない(代表点は水際にあり、"
    "陸を覆う区域の外に落ちるため)。区域が掛からない半径があっても、安全という意味ではない。"
    "隣の都道府県の区域は見ていない。区分の刻みは都道府県・年度によって違う。"
)


class TsunamiError(RuntimeError):
    pass


# ------------------------------------------------------------------ 区分ラベル

_NUM = r"(\d+(?:\.\d+)?)"
_PATTERNS = (
    # 順番に意味がある: 「以上~未満」の組を、片側だけの形より先に見る
    (rf"{_NUM}m?以上~?{_NUM}m?未満", lambda a, b: (float(a), float(b))),
    (rf"~?{_NUM}m?未満", lambda b: (0.0, float(b))),
    (rf"{_NUM}m?以上", lambda a: (float(a), math.inf)),
    (rf"~{_NUM}m", lambda b: (0.0, float(b))),
    (rf"{_NUM}m?~{_NUM}m", lambda a, b: (float(a), float(b))),
    (rf"{_NUM}m~", lambda a: (float(a), math.inf)),
)


def _normalize_label(label: str) -> str:
    s = unicodedata.normalize("NFKC", label)
    s = re.sub(r"\s+", "", s)  # 空白・改行(岡山 2016 は末尾に \n が入っている)
    return s.replace("〜", "~").replace("～", "~")


def parse_rank_label(label: str) -> tuple[float, float]:
    """区分ラベルから浸水深の区間(下限, 上限)を読む。読めない書式は例外にする(HC-075)。"""
    s = _normalize_label(label)
    for pattern, build in _PATTERNS:
        m = re.fullmatch(pattern, s)
        if m:
            low, high = build(*m.groups())
            if not low < high:
                raise TsunamiError(f"区間が壊れている: {label!r} -> {low}, {high}")
            return low, high
    raise TsunamiError(f"浸水深の区分ラベルが読めない: {label!r}")


def canonical_label(label: str) -> str:
    """区間から作り直した表示用のラベル。同じ区間の別表記は同じ文字列になる。"""
    low, high = parse_rank_label(label)
    if low == 0:
        return f"〜{high:g}m"
    if math.isinf(high):
        return f"{low:g}m〜"
    return f"{low:g}〜{high:g}m"


def rank_order(labels) -> list[str]:
    """表示用ラベルを、下限、次に上限の順(浅い → 深い)に並べる。"""
    canon = {canonical_label(label) for label in labels}
    return sorted(canon, key=parse_rank_label)


def strictly_nested_pairs(labels) -> list[tuple[str, str]]:
    """(外, 内) の組: 内の区分の下限が外より大きく、上限が外より小さい。

    rank_order の最大が最大浸水深の区間と一致するのは、この組が無いときだけ。
    年度の違う刻みが同じ県に混ざると区間は重なるが、境界を共有するか部分的に重なるだけなら最大は正しい。
    """
    intervals = [(label, parse_rank_label(label)) for label in rank_order(labels)]
    return [
        (outer, inner)
        for outer, (o_low, o_high) in intervals
        for inner, (i_low, i_high) in intervals
        if o_low < i_low and i_high < o_high
    ]


# ------------------------------------------------------------------ 半径検索(単体テストが見る)


@dataclass
class Index:
    geoms: list
    ranks: list[int]
    vintages: list[int]
    tree: STRtree


def build_index(items: list[tuple]) -> Index:
    """items: (経緯度の面, 区分の順位, 年度) の並び。"""
    geoms = [g for g, _, _ in items]
    return Index(geoms, [r for _, r, _ in items], [v for _, _, v in items], STRtree(geoms))


def max_rank_within(index: Index, lon: float, lat: float, radius_m: float) -> tuple[int | None, int | None]:
    """港の局所平面で半径 radius_m の円に掛かる面のうち、最も深い区分(と、その面の年度)。

    同じ深さの面が複数の年度にあれば新しい年度を返す。掛かる面が無ければ (None, None)。
    """
    mx, my = m_per_deg_lon(lat), M_PER_DEG_LAT
    query = box(lon - radius_m / mx, lat - radius_m / my, lon + radius_m / mx, lat + radius_m / my)
    disc = Point(0.0, 0.0).buffer(radius_m, quad_segs=32)

    def to_local(x, y, z=None):
        if hasattr(x, "__len__"):
            return [(xi - lon) * mx for xi in x], [(yi - lat) * my for yi in y]
        return (x - lon) * mx, (y - lat) * my

    best: tuple[int, int] | None = None
    for i in index.tree.query(query):
        if not ops.transform(to_local, index.geoms[i]).intersects(disc):
            continue
        candidate = (index.ranks[i], index.vintages[i])
        if best is None or candidate > best:
            best = candidate
    return (best[0], best[1]) if best else (None, None)


# ------------------------------------------------------------------ shapefile の読み出し


def _extract(zip_path: Path) -> Path:
    dest = RAW / zip_path.stem
    with zipfile.ZipFile(zip_path) as archive:
        members = [n for n in archive.namelist() if n.lower().endswith((".shp", ".shx", ".dbf", ".prj", ".cpg"))]
        shp_members = [n for n in members if n.lower().endswith(".shp")]
        if len(shp_members) != 1:
            raise TsunamiError(f"{zip_path.name} の shp が 1 本でない: {shp_members}")
        target = dest / shp_members[0]
        if not target.exists():
            archive.extractall(dest, members=members)
    return target


def _open_reader(shp: Path, prefecture: str) -> shapefile.Reader:
    """文字コードは実物で確かめる: 都道府県名の欄が期待どおりに読めるほうを採る。"""
    for encoding in ("cp932", "utf-8"):
        reader = shapefile.Reader(str(shp.with_suffix("")), encoding=encoding, encodingErrors="strict")
        try:
            names = [f[0] for f in reader.fields[1:]]
            if names != EXPECTED_FIELDS:
                raise TsunamiError(f"{shp.name}: 属性の列が想定と違う {names}")
            if reader.record(0)[0] == prefecture:
                return reader
        except UnicodeDecodeError:
            pass
        reader.close()
    raise TsunamiError(f"{shp.name}: 都道府県名 {prefecture} を読める文字コードが無い")


def shape_bboxes(shp: Path) -> np.ndarray:
    """全レコードの外接矩形 (xmin, ymin, xmax, ymax) を、形を読まずにまとめて読む。

    .shx の各レコード(8 バイト、ビッグエンディアン)の先頭 4 バイトが .shp 内の位置(16 ビット語単位)。
    .shp の各レコードは 8 バイトのヘッダ、4 バイトの形の種類(リトルエンディアン)、
    続いて外接矩形の double 4 つ。種類が面(5)でないレコードがあれば止める。
    """
    shx = shp.with_suffix(".shx").read_bytes()
    offsets = np.frombuffer(shx, dtype=">i4", offset=100).reshape(-1, 2)[:, 0].astype(np.int64) * 2
    data = np.memmap(shp, dtype=np.uint8, mode="r")
    kinds = data[offsets[:, None] + 8 + np.arange(4)].copy().view("<i4").ravel()
    if not np.all(kinds == 5):
        raise TsunamiError(f"{shp.name}: 面(5)でないレコードがある {sorted(set(kinds.tolist()))}")
    raw = data[offsets[:, None] + 12 + np.arange(32)].copy()
    return raw.view("<f8").reshape(-1, 4)


def build_prefecture(prefecture: str, zips: list[dict], ports: list[dict]) -> dict:
    with_coords = [p for p in ports if p["lat"] is not None]
    if not with_coords:
        return {"prefecture": prefecture, "labels": {}, "vintages": [], "stats": {}, "ports": {}}

    reach = max(RADII_M) * 1.05
    port_boxes = np.array([
        (p["lon"] - reach / m_per_deg_lon(p["lat"]), p["lat"] - reach / M_PER_DEG_LAT,
         p["lon"] + reach / m_per_deg_lon(p["lat"]), p["lat"] + reach / M_PER_DEG_LAT)
        for p in with_coords
    ])

    labels: collections.Counter = collections.Counter()
    canonical_cache: dict[str, str] = {}
    kept: list[tuple] = []  # (面, 表示ラベル, 年度)
    newer_geoms: list = []
    stats = {"polygons_total": 0, "polygons_near_ports": 0, "clipped": 0, "dropped_by_newer": 0}

    for entry in sorted(zips, key=lambda z: -z["year"]):
        shp = _extract(RAW / entry["file"])
        bboxes = shape_bboxes(shp)
        stats["polygons_total"] += len(bboxes)
        near = np.zeros(len(bboxes), dtype=bool)
        for xmin, ymin, xmax, ymax in port_boxes:
            near |= (bboxes[:, 0] <= xmax) & (bboxes[:, 2] >= xmin) & (bboxes[:, 1] <= ymax) & (bboxes[:, 3] >= ymin)
        selected = np.flatnonzero(near)

        reader = _open_reader(shp, prefecture)
        if len(reader) != len(bboxes):
            raise TsunamiError(f"{shp.name}: .dbf {len(reader)} 行と .shx {len(bboxes)} 件が合わない")
        newer_tree = STRtree(newer_geoms) if newer_geoms else None
        this_vintage = []
        for i in selected.tolist():
            rec = reader.record(i)
            if rec[0] != prefecture:
                raise TsunamiError(f"{entry['file']}#{i}: 別の都道府県の行 {rec[0]!r}")
            raw_label = rec[2]
            if raw_label not in canonical_cache:
                canonical_cache[raw_label] = canonical_label(raw_label)  # 読めない書式はここで止まる
            label = canonical_cache[raw_label]
            geom = shape(reader.shape(i).__geo_interface__)
            if not geom.is_valid:
                geom = geom.buffer(0)
            stats["polygons_near_ports"] += 1
            if newer_tree is not None:
                overlapping = [newer_geoms[j] for j in newer_tree.query(geom) if newer_geoms[j].intersects(geom)]
                if overlapping:
                    geom = geom.difference(ops.unary_union(overlapping))
                    stats["clipped"] += 1
                    if geom.is_empty:
                        stats["dropped_by_newer"] += 1
                        continue
            labels[label] += 1
            this_vintage.append(geom)
            kept.append((geom, label, entry["year"]))
        reader.close()
        newer_geoms.extend(this_vintage)

    order = rank_order(labels)
    nested = strictly_nested_pairs(labels)
    if nested:
        raise TsunamiError(f"{prefecture}: 区分が別の区分に真に含まれ、最大が決まらない {nested}")
    index = build_index([(g, order.index(label), year) for g, label, year in kept]) if kept else None

    out_ports = {}
    for port in with_coords:
        radii = []
        for radius in RADII_M:
            rank, vintage = max_rank_within(index, port["lon"], port["lat"], radius) if index else (None, None)
            radii.append({"radius_m": radius, "max_rank": None if rank is None else order[rank], "vintage": vintage})
        out_ports[port["port_no"]] = radii
    return {
        "prefecture": prefecture,
        "labels": dict(labels),
        "raw_labels": sorted(canonical_cache),
        "vintages": sorted({z["year"] for z in zips}, reverse=True),
        "stats": stats,
        "ports": out_ports,
    }


# ------------------------------------------------------------------ 全体


def build(only: list[str] | None = None) -> Path:
    manifest = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))
    ports = json.loads((CANON / "ports.json").read_text(encoding="utf-8"))
    by_pref: dict[str, list[dict]] = collections.defaultdict(list)
    for p in ports:
        by_pref[p["prefecture"]].append(p)
    zips_by_pref: dict[str, list[dict]] = collections.defaultdict(list)
    for f in manifest["files"]:
        zips_by_pref[f["prefecture"]].append(f)

    INTERIM.mkdir(parents=True, exist_ok=True)
    results = {}
    for prefecture, entry in TSUNAMI_POLICY.items():
        if entry["policy"] != "redistribute" or prefecture not in by_pref:
            continue
        if only and prefecture not in only:
            continue
        if prefecture not in zips_by_pref:
            raise TsunamiError(f"{prefecture}: 出す県なのに取得済みの zip が無い(fetch_a40.py を先に)")
        cache = INTERIM / f"{by_pref[prefecture][0]['pref_code']}.json"
        if cache.exists():
            results[prefecture] = json.loads(cache.read_text(encoding="utf-8"))
            continue
        t0 = time.time()
        result = build_prefecture(prefecture, zips_by_pref[prefecture], by_pref[prefecture])
        cache.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        results[prefecture] = result
        s = result["stats"]
        print(f"{prefecture}: 面 {s.get('polygons_total', 0):,} のうち港の近く {s.get('polygons_near_ports', 0):,} / "
              f"年度で切り取り {s.get('clipped', 0):,}(消えた {s.get('dropped_by_newer', 0):,})/ "
              f"区分 {rank_order(result['labels']) if result['labels'] else []} / {time.time() - t0:.0f}s", flush=True)

    if only:
        print("一部の県だけを作った。canonical は書かない")
        return INTERIM

    order = rank_order(label for r in results.values() for label in r["labels"])
    out_ports = {}
    for p in ports:
        policy = TSUNAMI_POLICY[p["prefecture"]]["policy"]
        record = {"prefecture": p["prefecture"], "policy": policy, "radii": None}
        if policy == "redistribute":
            radii = results[p["prefecture"]]["ports"].get(p["port_no"])
            record["radii"] = radii
            record["note"] = NOTE_WITH_VALUES if radii is not None else "座標が無いので、区域との位置関係を求めていない"
        elif policy == "link_only":
            record["note"] = f"{p['prefecture']}のデータは再配布に事前の連絡が要るため載せていない。県と国土数値情報の公式な情報を見ること"
        elif policy == "not_provided":
            record["note"] = "国土数値情報として津波浸水想定が提供されていない"
        else:
            record["note"] = "津波浸水想定の配布が無い"
        out_ports[p["port_no"]] = record

    canonical = {
        "meta": {
            "radii_m": list(RADII_M),
            "rank_order": order,
            "disclaimer": DISCLAIMER,
            "attribution": A40_ATTRIBUTION,
            "source_page": A40_PAGE_URL,
            "policy": TSUNAMI_POLICY,
            "vintages_by_prefecture": {k: v["vintages"] for k, v in results.items()},
            # 県ごとの区分の集合(T-049 が真に含まれる組を見る)。中間結果は積まないので、ここに残す。
            # 全国の rank_order は表示の並びで、県をまたいだ深さの比較には使わない
            "labels_by_prefecture": {k: rank_order(v["labels"]) for k, v in results.items()},
        },
        "ports": out_ports,
    }
    CANON.mkdir(parents=True, exist_ok=True)
    out = CANON / "tsunami_ports.json"
    out.write_text(json.dumps(canonical, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"区分の並び: {order}")
    print(f"港 {len(out_ports)} -> {out}")
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="この県だけ作る(試し用。canonical は書かない)")
    args = ap.parse_args()
    build(only=args.only)
