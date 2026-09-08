"""DS-001 水産庁「漁港一覧」の取得。

一覧ページ(sub81.html)を起点に、総括表・都道府県別集計・都道府県別明細の PDF を取得する。
リンク先 URL をコードに固定しない(HC-075: 仕様が変わったら黙って違う結果を出さないように、
リンク表そのものから導き、期待と食い違ったら例外で止める)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "jfa"

INDEX_URL = (
    "https://www.jfa.maff.go.jp/j/gyoko_gyozyo/g_zyoho_bako/gyoko_itiran/sub81.html"
)
UA = "FishingPortAtlasAI/0.1 (+https://github.com/; research use; contact via repository)"

# 一覧ページのアンカーテキストに現れる見出し。明細 PDF は都道府県名で並ぶ。
ANCHOR_RE = re.compile(
    r'<a\s+href="(?P<href>[^"]*attach/pdf/sub81-\d+\.pdf)"[^>]*>(?P<label>[^<]*)</a>'
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def discover(session: requests.Session) -> list[dict[str, str]]:
    res = session.get(INDEX_URL, timeout=60)
    res.raise_for_status()
    res.encoding = res.apparent_encoding
    html = res.text

    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in ANCHOR_RE.finditer(html):
        href = m.group("href")
        label = m.group("label").strip()
        url = urljoin(INDEX_URL, href)
        if url in seen:
            continue
        seen.add(url)
        # 「北海道(PDF : 283KB)」→「北海道」
        name = re.sub(r"[（(]\s*PDF.*$", "", label).strip()
        entries.append({"url": url, "label": label, "name": name})

    if not entries:
        raise RuntimeError(f"漁港一覧ページからリンクを 1 件も抽出できなかった: {INDEX_URL}")
    return entries


def fetch(force: bool = False, sleep_s: float = 1.0) -> Path:
    RAW.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = UA

    index_path = RAW / "sub81.html"
    res = session.get(INDEX_URL, timeout=60)
    res.raise_for_status()
    index_path.write_bytes(res.content)

    entries = discover(session)
    files = []
    for entry in entries:
        filename = entry["url"].rsplit("/", 1)[-1]
        dest = RAW / filename
        if force or not dest.exists():
            r = session.get(entry["url"], timeout=120)
            r.raise_for_status()
            dest.write_bytes(r.content)
            time.sleep(sleep_s)
        files.append(
            {
                "path": str(dest.relative_to(ROOT)).replace("\\", "/"),
                "url": entry["url"],
                "name": entry["name"],
                "sha256": _sha256(dest),
                "bytes": dest.stat().st_size,
            }
        )

    manifest = {
        "source_id": "DS-001",
        "dataset": "jfa-fishing-port-list",
        "index_url": INDEX_URL,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": files,
    }
    manifest_path = RAW / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{len(files)} files -> {RAW}")
    return manifest_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    fetch(force=args.force)
