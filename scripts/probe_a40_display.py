"""L0 実測用プローブ: 津波浸水想定をどう出すかを、福井県(A40-23_18)で測って決める。

前段(probe_a40.py)で、漁港の代表点の 42/44 が浸水想定区域の外(中央値 47 m)にあると分かった。
代表点は水際にあり、陸を覆う区域の外に落ちる。点の内外をそのまま出すと偽の「区域外」になる。

候補を二つ測る:

(a) 半径 R m 以内の最大浸水深区分 —— R を 100 / 200 / 500 m と変えたとき、
    答え(区分)がどれだけ変わるか。変わりやすければ R の選び方が結論を決めてしまう
(b) 区域そのものを地図に重ねる —— 深さ区分ごとにまとめて簡略化したとき、
    配信量がどれだけ減り、面積がどれだけ変わるか

出力は標準出力だけ。
"""

from __future__ import annotations

import collections
import json
import math
import time
from pathlib import Path

import numpy as np
import shapefile
from shapely import ops
from shapely.geometry import Point, mapping, shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
SHP = ROOT / "data" / "raw" / "ksj" / "A40" / "A40-23_18_GML" / "A40-23_18_GML" / "A40-23_18"

# 福井県で実測した区分(probe_a40.py、2026-09-14)。浅い順。未知の区分は例外にする
RANKS = ["～0.3m", "0.3～0.5m", "0.5～1m", "1～3m", "3～5m", "5m～"]
RADII_M = (100, 200, 500)
TOLERANCES_M = (1, 3, 10)


def geojson_bytes(geom) -> int:
    def round_coords(obj):
        if isinstance(obj, (list, tuple)):
            if obj and isinstance(obj[0], (int, float)):
                return [round(obj[0], 6), round(obj[1], 6)]
            return [round_coords(o) for o in obj]
        return obj

    m = mapping(geom)
    return len(json.dumps({"type": m["type"], "coordinates": round_coords(m["coordinates"])},
                          separators=(",", ":")))


def vertex_count(geom) -> int:
    if geom.is_empty:
        return 0
    polys = getattr(geom, "geoms", [geom])
    return sum(len(p.exterior.coords) + sum(len(r.coords) for r in p.interiors) for p in polys)


def main() -> None:
    reader = shapefile.Reader(str(SHP), encoding="cp932")
    records = list(reader.iterRecords())
    shapes = reader.shapes()
    reader.close()

    unknown = {r[2] for r in records} - set(RANKS)
    if unknown:
        raise SystemExit(f"未知の浸水深区分: {unknown}")

    lat0 = float(np.mean([s.bbox[1] for s in shapes]))
    kx = 111_320 * math.cos(math.radians(lat0))
    ky = 110_574

    def to_m(x, y, z=None):
        return (np.asarray(x) * kx, np.asarray(y) * ky)

    t0 = time.time()
    by_rank: dict[str, list] = collections.defaultdict(list)
    geoms_m, ranks = [], []
    for rec, shp in zip(records, shapes):
        g = shape(shp.__geo_interface__)
        by_rank[rec[2]].append(g)
        geoms_m.append(ops.transform(to_m, g))
        ranks.append(RANKS.index(rec[2]))
    print(f"面 {len(records)} を読み込み {time.time() - t0:.1f}s(局所平面の基準緯度 {lat0:.3f})")

    # ---------------- (b) まとめて簡略化 ----------------
    raw_bytes = sum(geojson_bytes(g) for gs in by_rank.values() for g in gs)
    raw_vertices = sum(vertex_count(g) for gs in by_rank.values() for g in gs)
    print(f"\n(b) 元のまま: GeoJSON 相当 {raw_bytes / 1e6:.2f} MB / 頂点 {raw_vertices:,}")
    t0 = time.time()
    dissolved = {r: ops.unary_union(by_rank[r]) for r in RANKS if by_rank[r]}
    print(f"区分ごとに結合 {time.time() - t0:.1f}s: "
          f"{sum(geojson_bytes(g) for g in dissolved.values()) / 1e6:.2f} MB / "
          f"頂点 {sum(vertex_count(g) for g in dissolved.values()):,}")
    for tol_m in TOLERANCES_M:
        tol_deg = tol_m / ky
        simplified = {r: g.simplify(tol_deg, preserve_topology=True) for r, g in dissolved.items()}
        size = sum(geojson_bytes(g) for g in simplified.values())
        verts = sum(vertex_count(g) for g in simplified.values())
        worst = max(
            abs(simplified[r].area - dissolved[r].area) / dissolved[r].area * 100
            for r in dissolved
        )
        sym = max(
            simplified[r].symmetric_difference(dissolved[r]).area / dissolved[r].area * 100
            for r in dissolved
        )
        print(f"  簡略化 {tol_m:>2} m: {size / 1e6:.2f} MB / 頂点 {verts:,} / "
              f"区分ごとの面積差 最大 {worst:.2f}% / 形のずれ(対称差/面積)最大 {sym:.2f}%")

    # ---------------- (a) 半径 R 以内の最大区分 ----------------
    tree = STRtree(geoms_m)
    ports = json.loads((ROOT / "data" / "canonical" / "ports.json").read_text(encoding="utf-8"))
    mine = [p for p in ports if p["prefecture"] == "福井県" and p["lat"] is not None]
    answers: dict[int, list[int | None]] = {}
    for radius in RADII_M:
        row = []
        for port in mine:
            px, py = to_m(port["lon"], port["lat"])
            disc = Point(float(px), float(py)).buffer(radius)
            hits = [ranks[i] for i in tree.query(disc) if geoms_m[i].intersects(disc)]
            row.append(max(hits) if hits else None)
        answers[radius] = row
        dist = collections.Counter("区域なし" if a is None else RANKS[a] for a in row)
        print(f"\n(a) R={radius} m: 港 {len(row)} の最大区分 {dict(sorted(dist.items()))}")
    for a, b in ((100, 200), (200, 500)):
        changed = sum(1 for x, y in zip(answers[a], answers[b]) if x != y)
        print(f"R={a} → R={b} で区分が変わった港: {changed}/{len(mine)}")


if __name__ == "__main__":
    main()
