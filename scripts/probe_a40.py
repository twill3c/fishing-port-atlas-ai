"""L0 実測用プローブ: 国土数値情報 A40(津波浸水想定)を作る前に確かめること。

1. 配布の全体像: 都道府県ごとの zip(年度・サイズ)と、利用条件の三区分
   (再配信可 / 条件付き / 提供不可)。再配信できる県だけを取った場合の合計サイズ
2. ダウンロード URL の規則: ページには URL が書かれていない(JavaScript で開く)ので、
   C09 と同じ規則を推測して実際に取れるかで確かめる
3. 使えるかどうか: 漁港は海岸にあるので、
   - ほぼ全港が浸水想定区域の中に入って情報にならない、
   - 逆に代表点が海上にあって「区域外」が嘘になる、
   のどちらも起こりうる。一県分で、代表点の内外と区域までの距離を測る

出力は標準出力だけ。数は SPEC の「実測」の出所として引用する。
"""

from __future__ import annotations

import collections
import html
import io
import json
import math
import re
import sys
import zipfile
from pathlib import Path

import requests
import shapefile
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "ksj" / "A40"
PAGE_FILE = RAW / "KsjTmplt-A40-2024.html"
UA = "FishingPortAtlasAI/0.1 (+https://github.com/twill3c/fishing-port-atlas-ai)"

# ページの記載をそのまま写す(2026-09-14 取得の KsjTmplt-A40-2024.html)
OPEN_PREFS = (
    "北海道、青森県、岩手県、秋田県、山形県、福島県、茨城県、東京都、神奈川県、新潟県、"
    "富山県、石川県、福井県、岐阜県、静岡県、愛知県、大阪府、兵庫県、和歌山県、鳥取県、"
    "岡山県、広島県、山口県、徳島県、愛媛県、高知県、福岡県、佐賀県、熊本県、宮崎県、"
    "鹿児島県、沖縄県"
).split("、")
CONDITIONAL_PREFS = ["宮城県", "千葉県", "三重県", "京都府", "島根県", "長崎県", "大分県"]
NOT_PROVIDED_PREFS = ["香川県"]


def short_name(pref: str) -> str:
    """ページの表は「北海道」以外を県・府・都を落とした短い名で書く。"""
    return pref if pref == "北海道" else pref[:-1]


def size_mb(text: str) -> float:
    m = re.match(r"([\d.]+)\s*(KB|MB|GB)", text)
    if not m:
        raise ValueError(f"サイズが読めない: {text!r}")
    value = float(m.group(1))
    return {"KB": value / 1024, "MB": value, "GB": value * 1024}[m.group(2)]


def parse_rows() -> list[dict]:
    page = PAGE_FILE.read_text(encoding="utf-8")
    rows = []
    for tr in re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", page):
        if ".zip" not in tr:
            continue
        cells = [
            re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
            for c in re.findall(r"(?s)<t[dh][^>]*>(.*?)</t[dh]>", tr)
        ]
        rows.append(
            {"pref": cells[0], "year": int(cells[2][:4]), "mb": size_mb(cells[3]), "file": cells[4]}
        )
    if not rows:
        raise SystemExit("配布の行を 1 件も読めなかった")
    return rows


