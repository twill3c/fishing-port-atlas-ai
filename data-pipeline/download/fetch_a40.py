"""DS-006 国土数値情報 A40(津波浸水想定)の取得。再配布してよい県だけ(SPEC G-21)。

- 配布表は A40 の 2024 年度ページから読む。URL はページに書かれていない(JavaScript で開く)ので、
  `https://nlftp.mlit.go.jp/ksj/gml/data/A40/A40-YY/A40-YY_PP_GML.zip` の規則で組み立てる
  (福井県 A40-23_18 で確かめた。2026-09-14)。**規則が外れた年度は黙って飛ばさず止める**
- 同じ県の年度違いは全部取る(「重複する箇所は最新年度を」なので、古い年度が覆う範囲も要る)
- 取得済みのファイルはサイズと sha256 を記録し、再実行では取り直さない(途中から再開できる)
- 1 ファイルごとに間隔を空ける
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.licenses import A40_PAGE_URL, TSUNAMI_POLICY, short_name  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "ksj" / "A40"
PAGE_FILE = RAW / "KsjTmplt-A40-2024.html"
URL_TEMPLATE = "https://nlftp.mlit.go.jp/ksj/gml/data/A40/{year_dir}/{file}"
UA = "FishingPortAtlasAI/0.1 (+https://github.com/twill3c/fishing-port-atlas-ai)"

# ページのサイズ表記は丸めてある(例 4.79MB)。これを超えて食い違えば取り違えを疑う
SIZE_TOLERANCE = 0.03


def _size_bytes(text: str) -> float:
    m = re.match(r"([\d.]+)\s*(KB|MB|GB)", text)
    if not m:
        raise ValueError(f"サイズ表記が読めない: {text!r}")
    return float(m.group(1)) * {"KB": 1024, "MB": 1024**2, "GB": 1024**3}[m.group(2)]


def parse_distribution(page: str) -> list[dict]:
    rows = []
    for tr in re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", page):
        if ".zip" not in tr:
            continue
        cells = [
            re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
            for c in re.findall(r"(?s)<t[dh][^>]*>(.*?)</t[dh]>", tr)
        ]
        m = re.fullmatch(r"A40-(\d{2})_(\d{2})_GML\.zip", cells[4])
        if not m:
            raise ValueError(f"ファイル名の形が想定と違う: {cells}")
        rows.append(
            {
                "short": cells[0],
                "year": int(cells[2][:4]),
                "page_bytes": _size_bytes(cells[3]),
                "file": cells[4],
                "pref_code": m.group(2),
                "year_dir": f"A40-{m.group(1)}",
            }
        )
    if not rows:
        raise SystemExit("配布表から 1 行も読めなかった")
    return rows


def main(limit: int | None = None, sleep_s: float = 1.0) -> Path:
    RAW.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = UA

    if not PAGE_FILE.exists():
        res = session.get(A40_PAGE_URL, timeout=60)
        res.raise_for_status()
        PAGE_FILE.write_bytes(res.content)
    rows = parse_distribution(PAGE_FILE.read_text(encoding="utf-8"))

    by_short = {short_name(p): p for p in TSUNAMI_POLICY}
    unknown = sorted({r["short"] for r in rows} - set(by_short))
    if unknown:
        raise SystemExit(f"区分表に無い県が配布表にある: {unknown}")

    targets = [r for r in rows if TSUNAMI_POLICY[by_short[r["short"]]]["policy"] == "redistribute"]
    skipped = sorted({by_short[r["short"]] for r in rows} - {by_short[r["short"]] for r in targets})
    print(f"配布 {len(rows)} 行 / 取得対象 {len(targets)} 行 / 取らない県 {skipped}")
    if limit:
        targets = targets[:limit]

    manifest_path = RAW / "manifest.json"
    done = {}
    if manifest_path.exists():
        done = {f["file"]: f for f in json.loads(manifest_path.read_text(encoding="utf-8"))["files"]}

    files = []
    for i, row in enumerate(targets, 1):
        dest = RAW / row["file"]
        pref = by_short[row["short"]]
        if dest.exists() and row["file"] in done and dest.stat().st_size == done[row["file"]]["bytes"]:
            files.append(done[row["file"]])
            continue
        url = URL_TEMPLATE.format(**row)
        res = session.get(url, timeout=900)
        if res.status_code != 200:
            raise SystemExit(f"URL の規則が外れた: {url} -> {res.status_code}")
        ratio = len(res.content) / row["page_bytes"]
        if abs(ratio - 1) > SIZE_TOLERANCE:
            raise SystemExit(
                f"{row['file']}: 取得 {len(res.content):,} bytes がページ表記 {row['page_bytes']:,.0f} と食い違う"
            )
        dest.write_bytes(res.content)
        entry = {
            "prefecture": pref,
            "year": row["year"],
            "file": row["file"],
            "url": url,
            "bytes": len(res.content),
            "sha256": hashlib.sha256(res.content).hexdigest(),
        }
        files.append(entry)
        print(f"[{i}/{len(targets)}] {pref} {row['year']} {len(res.content) / 1e6:.1f} MB", flush=True)
        manifest_path.write_text(
            json.dumps({"source_id": "DS-006", "page": A40_PAGE_URL, "files": files}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        time.sleep(sleep_s)

    manifest = {
        "source_id": "DS-006",
        "page": A40_PAGE_URL,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": files,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(f["bytes"] for f in files)
    print(f"取得済み {len(files)} ファイル / {total / 1e9:.2f} GB -> {manifest_path}")
    return manifest_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="先頭 N 行だけ取る(試し取り用)")
    args = ap.parse_args()
    main(limit=args.limit)
