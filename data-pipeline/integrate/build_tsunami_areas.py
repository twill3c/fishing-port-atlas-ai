"""地図に重ねる津波浸水想定の区域の面を、港ごとに書き出す。SPEC §4 G-31〜G-33(loop_009、実測前に登録)。

## 何を配るか

- **半径の区分(build_tsunami.py)と同じ面**(`collect_polygons`: 年度の新しい面を優先し、古い面は切り取る)から作る
- 再配布してよい県の港のうち、**半径 500 m に区分がある港だけ**(G-33)
- 港ごとに、港の局所平面で半径 500 m の円で切り、同じ(区分・年度)の面を融合する
- 簡略化は局所平面で **1 m**、座標は小数 **6 桁**(G-32)。福井・岩手のプローブで 1 m の面積の変化は最大 0.32%

## 書き出す前に止める条件(黙って配らない)

- 簡略化した面から計算し直した半径 100 / 200 / 500 m の最大区分と年度が、表(tsunami_ports.json)と食い違う(G-31)
- 港ごとの面積の変化が 1% を超える(G-32)
- 1 港のファイルが 300 KB を超える(G-33)

## 再開

県ごとに済んだ印(data/interim/tsunami_areas/{県コード}.json、港ごとの報告を含む)を残し、再実行では済んだ県を飛ばす。
面のファイル(data/canonical/tsunami_areas/)は約 80 MB になるので Git に積まない。配信物(public/data/hazards/tsunami/)を積む。

使い方: python data-pipeline/integrate/build_tsunami_areas.py [--only 福井県 ...]
"""

from __future__ import annotations

import collections
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import shapely
from shapely import affinity, ops
from shapely.geometry import Point, mapping
from shapely.strtree import STRtree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.licenses import TSUNAMI_POLICY  # noqa: E402
from integrate.build_tsunami import (  # noqa: E402
    CANON,
    M_PER_DEG_LAT,
    RADII_M,
    RAW,
    collect_polygons,
    m_per_deg_lon,
)

ROOT = Path(__file__).resolve().parents[2]
AREAS = CANON / "tsunami_areas"
INTERIM = ROOT / "data" / "interim" / "tsunami_areas"
REPORT = CANON / "tsunami_areas_report.json"

SIMPLIFY_M = 1.0  # 上限。1 m で面積の変化が 1% を超える港だけ、下の段へ下げる(SPEC G-32、2026-09-17 改訂)
TOLERANCES_M = (1.0, 0.5, 0.25, 0.0)
COORD_DECIMALS = 6
MAX_AREA_CHANGE = 0.01
MAX_BYTES = 300_000
DISC_SEGMENTS = 32


class AreaError(RuntimeError):
    pass


def _local(geom, lon: float, lat: float):
    mx = m_per_deg_lon(lat)
    return affinity.affine_transform(geom, [mx, 0, 0, M_PER_DEG_LAT, -lon * mx, -lat * M_PER_DEG_LAT])


def _lonlat(geom, lon: float, lat: float):
    return affinity.affine_transform(geom, [1 / m_per_deg_lon(lat), 0, 0, 1 / M_PER_DEG_LAT, lon, lat])


def _polygonal(geom):
    """面(Polygon / MultiPolygon)だけを取り出す。GeometryCollection の線・点は捨てる。"""
    if geom.is_empty or geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    if geom.geom_type == "GeometryCollection":
        polys = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon") and not g.is_empty]
        return ops.unary_union(polys) if polys else Point(0, 0).buffer(0)
    return Point(0, 0).buffer(0)  # 線・点だけ = 面は無い


def _round(obj):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(v, COORD_DECIMALS) for v in obj]
        return [_round(v) for v in obj]
    return obj


