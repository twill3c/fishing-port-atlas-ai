"""漁港マスタ(canonical)を作る。

## 主キー

仕様書 §13.1 は `JP-FP-{pref_code}-{sequence}` という**新規に採番する ID** を定めていたが、
実測の結果、水産庁の明細 PDF も国土数値情報 C09 も **7 桁の「漁港番号」**を持ち、
両者は同じ体系である(2,768 港中 2,676 港が番号で一致し、うち 97.46% は港名も一致。
実測 2026-09-08)。採番し直すと出所への遡行が切れるので、**漁港番号を主キーにする**。

## 座標の由来と信頼度

C09(平成18年度 = 2006 年)は 2026 年のマスタより 20 年古い。番号が一致しても
別の港に振り替わっている場合があるため、突合を段階に分け、`geometry_method` に
どの段階で付いた座標かを残す。

- `code_name_pref`: 漁港番号・港名・都道府県がすべて一致(最も強い)
- `code_pref`: 漁港番号と都道府県が一致(港名は 2006 年以降に変わった可能性)
- `name_pref`: 番号は一致しないが、同一都道府県に同名の港が 1 つだけある
- `boundary_centroid`: 点レイヤに無いが漁港区域線があり、その重心が
  **同一都道府県で既に座標が付いた港の外接矩形 +0.5 度**に入る
- なし: 座標を付けない(`lat`/`lon` は null。0 で埋めない)

`boundary_centroid` の外接矩形ガードは飾りではない —— 実測(2026-09-08)で
石川県「中島」(2410125)の区域線が 35.611N/134.467E(石川県の外接矩形の外)を指しており、
このガードが実際に落とした。区域線側にも点レイヤと同じコード衝突がある。

C09 には**漁港番号が重複する 30 コード**があり、重複行では港名・管理者・指定年月日が
別の港のものに置き換わっている(例: 1410690「宇島」が福岡県豊前市と宮城県石巻市の
2 点を持つ。実測 2026-09-08)。よって重複コードは、市区町村コードの上 2 桁が
都道府県と一致する候補が**ちょうど 1 つ**のときだけ採用する。
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import shapefile

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.prefectures import CODE_PREF, PREF_CODE  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
NORM = ROOT / "data" / "normalized"
RAW = ROOT / "data" / "raw"
CANON = ROOT / "data" / "canonical"

C09_POINT = RAW / "ksj" / "C09-06" / "C09-06_FishingPort"
C09_BOUNDARY = RAW / "ksj" / "C09-06" / "C09-06_FishingPortBoundary"

# 区域線重心を採用してよい範囲(同一都道府県の既知座標の外接矩形からの余裕、度)
BBOX_MARGIN_DEG = 0.5

# 日本の範囲(SPEC §14.1 の port.schema.json と同じ)
LAT_RANGE = (20.0, 46.0)
LON_RANGE = (122.0, 154.0)

CLASS_MAP = {"1": "1", "2": "2", "3": "3", "特3": "special_3", "4": "4"}


class IntegrateError(RuntimeError):
    pass


def load_c09() -> list[dict]:
    reader = shapefile.Reader(str(C09_POINT), encoding="cp932")
    out = []
    for rec, shp in zip(reader.records(), reader.shapes()):
        if not shp.points:
            continue
        lon, lat = shp.points[0]
        out.append(
            {
                "port_no": rec[0],
                "name": rec[1],
                "muni_code": rec[2],
                "pref_code": str(rec[2])[:2],
                "lat": lat,
                "lon": lon,
            }
        )
    reader.close()
    if not out:
        raise IntegrateError(f"C09 から点を 1 件も読めなかった: {C09_POINT}")
    return out


def load_c09_boundary_centroids() -> dict[str, tuple[float, float]]:
    """漁港区域線を漁港番号ごとにまとめ、頂点の平均を代表点とする。"""
    reader = shapefile.Reader(str(C09_BOUNDARY), encoding="cp932")
    acc: dict[str, list[tuple[float, float]]] = collections.defaultdict(list)
    for rec, shp in zip(reader.records(), reader.shapes()):
        acc[rec[1]].extend(shp.points)
    reader.close()
    return {
        code: (sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts))
        for code, pts in acc.items()
        if pts
    }


def verify_pref_table(c09: list[dict], ports: list[dict]) -> None:
    """PREF_CODE(定数表)を C09 の市区町村コードとの多数決で検算する。

    港名+番号が一致した組だけを使う。表が間違っていれば、ここで落ちる。
    """
    by_code = collections.defaultdict(list)
    for r in c09:
        by_code[r["port_no"]].append(r)
    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for p in ports:
        cands = [c for c in by_code.get(p["port_no"], []) if c["name"] == p["name_ja"]]
        if len(cands) == 1:
            votes[p["prefecture"]][cands[0]["pref_code"]] += 1

    problems = []
    for pref, counter in votes.items():
        top, n = counter.most_common(1)[0]
        if PREF_CODE.get(pref) != top:
            problems.append((pref, PREF_CODE.get(pref), top, n))
    if problems:
        raise IntegrateError(f"都道府県コード表が C09 の多数決と食い違う: {problems}")
    if len(votes) < 30:
        raise IntegrateError(f"検算に使えた都道府県が {len(votes)} 件しかない(検算が空振り)")


def in_japan(lat: float, lon: float) -> bool:
    return LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]


def within_prefecture_bbox(
    bbox: list[float] | None, lat: float, lon: float, margin: float = BBOX_MARGIN_DEG
) -> bool:
    """区域線重心を採ってよいか。bbox は [lon_min, lat_min, lon_max, lat_max]。

    判定を build() の中に埋めない —— 規則が壊れたときに誰も気づかないため(HC-080)。
    """
    if bbox is None:
        return False
    return (
        bbox[0] - margin <= lon <= bbox[2] + margin
        and bbox[1] - margin <= lat <= bbox[3] + margin
    )


def build() -> dict:
    ports = json.loads((NORM / "jfa_ports.json").read_text(encoding="utf-8"))
    counts = json.loads((NORM / "jfa_official_counts.json").read_text(encoding="utf-8"))
    c09 = load_c09()
    verify_pref_table(c09, ports)

    by_code: dict[str, list[dict]] = collections.defaultdict(list)
    by_pref_name: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for r in c09:
        by_code[r["port_no"]].append(r)
        pref = CODE_PREF.get(r["pref_code"])
        if pref:
            by_pref_name[(pref, r["name"])].append(r)

    special = set(counts["overall"]["special_class_3_names"])

    records = []
    method_counts: collections.Counter = collections.Counter()
    for p in ports:
        pref = p["prefecture"]
        pref_code = PREF_CODE[pref]
        cands = by_code.get(p["port_no"], [])
        same_pref = [c for c in cands if c["pref_code"] == pref_code]

        hit = None
        method = None
        exact = [c for c in same_pref if c["name"] == p["name_ja"]]
        if len(exact) == 1:
            hit, method = exact[0], "code_name_pref"
        elif len(same_pref) == 1:
            hit, method = same_pref[0], "code_pref"
        else:
            by_name = by_pref_name.get((pref, p["name_ja"]), [])
            if len(by_name) == 1:
                hit, method = by_name[0], "name_pref"

        if hit is not None and not in_japan(hit["lat"], hit["lon"]):
            raise IntegrateError(
                f"{p['port_no']} {p['name_ja']}: 座標が日本の範囲外 {hit['lat']},{hit['lon']}"
            )

        method_counts[method or "none"] += 1
        port_class = CLASS_MAP.get(p["port_class"])
        if port_class is None:
            raise IntegrateError(f"未知の種別 {p['port_class']!r}: {p['port_no']}")
        records.append(
            {
                "port_no": p["port_no"],
                "name_ja": p["name_ja"],
                "name_kana": p["name_kana"],
                "port_class": port_class,
                "pref_code": pref_code,
                "prefecture": pref,
                "municipality": p["municipality"] or None,
                "administrator_name": p["administrator_name"] or None,
                "administrator_type": (
                    "prefecture" if p["administrator_name"] == pref else "municipality"
                ),
                "fishery_coop": p["fishery_coop"] or None,
                "designation_date": p["designation_date"] or None,
                "area_change_date": p["area_change_date"] or None,
                "island_peninsula": p["island_peninsula"] or None,
                "inhabited_border_island": p["inhabited_border_island"] or None,
                "coast_conservation": p["coast_conservation"] or None,
                "port_regulation_law": p["port_regulation_law"] or None,
                "visitor_berth": p["visitor_berth"] or None,
                "subdistrict": p["subdistrict"] or None,
                "remarks": p["remarks"] or None,
                "lat": round(hit["lat"], 6) if hit else None,
                "lon": round(hit["lon"], 6) if hit else None,
                "geometry_method": method,
                "geometry_source": "DS-002" if hit else None,
                "source_pdf": p["source_pdf"],
            }
        )

    # --- 第 2 段: 点レイヤで付かなかった港を、漁港区域線の重心で補う ---
    centroids = load_c09_boundary_centroids()
    bbox: dict[str, list[float]] = {}
    for r in records:
        if r["lat"] is None:
            continue
        bb = bbox.setdefault(r["prefecture"], [180.0, 90.0, -180.0, -90.0])
        bb[0] = min(bb[0], r["lon"])
        bb[1] = min(bb[1], r["lat"])
        bb[2] = max(bb[2], r["lon"])
        bb[3] = max(bb[3], r["lat"])

    rejected = 0
    for r in records:
        if r["lat"] is not None:
            continue
        pt = centroids.get(r["port_no"])
        bb = bbox.get(r["prefecture"])
        if pt is None or bb is None:
            continue
        lat, lon = pt
        if not within_prefecture_bbox(bb, lat, lon):
            rejected += 1
            continue
        if not in_japan(lat, lon):
            rejected += 1
            continue
        r["lat"] = round(lat, 6)
        r["lon"] = round(lon, 6)
        r["geometry_method"] = "boundary_centroid"
        r["geometry_source"] = "DS-002"
        method_counts["none"] -= 1
        method_counts["boundary_centroid"] += 1
    method_counts["boundary_rejected_by_bbox"] = rejected

    if len({r["port_no"] for r in records}) != len(records):
        raise IntegrateError("漁港番号が全国で一意でない")

    # 特定第３種は「集合として」総括表の脚注と一致すること。
    # 港名は全国で一意ではない(第 1 種の「長崎」が別に存在する。実測 2026-09-08)ので、
    # 1 件ずつ名前で判定してはならない。
    got_special = {r["name_ja"] for r in records if r["port_class"] == "special_3"}
    if got_special != special:
        raise IntegrateError(
            f"特定第３種の集合が総括表脚注と不一致: 明細のみ {got_special - special} / "
            f"脚注のみ {special - got_special}"
        )

    CANON.mkdir(parents=True, exist_ok=True)
    out = CANON / "ports.json"
    out.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")

    with_geom = sum(1 for r in records if r["lat"] is not None)
    print(f"{len(records)} ports -> {out}")
    print(f"座標あり {with_geom} ({with_geom / len(records) * 100:.2f}%)")
    print("突合の内訳:", dict(method_counts))
    return {"count": len(records), "with_geometry": with_geom, "methods": dict(method_counts)}


if __name__ == "__main__":
    argparse.ArgumentParser().parse_args()
    build()
