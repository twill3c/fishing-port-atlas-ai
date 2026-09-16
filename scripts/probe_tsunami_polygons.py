"""L0 実測用プローブ(loop_009): 津波浸水想定の区域の面を、港ごとに地図へ重ねて配れるかを測る。

製品のコードではない。配り方と合否の規則を SPEC に書く前に、次を測る。

1. collect_polygons への切り出しで構築の結果が変わっていないか(中間結果と港ごとに照合)
2. 港ごとに半径 500 m の円で切り、同じ(区分・年度)の面を融合した GeoJSON の大きさ(圧縮前後)
3. 簡略化(0 / 1 / 3 m、港の局所平面で)で変わる面積の割合
4. **表との一致(別経路)**: 切った面から半径 100 / 200 / 500 m の最大区分を計算し直し、
   防災タブの値(中間結果)と一致するか。簡略化の度合いごとに
5. 全国の見積もり(港の近くの面の枚数の比で伸ばす)

使い方: python scripts/probe_tsunami_polygons.py 福井県 [他の県 ...]
"""

from __future__ import annotations

import collections
import gzip
import json
import statistics
import sys
import time
from pathlib import Path

from shapely import affinity, ops
from shapely.geometry import Point, mapping
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data-pipeline"))

from integrate.build_tsunami import (  # noqa: E402
    CANON,
    INTERIM,
    M_PER_DEG_LAT,
    RADII_M,
    RAW,
    build_prefecture,
    collect_polygons,
    m_per_deg_lon,
    rank_order,
)

TOLERANCES_M = (0.0, 1.0, 3.0)
NATIONAL_NEAR_PORT_POLYGONS = 515_346  # summarize_tsunami.py の合計(2026-09-14)


def to_local(geom, lon, lat):
    return affinity.affine_transform(geom, [m_per_deg_lon(lat), 0, 0, M_PER_DEG_LAT, -lon * m_per_deg_lon(lat), -lat * M_PER_DEG_LAT])


def to_lonlat(geom, lon, lat):
    return affinity.affine_transform(geom, [1 / m_per_deg_lon(lat), 0, 0, 1 / M_PER_DEG_LAT, lon, lat])


def round_coords(obj, nd=6):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(v, nd) for v in obj]
        return [round_coords(v, nd) for v in obj]
    return obj


def feature_collection(parts, lon, lat):
    feats = []
    for (label, year), geom_local in parts:
        geo = mapping(to_lonlat(geom_local, lon, lat))
        feats.append({"type": "Feature", "properties": {"rank": label, "vintage": year},
                      "geometry": {"type": geo["type"], "coordinates": round_coords(geo["coordinates"])}})
    return {"type": "FeatureCollection", "features": feats}


def max_rank(parts, order, radius):
    disc = Point(0, 0).buffer(radius, quad_segs=32)
    best = None
    for (label, year), geom in parts:
        if geom.is_empty or not geom.intersects(disc):
            continue
        cand = (order.index(label), year)
        if best is None or cand > best:
            best = cand
    return (None, None) if best is None else (order[best[0]], best[1])


