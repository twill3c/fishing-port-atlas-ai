"""L0 実測用プローブ — 仕様書の前提を実物に当てて確かめる(使い捨てではなく記録用)。

出力はすべて標準出力。数値は SPEC / TEST_SPEC の「実測」の出所として引用する。
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pdfplumber
import shapefile  # pyshp

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"


def probe_summary_pdf() -> None:
    pdf_path = RAW / "jfa" / "sub81-256.pdf"
    print(f"=== 総括表 {pdf_path.name} ===")
    with pdfplumber.open(pdf_path) as pdf:
        print(f"pages={len(pdf.pages)}")
        for page in pdf.pages:
            text = page.extract_text() or ""
            print(text)
            for table in page.extract_tables():
                print("--- table ---")
                for row in table[:60]:
                    print(row)


def probe_pref_pdf() -> None:
    pdf_path = RAW / "jfa" / "sub81-298_hokkaido.pdf"
    print(f"\n=== 都道府県別 {pdf_path.name} ===")
    with pdfplumber.open(pdf_path) as pdf:
        print(f"pages={len(pdf.pages)}")
        page = pdf.pages[0]
        print(page.extract_text())
        for table in page.extract_tables():
            print("--- table ---")
            for row in table[:25]:
                print(row)


def probe_c09() -> None:
    zip_path = RAW / "ksj" / "C09-06_GML.zip"
    print(f"\n=== 国土数値情報 C09 {zip_path.name} ===")
    dest = RAW / "ksj" / "C09-06"
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)

    for stem in ("C09-06_FishingPort", "C09-06_FishingPortBoundary"):
        reader = shapefile.Reader(str(dest / stem), encoding="cp932")
        print(f"\n--- {stem} ---")
        print(f"shapeType={reader.shapeTypeName} records={len(reader)}")
        print("fields:", [f[0] for f in reader.fields[1:]])
        for rec in reader.iterRecords():
            print(list(rec))
            break
        shp = reader.shape(0)
        print("first shape points[:3]:", shp.points[:3])
        reader.close()


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "summary"):
        probe_summary_pdf()
    if which in ("all", "pref"):
        probe_pref_pdf()
    if which in ("all", "c09"):
        probe_c09()
