"""canonical → public/data の Web 配信物を作る。

初期ロードに乗せるのは `manifest.json` と `ports.min.json` だけ(SPEC N-04)。
港の詳細は `ports/{port_no}.json` に分割し、クリック時に取りに行く。

欠損は 0 で埋めない(SPEC G-08)。値が無い欄は `null` にし、
「なぜ無いか」は `status` 語彙で区別する。
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "data" / "canonical"
NORM = ROOT / "data" / "normalized"
PUBLIC = ROOT / "public" / "data"

SCHEMA_VERSION = "1.0"

# ports.min.json のキー(初期ロードを小さくするため 1 文字)
#   n: 港名 / k: 読み / p: 都道府県 / m: 市町村 / c: 種別 / x: 経度 / y: 緯度 / g: 突合段階
MIN_KEYS = ("id", "n", "k", "p", "m", "c", "x", "y", "g")

STATUS_VOCAB = (
    "observed",
    "estimated",
    "suppressed",
    "not_available",
    "not_applicable",
    "missing_source",
)


def _load_ai() -> tuple[dict | None, dict]:
    """AI(種別と施設延長)の報告と、港ごとの分割外予測。未生成なら (None, {})。"""
    report_path = CANON / "ai_class_report.json"
    oof_path = CANON / "ai_class_oof.json"
    if not report_path.exists() or not oof_path.exists():
        return None, {}
    return (
        json.loads(report_path.read_text(encoding="utf-8")),
        json.loads(oof_path.read_text(encoding="utf-8")),
    )


def _ai_section(report: dict | None, oof: dict, port_no: str) -> dict:
    """港の詳細に載せる AI 欄(SPEC G-10: モデル・学習の手順・ベースライン・年次を併記)。

    予測は**分割外予測**(その港を学習に使っていないモデルの答え)の 5 反復多数決である。
    学習に使った港をそのモデルで当てた値を出すと、当たって見えるだけになる。
    """
    if report is None:
        return {"status": "not_available", "note": "AI の報告が未生成"}
    pred = oof.get(port_no)
    if pred is None:
        return {
            "status": "not_available",
            "note": "施設延長(国土数値情報 C09)が無い港、または 0(欠測の符号)の港は学習に入れていない(0 を値として使わない)",
        }
    shipped = next(m for m in report["models"] if m["name"] == report["shipped_model"])
    majority = next(m for m in report["models"] if m["name"] == "majority")
    return {
        "status": "estimated",
        "question": report["question"],
        "official_class": pred["official"],
        "predicted_class": pred["predicted"],
        "vote_share": pred["vote_share"],
        "agrees": pred["agrees"],
        "model": report["shipped_model"],
        "model_macro_f1": round(shipped["macro_f1_mean"], 4),
        "baseline_macro_f1": round(majority["macro_f1_mean"], 4),
        "cv": f"層化 {report['cv']['folds']} 分割 × {report['cv']['repeats']} 反復の分割外予測",
        "data_vintage": report["data_vintage"],
    }


TSUNAMI_STATUS = {
    "link_only": "suppressed",  # 再配布に連絡が要るので載せない
    "not_provided": "missing_source",  # 国土数値情報として提供されていない
    "no_data": "not_applicable",  # 津波浸水想定の配布が無い
}


def _tsunami_section(tsunami: dict | None, port_no: str, areas_report: dict | None = None) -> dict:
    """港の詳細に載せる津波の欄(SPEC §7.4 / G-19〜G-22、面は G-31〜G-34)。

    代表点が区域の内か外かは出さない。半径 100 / 200 / 500 m の最大浸水深区分だけを並べる。
    `area` は地図に重ねる面のファイルの場所で、面を配っている港だけに入れる(無い港は None)。
    """
    if tsunami is None:
        return {"status": "missing_source", "policy": None, "radii": None, "area": None, "note": "津波浸水想定は未構築"}
    record = tsunami["ports"][port_no]
    policy = record["policy"]
    if policy == "redistribute":
        status = "observed" if record["radii"] is not None else "not_available"
    else:
        status = TSUNAMI_STATUS[policy]
    has_area = areas_report is not None and port_no in areas_report["ports"]
    return {
        "status": status,
        "policy": policy,
        "radii": record["radii"],
        "area": f"/data/hazards/tsunami/{port_no}.json" if has_area else None,
        "note": record["note"],
    }


def _similar_section(report: dict | None, neighbors: dict, port_by_no: dict, port_no: str) -> dict:
    """港の詳細に載せる類似漁港の欄(F-08、SPEC G-25 / G-26)。

    G-25 を通らなければ近傍を出さない。出すときは、何を似ているとみなしたか(特徴の一覧)と、
    選び方への感度の注意書き(G-26)を必ず添える。
    """
    if report is None:
        return {"status": "missing_source", "note": "類似漁港は未構築"}
    if not report["gates"]["G-25"]["passed"]:
        return {
            "status": "suppressed",
            "note": "近傍の種別の一致が無作為と十分に違わなかったので、類似漁港は出していない(SPEC G-25)",
        }
    row = neighbors.get(port_no)
    if row is None:
        return {
            "status": "not_available",
            "note": "施設延長(国土数値情報 C09)が無い港、または 0(欠測の符号)の港は、似た港を計算していない",
        }
    return {
        "status": "estimated",
        "neighbors": [
            {
                "port_no": e["port_no"],
                "name_ja": port_by_no[e["port_no"]]["name_ja"],
                "prefecture": port_by_no[e["port_no"]]["prefecture"],
                "port_class": port_by_no[e["port_no"]]["port_class"],
                "distance": round(e["distance"], 4),
            }
            for e in row
        ],
        "features": report["features"],
        "sensitivity_notice": report["sensitivity_notice"],
        "note": "施設延長(交付税の算定に使う数)と属性を標準化した距離で近い 10 港。種別・座標・都道府県は使っていない",
    }


def _mark(value, status_when_missing: str = "not_available") -> dict:
    """値と、その値が無い理由をひと組で返す(SPEC G-08)。"""
    if value in (None, ""):
        return {"value": None, "status": status_when_missing}
    return {"value": value, "status": "observed"}


def build() -> dict:
    ports = json.loads((CANON / "ports.json").read_text(encoding="utf-8"))
    counts = json.loads((NORM / "jfa_official_counts.json").read_text(encoding="utf-8"))
    raw_manifest = json.loads((ROOT / "data" / "raw" / "jfa" / "manifest.json").read_text(encoding="utf-8"))

    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    (PUBLIC / "ports").mkdir(parents=True, exist_ok=True)

    ai_report, ai_oof = _load_ai()

    # 津波浸水想定(DS-006、SPEC §7.4)。未構築なら港の欄は「未取得」にする
    tsunami_path = CANON / "tsunami_ports.json"
    tsunami = json.loads(tsunami_path.read_text(encoding="utf-8")) if tsunami_path.exists() else None
    # 地図に重ねる区域の面の報告(G-31〜G-33)。港ごとの面のファイルがある港の一覧を兼ねる
    areas_path = CANON / "tsunami_areas_report.json"
    areas_report = json.loads(areas_path.read_text(encoding="utf-8")) if areas_path.exists() else None

    # 類似漁港(F-08、SPEC G-25〜G-28)。未生成なら港の欄は「未取得」にする
    similar_path = CANON / "similar_report.json"
    similar_report = json.loads(similar_path.read_text(encoding="utf-8")) if similar_path.exists() else None
    similar_neighbors = (
        json.loads((CANON / "similar_neighbors.json").read_text(encoding="utf-8"))
        if similar_report is not None
        else {}
    )
    port_by_no = {p["port_no"]: p for p in ports}

    min_rows = []
    for p in ports:
        min_rows.append(
            {
                "id": p["port_no"],
                "n": p["name_ja"],
                "k": p["name_kana"],
                "p": p["prefecture"],
                "m": p["municipality"] or "",
                "c": p["port_class"],
                "x": p["lon"],
                "y": p["lat"],
                "g": p["geometry_method"],
            }
        )
        detail = {
            "port": {
                "port_no": p["port_no"],
                "name_ja": p["name_ja"],
                "name_kana": p["name_kana"],
                "port_class": p["port_class"],
                "prefecture": p["prefecture"],
                "pref_code": p["pref_code"],
                "municipality": p["municipality"],
                "lat": p["lat"],
                "lon": p["lon"],
                "geometry_method": p["geometry_method"],
            },
            "administration": {
                "administrator_name": _mark(p["administrator_name"]),
                "administrator_type": _mark(p["administrator_type"]),
                "fishery_coop": _mark(p["fishery_coop"]),
                "designation_date": _mark(p["designation_date"]),
                "area_change_date": _mark(p["area_change_date"], "not_applicable"),
            },
            "attributes": {
                "island_peninsula": _mark(p["island_peninsula"], "not_applicable"),
                "inhabited_border_island": _mark(p["inhabited_border_island"], "not_applicable"),
                "coast_conservation": _mark(p["coast_conservation"], "not_applicable"),
                "port_regulation_law": _mark(p["port_regulation_law"], "not_applicable"),
                "visitor_berth": _mark(p["visitor_berth"], "not_applicable"),
                "subdistrict": _mark(p["subdistrict"], "not_applicable"),
                "remarks": _mark(p["remarks"], "not_applicable"),
            },
            "landing": {"status": "missing_source", "note": "e-Stat の認証が必要なため V1.0 では未取得"},
            "species": {"status": "missing_source", "note": "e-Stat の認証が必要なため V1.0 では未取得"},
            "ocean": {
                "status": "not_available",
                "note": (
                    "気象庁は沿岸海域のポリゴンを配布しておらず、港と海域の対応を"
                    "裏づけをもって付けられない。海域ごとの水温は「海の温度」の画面で読める"
                ),
            },
            "ai": _ai_section(ai_report, ai_oof, p["port_no"]),
            "tsunami": _tsunami_section(tsunami, p["port_no"], areas_report),
            "similar": _similar_section(similar_report, similar_neighbors, port_by_no, p["port_no"]),
            "sources": [
                {"source_id": "DS-001", "role": "港名・種別・管理者・所在地", "artifact": p["source_pdf"]},
                *(
                    [{"source_id": "DS-002", "role": f"座標({p['geometry_method']})"}]
                    if p["geometry_method"]
                    else []
                ),
            ],
        }
        (PUBLIC / "ports" / f"{p['port_no']}.json").write_text(
            json.dumps(detail, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )

    (PUBLIC / "ports.min.json").write_text(
        json.dumps(min_rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    # --- 津波浸水想定のメタ(但し書き・区分の並び・利用条件の表)。港の欄は詳細 JSON に入れた ---
    if tsunami is not None:
        (PUBLIC / "hazards").mkdir(parents=True, exist_ok=True)
        (PUBLIC / "hazards" / "tsunami-meta.json").write_text(
            json.dumps(tsunami["meta"], ensure_ascii=False, indent=1), encoding="utf-8"
        )

    # --- 地図に重ねる区域の面(SPEC G-31〜G-33)。港ごとのファイルを写す ---
    # 報告があるのに面の置き場が無い(新しい clone など)ときは、黙って空の配信物を作らずに止める
    if areas_report is not None:
        areas_dir = CANON / "tsunami_areas"
        if not areas_dir.exists():
            raise RuntimeError(
                "tsunami_areas_report.json があるのに data/canonical/tsunami_areas/ が無い"
                "(python data-pipeline/integrate/build_tsunami_areas.py を先に)"
            )
        (PUBLIC / "hazards" / "tsunami").mkdir(parents=True, exist_ok=True)
        for port_no in areas_report["ports"]:
            shutil.copyfile(areas_dir / f"{port_no}.json", PUBLIC / "hazards" / "tsunami" / f"{port_no}.json")

    # --- AI: 公式の種別は、交付税の算定に使う施設延長で読めるのか(SPEC §7.3 / G-23 / G-24)---
    if ai_report is not None:
        (PUBLIC / "ai").mkdir(parents=True, exist_ok=True)
        (PUBLIC / "ai" / "class-report.json").write_text(
            json.dumps(ai_report, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )

    # --- 類似漁港とクラスタ(F-08、SPEC G-25〜G-28)---
    # G-25 を通らなければ近傍は配らない。クラスタは G-28 を通ったときだけ canonical に在る
    if similar_report is not None and similar_report["gates"]["G-25"]["passed"]:
        (PUBLIC / "similar").mkdir(parents=True, exist_ok=True)
        for name in ("neighbors", "features"):
            shutil.copyfile(CANON / f"similar_{name}.json", PUBLIC / "similar" / f"{name}.json")
        if similar_report["gates"]["G-28"]["passed"]:
            shutil.copyfile(CANON / "similar_clusters.json", PUBLIC / "similar" / "clusters.json")
        similar_meta = {
            "question": similar_report["question"],
            "features": similar_report["features"],
            "k": similar_report["k"],
            "distance": similar_report["distance"],
            "tie_rule": similar_report["tie_rule"],
            "class_agreement": similar_report["class_agreement"],
            "gates": similar_report["gates"],
            "sensitivity_notice": similar_report["sensitivity_notice"],
            "identical_feature_rows": similar_report["identical_feature_rows"],
            "n_ports": similar_report["n_ports"],
            # G-28 を通ったときだけ在る。群の言語化(大きさ・種別の内訳・中央値・印の割合)
            "clusters": similar_report.get("clusters"),
        }
        (PUBLIC / "similar" / "meta.json").write_text(
            json.dumps(similar_meta, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    # --- 海域(DS-003)---
    ocean_path = CANON / "ocean_areas.json"
    ocean = json.loads(ocean_path.read_text(encoding="utf-8")) if ocean_path.exists() else []
    if ocean:
        (PUBLIC / "ocean").mkdir(parents=True, exist_ok=True)
        (PUBLIC / "ocean" / "areas.json").write_text(
            json.dumps(ocean, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )

    official = counts["overall"]["by_class"]
    stats = {
        "official": {
            "as_of": "2026-04-01",
            "total": official["total"],
            "by_class": {k: official[k] for k in ("1", "2", "3", "special_3", "4")},
            "special_class_3_names": counts["overall"]["special_class_3_names"],
        },
        "built": {
            "total": len(ports),
            "with_coordinates": sum(1 for p in ports if p["lat"] is not None),
            "by_geometry_method": _counter([p["geometry_method"] for p in ports]),
            "by_class": _counter([p["port_class"] for p in ports]),
            "by_prefecture": _counter([p["prefecture"] for p in ports]),
        },
    }
    if ocean:
        long_series = [a for a in ocean if a["trend"]["n_years"] >= 40]
        slopes = sorted(a["trend"]["slope_per_decade"] for a in long_series)
        stats["ocean"] = {
            "areas": len(ocean),
            "long_series_areas": len(long_series),
            "short_series_areas": len(ocean) - len(long_series),
            "rising": sum(1 for a in long_series if a["trend"]["slope_per_decade"] > 0),
            "rising_significant": sum(
                1
                for a in long_series
                if a["trend"]["slope_per_decade"] > 0 and a["trend"]["p"] < 0.05
            ),
            # 中央値は偶数件のとき中央 2 つの平均。lib/ocean.ts の median() と同じ定義。
            "median_slope_per_decade": (
                round(
                    (slopes[len(slopes) // 2 - 1] + slopes[len(slopes) // 2]) / 2
                    if len(slopes) % 2 == 0
                    else slopes[len(slopes) // 2],
                    4,
                )
                if slopes
                else None
            ),
            "last_observation": max(a["last_observation"] for a in ocean),
            # 港と海域の対応は付けていない(理由は /methodology/ と SPEC §7)
            "port_area_assignment": "not_available",
        }
    (PUBLIC / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    sources = [
        {
            "id": "DS-001",
            "title": "漁港一覧(総括表・都道府県別・都道府県別明細)",
            "provider": "水産庁",
            "url": raw_manifest["index_url"],
            "retrieved": raw_manifest["retrieved_at"][:10],
            "coverage": "令和8年4月1日現在",
            "processed": True,
            "processing": "PDF の罫線座標から表を再構成し、漁港 1 件 1 行へ正規化",
            "license": "出典の明示を条件に利用可(政府標準利用規約準拠)",
            "attribution": "出典: 水産庁「漁港一覧」",
        },
        {
            "id": "DS-002",
            "title": "国土数値情報 漁港データ(C09-06)",
            "provider": "国土交通省 国土政策局",
            "url": "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-C09.html",
            "retrieved": datetime.now(timezone.utc).date().isoformat(),
            "coverage": "平成18年度",
            "processed": True,
            "processing": "漁港番号で水産庁マスタへ突合し、段階(geometry_method)を記録",
            "license": "国土数値情報 利用約款",
            "attribution": "出典: 国土交通省「国土数値情報(漁港データ)」",
        },
        {
            "id": "DS-003",
            "title": "日本沿岸域の海面水温情報(沿岸海域 107)",
            "provider": "気象庁",
            "url": "https://www.data.jma.go.jp/kaiyou/data/db/kaikyo/series/engan/engan.html",
            "retrieved": datetime.now(timezone.utc).date().isoformat(),
            "coverage": "1982-01-01 以降(瀬戸内海の 5 海域は 2016-01-01 以降)",
            "processed": True,
            "processing": "日別値を年平均へ集計し、有効日数 330 日以上の年で最小二乗回帰",
            "license": "気象庁ホームページ利用規約(政府標準利用規約準拠)",
            "attribution": "気象庁「日本沿岸域の海面水温」をもとに Fishing Port Atlas AI が加工",
        },
        {
            "id": "DS-006",
            "title": "国土数値情報 津波浸水想定データ(A40、2024 年度ページ)",
            "provider": "国土交通省(原典は各都道府県)",
            "url": "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A40-2024.html",
            "retrieved": datetime.now(timezone.utc).date().isoformat(),
            "coverage": "都道府県ごとに年度が異なる(重なる箇所は新しい年度を優先)",
            "processed": True,
            "processing": (
                "再配布してよい都道府県だけ、漁港の代表点から半径 100 / 200 / 500 m の円に掛かる区域の"
                "最大浸水深区分を求めた。代表点が区域の内か外かは出していない"
            ),
            "license": "CC BY 4.0(一部制限)・都道府県ごとの利用条件",
            "attribution": "出典: 国土交通省「国土数値情報(津波浸水想定データ)」を加工して作成",
        },
        {
            "id": "DS-004",
            "title": "地理院タイル(淡色地図)",
            "provider": "国土地理院",
            "url": "https://maps.gsi.go.jp/development/ichiran.html",
            "retrieved": datetime.now(timezone.utc).date().isoformat(),
            "coverage": "—",
            "processed": False,
            "processing": "背景地図として配信元から直接読み込む(再配布しない)",
            "license": "地理院タイル利用規約",
            "attribution": "地理院タイル",
        },
    ]
    (PUBLIC / "sources.json").write_text(
        json.dumps(sources, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    manifest = {
        "build": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "schemaVersion": SCHEMA_VERSION,
        "statusVocabulary": list(STATUS_VOCAB),
        "datasets": {
            "ports": {"url": "/data/ports.min.json", "count": len(min_rows)},
            "stats": {"url": "/data/stats.json"},
            "sources": {"url": "/data/sources.json"},
            "portDetail": {"urlTemplate": "/data/ports/{port_no}.json"},
            **(
                {"oceanAreas": {"url": "/data/ocean/areas.json", "count": len(ocean)}}
                if ocean
                else {}
            ),
            **(
                {
                    "aiClass": {
                        "url": "/data/ai/class-report.json",
                        "shippedModel": ai_report["shipped_model"],
                    }
                }
                if ai_report is not None
                else {}
            ),
            **(
                {
                    "tsunamiMeta": {
                        "url": "/data/hazards/tsunami-meta.json",
                        "radiiM": tsunami["meta"]["radii_m"],
                    }
                }
                if tsunami is not None
                else {}
            ),
            **(
                {
                    "tsunamiAreas": {
                        "urlTemplate": "/data/hazards/tsunami/{port_no}.json",
                        "ports": len(areas_report["ports"]),
                        "radiusM": areas_report["radius_m"],
                        "simplifyM": areas_report["simplify_m"],
                        "maxAreaChange": areas_report["max_area_change"],
                    }
                }
                if areas_report is not None
                else {}
            ),
            **(
                {
                    "similar": {
                        "metaUrl": "/data/similar/meta.json",
                        "neighborsUrl": "/data/similar/neighbors.json",
                        "clusters": similar_report["gates"]["G-28"]["passed"],
                    }
                }
                if similar_report is not None and similar_report["gates"]["G-25"]["passed"]
                else {}
            ),
        },
    }
    (PUBLIC / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    size = (PUBLIC / "ports.min.json").stat().st_size
    print(f"ports.min.json {size / 1024:.1f} KB / 詳細 {len(ports)} 本 -> {PUBLIC}")
    return {"ports": len(ports), "min_bytes": size}


def _counter(values) -> dict:
    out: dict[str, int] = {}
    for v in values:
        key = "none" if v is None else str(v)
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


if __name__ == "__main__":
    build()