def main(prefectures: list[str]) -> None:
    manifest = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))
    ports = json.loads((CANON / "ports.json").read_text(encoding="utf-8"))
    national_near = 0
    for pref in prefectures:
        t0 = time.time()
        zips = [f for f in manifest["files"] if f["prefecture"] == pref]
        pref_ports = [p for p in ports if p["prefecture"] == pref]
        with_coords = [p for p in pref_ports if p["lat"] is not None]
        cache = INTERIM / f"{pref_ports[0]['pref_code']}.json"
        cached = json.loads(cache.read_text(encoding="utf-8"))

        # ---- 1. 切り出しの回帰
        rebuilt = build_prefecture(pref, zips, pref_ports)
        print(f"\n=== {pref}: 港 {len(with_coords)}")
        print(f"[1] 構築し直した港ごとの区分が中間結果と一致: {rebuilt['ports'] == cached['ports']}")

        kept, labels, _, stats = collect_polygons(pref, zips, with_coords)
        order = rank_order(labels)
        national_near += stats["polygons_near_ports"]
        tree = STRtree([g for g, _, _ in kept])

        sizes = {t: [] for t in TOLERANCES_M}
        gz = {t: [] for t in TOLERANCES_M}
        area_change = {t: [] for t in TOLERANCES_M}
        mismatch = {t: collections.Counter() for t in TOLERANCES_M}
        feature_counts = []
        for port in with_coords:
            lon, lat = port["lon"], port["lat"]
            disc_local = Point(0, 0).buffer(max(RADII_M), quad_segs=32)
            disc_ll = to_lonlat(disc_local, lon, lat)
            grouped = collections.defaultdict(list)
            for i in tree.query(disc_ll):
                geom, label, year = kept[i]
                if not geom.intersects(disc_ll):
                    continue
                grouped[(label, year)].append(to_local(geom, lon, lat).intersection(disc_local))
            base = {key: ops.unary_union(gs) for key, gs in grouped.items()}
            base = {k: g for k, g in base.items() if not g.is_empty}
            feature_counts.append(len(base))
            base_area = sum(g.area for g in base.values())
            expected = {r["radius_m"]: (r["max_rank"], r["vintage"]) for r in cached["ports"][port["port_no"]]}
            for tol in TOLERANCES_M:
                parts = [(k, g.simplify(tol, preserve_topology=True) if tol else g) for k, g in sorted(base.items())]
                body = json.dumps(feature_collection(parts, lon, lat), ensure_ascii=False, separators=(",", ":")).encode()
                sizes[tol].append(len(body))
                gz[tol].append(len(gzip.compress(body)))
                if base_area > 0:
                    area_change[tol].append(abs(sum(g.area for _, g in parts) - base_area) / base_area)
                for radius in RADII_M:
                    if max_rank(parts, order, radius) != expected[radius]:
                        mismatch[tol][radius] += 1

        print(f"[2] (区分・年度)ごとに融合した面の数/港: 中央値 {statistics.median(feature_counts)} 最大 {max(feature_counts)}")
        for tol in TOLERANCES_M:
            s = sorted(sizes[tol])
            g = sorted(gz[tol])
            print(f"    簡略化 {tol:g} m: 合計 {sum(s) / 1e6:.2f} MB(gzip {sum(g) / 1e6:.2f} MB)"
                  f" / 港あたり 中央値 {statistics.median(s) / 1e3:.1f} KB・95% {s[int(len(s) * 0.95)] / 1e3:.1f} KB・最大 {s[-1] / 1e3:.1f} KB")
        for tol in TOLERANCES_M[1:]:
            a = sorted(area_change[tol])
            print(f"[3] 簡略化 {tol:g} m の面積の変化: 中央値 {statistics.median(a):.4%} 最大 {a[-1]:.4%}")
        for tol in TOLERANCES_M:
            print(f"[4] 簡略化 {tol:g} m で表と食い違う港: " + " / ".join(f"R={r} {mismatch[tol][r]}" for r in RADII_M))
        ratio = NATIONAL_NEAR_PORT_POLYGONS / stats["polygons_near_ports"]
        print(f"[5] 港の近くの面 {stats['polygons_near_ports']:,} → 全国 {NATIONAL_NEAR_PORT_POLYGONS:,}(×{ratio:.0f})で伸ばすと、"
              + " / ".join(f"{t:g} m: {sum(sizes[t]) * ratio / 1e6:.0f} MB(gzip {sum(gz[t]) * ratio / 1e6:.0f} MB)" for t in TOLERANCES_M))
        print(f"    所要 {time.time() - t0:.0f} 秒")


if __name__ == "__main__":
    main(sys.argv[1:] or ["福井県"])
