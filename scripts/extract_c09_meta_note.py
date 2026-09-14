"""C09 のメタデータから、施設延長の意味を述べた一文を機械で抜き、テストのフィクスチャにする(loop_006)。

T-051 は、AI の報告に載せる但し書きをこの抜粋と照合する。但し書きを手で書き写し、
照合相手はメタデータから機械で抜くので、写し間違い・言い換えは照合で落ちる(非循環)。

メタデータ KS-META-C09-06-g.xml は Shift_JIS。UTF-8 として読むと該当語が一つも見つからない
(loop_004 で読み落とした一因)。宣言された encoding を読んでから復号する。

使い方: python scripts/extract_c09_meta_note.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "data" / "raw" / "ksj" / "C09-06" / "KS-META-C09-06-g.xml"
FIXTURE = ROOT / "tests" / "fixtures" / "c09_meta_note.txt"
KEY = "普通交付税算定基準"


def extract(raw: bytes) -> str:
    declared = re.match(rb'<\?xml[^>]*encoding="([^"]+)"', raw)
    if not declared:
        raise SystemExit("XML 宣言に encoding が無い")
    text = raw.decode(declared.group(1).decode("ascii"))
    sentences = [s + "。" for s in re.split(r"。", text) if KEY in s]
    if len(sentences) != 1:
        raise SystemExit(f"{KEY} を含む文が 1 つでない: {len(sentences)}")
    sentence = sentences[0]
    start = sentence.rfind("なお、")
    if start < 0:
        raise SystemExit(f"文の書き出しが想定と違う: {sentence[-120:]!r}")
    return sentence[start:].strip()


def main() -> None:
    note = extract(META.read_bytes())
    FIXTURE.write_text(note + "\n", encoding="utf-8")
    print(f"{FIXTURE.relative_to(ROOT)}: {note}")


if __name__ == "__main__":
    main()
