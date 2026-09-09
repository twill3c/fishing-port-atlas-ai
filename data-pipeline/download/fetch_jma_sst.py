"""DS-003 気象庁「日本沿岸域の海面水温情報」の取得。

海域番号と海域名は**対応表のページ**から取る(コードに固定しない)。
日別値は海域ごとの TXT、平年値・5年統計値は `-stat.txt`。

サーバ負荷を避けるため:
- 既に取得済みのファイルは `--force` が無ければ再取得しない
- 1 ファイルごとに間隔を空ける
- 失敗しても最新だけを取り直せるようにファイル単位で保存する
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "jma_sst"

BASE = "https://www.data.jma.go.jp/kaiyou/data/db/kaikyo/series/engan"
AREA_TABLE_URL = f"{BASE}/eg_areano.html"
UA = "FishingPortAtlasAI/0.1 (+https://github.com/twill3c/fishing-port-atlas-ai)"

# 気象庁が海域を束ねている地域区分(各地域のページから所属を読む)
REGIONS = {
    "SP": "北海道周辺",
    "SN": "東北周辺",
    "TK": "関東・東海・北陸",
    "OS": "近畿・中国・四国",
    "FK": "九州北部",
    "KG": "九州南部・奄美",
    "OK": "沖縄",
}
REGION_LINK_RE = re.compile(r'href="engan(\d+)\.html"')

# 対応表は 1 行に 2 組(番号・海域名)が並ぶ
PAIR_RE = re.compile(
    r'<a href="engan(?P<no>\d+)\.html">\s*(?P=no)\s*</a>\s*</td>\s*<td>\s*(?P<name>[^<]+?)\s*</td>',
    re.S,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover_areas(session: requests.Session) -> list[dict[str, str]]:
    res = session.get(AREA_TABLE_URL, timeout=60)
    res.raise_for_status()
    res.encoding = res.apparent_encoding
    areas = [
        {"area_no": m.group("no"), "area_name": m.group("name").strip()}
        for m in PAIR_RE.finditer(res.text)
    ]
    if len(areas) < 50:
        raise RuntimeError(f"海域が {len(areas)} 件しか取れなかった: {AREA_TABLE_URL}")
    if len({a["area_no"] for a in areas}) != len(areas):
        raise RuntimeError("対応表に海域番号の重複がある")

    # 地域区分の所属を、各地域ページのリンクから読む
    belongs: dict[str, str] = {}
    for code, label in REGIONS.items():
        res = session.get(f"{BASE}/engan_{code}.html", timeout=60)
        res.raise_for_status()
        res.encoding = res.apparent_encoding
        for no in REGION_LINK_RE.findall(res.text):
            belongs.setdefault(no, label)
        time.sleep(0.5)

    unknown = [a["area_no"] for a in areas if a["area_no"] not in belongs]
    if unknown:
        raise RuntimeError(f"地域区分の分からない海域がある: {unknown}")
    for area in areas:
        area["region"] = belongs[area["area_no"]]
    return areas


def fetch(force: bool = False, sleep_s: float = 0.8) -> Path:
    RAW.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = UA

    areas = discover_areas(session)
    files = []
    for area in areas:
        for suffix in ("", "-stat"):
            name = f"area{area['area_no']}{suffix}.txt"
            dest = RAW / name
            if force or not dest.exists():
                res = session.get(f"{BASE}/txt/{name}", timeout=120)
                if res.status_code == 404:
                    # 平年値が無い海域がある(瀬戸内海の速報のみ海域)。欠落は記録して進む。
                    files.append(
                        {
                            "path": None,
                            "url": f"{BASE}/txt/{name}",
                            "area_no": area["area_no"],
                            "kind": "stat" if suffix else "daily",
                            "status": "404",
                        }
                    )
                    time.sleep(sleep_s)
                    continue
                res.raise_for_status()
                dest.write_bytes(res.content)
                time.sleep(sleep_s)
            files.append(
                {
                    "path": str(dest.relative_to(ROOT)).replace("\\", "/"),
                    "url": f"{BASE}/txt/{name}",
                    "area_no": area["area_no"],
                    "kind": "stat" if suffix else "daily",
                    "sha256": _sha256(dest),
                    "bytes": dest.stat().st_size,
                }
            )

    manifest = {
        "source_id": "DS-003",
        "dataset": "jma-coastal-sst",
        "area_table_url": AREA_TABLE_URL,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "areas": areas,
        "files": files,
    }
    (RAW / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    got = sum(1 for f in files if f.get("path"))
    missing = [f for f in files if not f.get("path")]
    print(f"海域 {len(areas)} / ファイル {got} 本取得(欠落 {len(missing)} 本)-> {RAW}")
    return RAW / "manifest.json"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    fetch(force=args.force)