def _max_rank(parts, order: list[str], radius: float):
    disc = Point(0, 0).buffer(radius, quad_segs=DISC_SEGMENTS)
    best = None
    for (label, year), geom in parts:
        if geom.is_empty or not geom.intersects(disc):
            continue
        cand = (order.index(label), year)
        if best is None or cand > best:
            best = cand
    return (None, None) if best is None else (order[best[0]], best[1])


def build_port(port: dict, kept: list, tree: STRtree, order: list[str], radii: list[dict]) -> tuple[bytes, dict]:
    lon, lat = port["lon"], port["lat"]
    disc_local = Point(0, 0).buffer(max(RADII_M), quad_segs=DISC_SEGMENTS)
    disc_ll = _lonlat(disc_local, lon, lat)
    grouped = collections.defaultdict(list)
    for i in tree.query(disc_ll):
        geom, label, year = kept[i]
        if geom.intersects(disc_ll):
            local = _local(geom, lon, lat)
            # 古い年度の面を新しい面で切り取った結果に、不正な形(自己交差など)が残ることがあり、
            # 交差で TopologyException になった(全国の構築で分かった)。地図用の面の側でだけ形を正す。
            # 半径の区分(collect_polygons の面)は変えない。正したことで区分が変わるなら G-31 の照合が止める
            if not local.is_valid:
                local = shapely.make_valid(local)
            grouped[(label, year)].append(_polygonal(local.intersection(disc_local)))

    # 円で切って融合すると、面に線や点の切れ端が混ざった GeometryCollection になる港がある
    # (全国の構築で落ちて分かった)。面だけを残す。捨てた切れ端で区分が変わるなら、下の G-31 の照合が止める
    base = {key: _polygonal(ops.unary_union(gs)) for key, gs in grouped.items()}
    base = {key: g for key, g in base.items() if not g.is_empty}
    keys = sorted(base, key=lambda k: (order.index(k[0]), k[1]))
    base_area = sum(g.area for g in base.values())

    def simplify_at(tol: float):
        parts = [(k, _polygonal(base[k].simplify(tol, preserve_topology=True)) if tol else base[k]) for k in keys]
        parts = [(k, g) for k, g in parts if not g.is_empty]
        change = abs(sum(g.area for _, g in parts) - base_area) / base_area if base_area else 0.0
        return parts, change

    # ---- G-32: 面積の変化。1 m で上限を超える港だけ幅を下げる(上限 1% は緩めない、2026-09-17 改訂)
    simplified, change_at_1m = simplify_at(TOLERANCES_M[0])
    tol_used, area_change = TOLERANCES_M[0], change_at_1m
    for tol in TOLERANCES_M[1:]:
        if area_change <= MAX_AREA_CHANGE:
            break
        simplified, area_change = simplify_at(tol)
        tol_used = tol
    if area_change > MAX_AREA_CHANGE:
        raise AreaError(f"{port['port_no']}: 簡略化しなくても面積が {area_change:.2%} 変わった(上限 1%)")

    # ---- G-31: 書き出す面から計算し直した区分が表と一致しなければ止める
    expected = {r["radius_m"]: (r["max_rank"], r["vintage"]) for r in radii}
    for radius in RADII_M:
        got = _max_rank(simplified, order, radius)
        if got != expected[radius]:
            raise AreaError(f"{port['port_no']}: 半径 {radius} m で面の区分 {got} が表 {expected[radius]} と食い違う(幅 {tol_used} m)")

    features = []
    for (label, year), geom in simplified:
        geo = mapping(_lonlat(geom, lon, lat))
        features.append({
            "type": "Feature",
            "properties": {"rank": label, "vintage": year},
            "geometry": {"type": geo["type"], "coordinates": _round(geo["coordinates"])},
        })
    body = json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    # ---- G-33: 大きさ
    if len(body) > MAX_BYTES:
        raise AreaError(f"{port['port_no']}: 面のファイルが {len(body):,} バイト(上限 {MAX_BYTES:,})")
    return body, {
        "simplify_m": tol_used,
        "area_change": area_change,
        "area_change_at_1m": change_at_1m,
        "bytes": len(body),
        "features": len(features),
    }