def main() -> None:
    rows = parse_rows()
    by_pref: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        by_pref[row["pref"]].append(row)

    klass: dict[str, str] = {}
    for p in OPEN_PREFS:
        klass[short_name(p)] = "open"
    for p in CONDITIONAL_PREFS:
        klass[short_name(p)] = "conditional"
    for p in NOT_PROVIDED_PREFS:
        klass[short_name(p)] = "not_provided"

    print(f"配布の行 {len(rows)} / 配布のある県 {len(by_pref)}")
    unknown = [p for p in by_pref if p not in klass]
    print("利用条件の区分が分からない県名:", unknown)
    print("区分ごとの配布のある県数:", collections.Counter(klass.get(p, "?") for p in by_pref))

    ports = json.loads((ROOT / "data" / "canonical" / "ports.json").read_text(encoding="utf-8"))
    port_count = collections.Counter(short_name(p["prefecture"]) for p in ports)

    open_latest = sum(
        max(v, key=lambda r: r["year"])["mb"] for p, v in by_pref.items() if klass.get(p) == "open"
    )
    open_all = sum(r["mb"] for p, v in by_pref.items() if klass.get(p) == "open" for r in v)
    print(f"再配信可の県: 最新年度だけ {open_latest / 1024:.2f} GB / 全年度 {open_all / 1024:.2f} GB")
    print("再配信可なのに配布の無い県:", [short_name(p) for p in OPEN_PREFS if short_name(p) not in by_pref])
    no_data = sorted((p for p in port_count if p not in by_pref), key=lambda p: -port_count[p])
    print("漁港があるのに配布の無い県:", [(p, port_count[p]) for p in no_data])
    multi = {p: [r["year"] for r in v] for p, v in by_pref.items() if len(v) > 1}
    print("年度違いが複数ある県:", multi)

    # --- 一県だけ取り、使えるかを測る(年度が 1 つだけで、漁港が 10 以上ある再配信可の県で最小) ---
    candidates = sorted(
        (
            (v[0], p)
            for p, v in by_pref.items()
            if klass.get(p) == "open" and len(v) == 1 and port_count[p] >= 10
        ),
        key=lambda x: x[0]["mb"],
    )
    if not candidates:
        raise SystemExit("試せる県が無い")
    row, pref = candidates[0]
    print(f"\n試す県: {pref} {row} 漁港 {port_count[pref]}")

    year_dir = row["file"].split("_")[0]
    url = f"https://nlftp.mlit.go.jp/ksj/gml/data/A40/{year_dir}/{row['file']}"
    res = requests.get(url, headers={"User-Agent": UA}, timeout=300)
    print("URL の推測:", url, "->", res.status_code, len(res.content), "bytes")
    if res.status_code != 200:
        raise SystemExit("URL の推測が外れた")
    (RAW / row["file"]).write_bytes(res.content)

    archive = zipfile.ZipFile(io.BytesIO(res.content))
    names = archive.namelist()
    print("zip の中身:", names[:15], f"... 計 {len(names)}")
    shp_names = [n for n in names if n.lower().endswith(".shp")]
    if not shp_names:
        raise SystemExit("shp が無い")
    dest = RAW / row["file"].replace(".zip", "")
    archive.extractall(dest)

    for shp_name in shp_names:
        encoding = "utf-8" if "utf" in shp_name.lower() else "cp932"
        reader = shapefile.Reader(str(dest / shp_name[:-4]), encoding=encoding)
        print(
            f"shp: {shp_name} 型 {reader.shapeTypeName} 件数 {len(reader)} "
            f"欄 {[f[0] for f in reader.fields[1:]]} (encoding={encoding})"
        )
        first = next(reader.iterRecords())
        print("  先頭の行:", list(first))
        reader.close()

    shp_name = shp_names[0]
    encoding = "utf-8" if "utf" in shp_name.lower() else "cp932"
    reader = shapefile.Reader(str(dest / shp_name[:-4]), encoding=encoding)
    field_names = [f[0] for f in reader.fields[1:]]
    rank_index = next((i for i, f in enumerate(field_names) if f.endswith("003")), None)
    records = list(reader.iterRecords())
    if rank_index is not None:
        print("浸水深の区分(A40_003):", collections.Counter(r[rank_index] for r in records).most_common())
    geoms = [shape(s.__geo_interface__) for s in reader.shapes()]
    reader.close()
    tree = STRtree(geoms)

    mine = [p for p in ports if short_name(p["prefecture"]) == pref and p["lat"] is not None]
    inside = 0
    distances_m: list[float] = []
    for port in mine:
        point = Point(port["lon"], port["lat"])
        if any(geoms[i].contains(point) for i in tree.query(point)):
            inside += 1
            continue
        nearest = tree.nearest(point)
        degrees = geoms[nearest].distance(point)
        # 概算: 経度方向の縮みを緯度で補正した 1 度 ≒ 111 km(プローブ用。出荷には使わない)
        distances_m.append(degrees * 111_000 * math.cos(math.radians(port["lat"])))

    print(f"\n{pref} の漁港 {len(mine)}: 代表点が区域内 {inside} / 区域外 {len(distances_m)}")
    if distances_m:
        ds = sorted(distances_m)
        print(
            f"区域外の点から最寄りの区域まで(概算 m): 最小 {ds[0]:.0f} / 中央 {ds[len(ds) // 2]:.0f} / "
            f"最大 {ds[-1]:.0f} / 50m 以内 {sum(1 for d in ds if d <= 50)} / "
            f"200m 以内 {sum(1 for d in ds if d <= 200)}"
        )


if __name__ == "__main__":
    sys.exit(main())
