"""L0 実測用プローブ: 取得した A40 全ファイルの浸水深区分ラベルの語彙を一度に測る。

build_tsunami.py の読み取り規則は、福井県の語彙だけを見て書いたため、北海道の
「1m以上 ～ 3m未満」で止まった。規則を直す前に、全ファイルの語彙を測って被覆を確かめる(HC-069)。

- 面(.shp)は読まない。zip の中の属性表(.dbf)だけを読むので速い
- ラベルごとに、今の規則で読めるかを出す
- 同じファイルの中で区間が重なっていないか(区分の体系が混ざっていないか)を出す
"""

from __future__ import annotations

import collections
import io
import json
import sys
import zipfile
from pathlib import Path

import shapefile

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "ksj" / "A40"
sys.path.insert(0, str(ROOT / "data-pipeline"))

from integrate.build_tsunami import TsunamiError, parse_rank_label  # noqa: E402


def read_labels(zip_path: Path, prefecture: str) -> collections.Counter:
    with zipfile.ZipFile(zip_path) as archive:
        dbf_names = [n for n in archive.namelist() if n.lower().endswith(".dbf")]
        if len(dbf_names) != 1:
            raise SystemExit(f"{zip_path.name}: .dbf が 1 本でない {dbf_names}")
        data = archive.read(dbf_names[0])
    for encoding in ("cp932", "utf-8"):
        try:
            reader = shapefile.Reader(dbf=io.BytesIO(data), encoding=encoding, encodingErrors="strict")
            if reader.record(0)[0] != prefecture:
                continue
            return collections.Counter(rec[2] for rec in reader.iterRecords())
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"{zip_path.name}: 都道府県名 {prefecture} を読める文字コードが無い")


def main() -> None:
    manifest = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))
    total: collections.Counter = collections.Counter()
    by_file: dict[str, collections.Counter] = {}
    for entry in manifest["files"]:
        labels = read_labels(RAW / entry["file"], entry["prefecture"])
        key = f"{entry['prefecture']} {entry['year']}"
        by_file[key] = labels
        total.update(labels)

    print(f"ファイル {len(by_file)} / 区分ラベル {len(total)} 種 / 面 {sum(total.values()):,}")
    unreadable = []
    for label, count in sorted(total.items(), key=lambda kv: -kv[1]):
        try:
            low, high = parse_rank_label(label)
            parsed = f"{low}〜{high}"
        except TsunamiError:
            parsed = "読めない"
            unreadable.append(label)
        print(f"  {label!r:<28} {count:>9,}  -> {parsed}")
    print("\n読めないラベル:", unreadable)

    print("\n区分の体系(ファイルごとのラベル集合。同じ集合はまとめる):")
    systems: dict[tuple, list[str]] = collections.defaultdict(list)
    for key, labels in by_file.items():
        systems[tuple(sorted(labels))].append(key)
    for labels, files in sorted(systems.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(files):>2} ファイル: {list(labels)}")
        print(f"      {files}")

    print("\n同じファイルの中で区間が重なるもの(読めるラベルだけで判定):")
    for key, labels in by_file.items():
        intervals = []
        for label in labels:
            try:
                intervals.append((*parse_rank_label(label), label))
            except TsunamiError:
                pass
        intervals.sort()
        overlaps = [
            (a[2], b[2]) for a, b in zip(intervals, intervals[1:]) if b[0] < a[1]
        ]
        if overlaps:
            print(f"  {key}: {overlaps}")


if __name__ == "__main__":
    main()