def build(only: list[str] | None = None) -> None:
    manifest = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))
    ports = json.loads((CANON / "ports.json").read_text(encoding="utf-8"))
    tsunami = json.loads((CANON / "tsunami_ports.json").read_text(encoding="utf-8"))
    order = tsunami["meta"]["rank_order"]

    by_pref: dict[str, list[dict]] = collections.defaultdict(list)
    for p in ports:
        by_pref[p["prefecture"]].append(p)
    zips_by_pref: dict[str, list[dict]] = collections.defaultdict(list)
    for f in manifest["files"]:
        zips_by_pref[f["prefecture"]].append(f)

    AREAS.mkdir(parents=True, exist_ok=True)
    INTERIM.mkdir(parents=True, exist_ok=True)
    for prefecture, entry in TSUNAMI_POLICY.items():
        if entry["policy"] != "redistribute" or prefecture not in by_pref:
            continue
        if only and prefecture not in only:
            continue
        targets = [
            p for p in by_pref[prefecture]
            if p["lat"] is not None
            and tsunami["ports"][p["port_no"]]["radii"] is not None
            and tsunami["ports"][p["port_no"]]["radii"][-1]["max_rank"] is not None
        ]
        done = INTERIM / f"{by_pref[prefecture][0]['pref_code']}.json"
        if done.exists():
            continue
        t0 = time.time()
        report: dict[str, dict] = {}
        if targets:
            with_coords = [p for p in by_pref[prefecture] if p["lat"] is not None]
            kept, _, _, _ = collect_polygons(prefecture, zips_by_pref[prefecture], with_coords)
            tree = STRtree([g for g, _, _ in kept])
            for port in targets:
                body, entry_report = build_port(port, kept, tree, order, tsunami["ports"][port["port_no"]]["radii"])
                (AREAS / f"{port['port_no']}.json").write_bytes(body)
                report[port["port_no"]] = entry_report
        done.write_text(json.dumps({"prefecture": prefecture, "ports": report}, ensure_ascii=False), encoding="utf-8")
        sizes = [r["bytes"] for r in report.values()] or [0]
        print(f"{prefecture}: 港 {len(report)} / 合計 {sum(sizes) / 1e6:.2f} MB / 最大 {max(sizes) / 1e3:.0f} KB / "
              f"面積の変化 最大 {max((r['area_change'] for r in report.values()), default=0):.4%} / {time.time() - t0:.0f}s", flush=True)

    if only:
        print("一部の県だけを作った。報告は書かない")
        return

    ports_report: dict[str, dict] = {}
    for done in sorted(INTERIM.glob("*.json")):
        ports_report.update(json.loads(done.read_text(encoding="utf-8"))["ports"])
    written = {p.stem for p in AREAS.glob("*.json")}
    if written != set(ports_report):
        raise AreaError(f"面のファイルと報告の港が一致しない: ファイルだけ {sorted(written - set(ports_report))[:5]} / 報告だけ {sorted(set(ports_report) - written)[:5]}")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "radius_m": max(RADII_M),
        "simplify_m": SIMPLIFY_M,
        "coord_decimals": COORD_DECIMALS,
        "max_area_change": max(r["area_change"] for r in ports_report.values()),
        "total_bytes": sum(r["bytes"] for r in ports_report.values()),
        "max_bytes": max(r["bytes"] for r in ports_report.values()),
        "ports": dict(sorted(ports_report.items())),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"港 {len(ports_report):,} / 合計 {report['total_bytes'] / 1e6:.1f} MB / 最大 {report['max_bytes'] / 1e3:.0f} KB / "
          f"面積の変化 最大 {report['max_area_change']:.4%} -> {REPORT}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="この県だけ作る(試し用。報告は書かない)")
    args = ap.parse_args()
    build(only=args.only)
