"""PDF の本文をページごとに標準出力へ出す(読むための道具。出荷物ではない)。

使い方: python scripts/pdf_text.py <PDF のパス> [ページごとの最大文字数(既定 1500)] [キーワード ...]

キーワードを渡すと、そのいずれかを含む行だけを、ページ番号つきで出す。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pdfplumber


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 1500
    keywords = sys.argv[3:]
    with pdfplumber.open(path) as pdf:
        print(f"{path.name}: {len(pdf.pages)} ページ")
        for number, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            if keywords:
                for line in text.splitlines():
                    if any(k in line for k in keywords):
                        print(f"p{number}: {line}")
            else:
                print(f"----- p{number} -----")
                print(text[:limit])
    return 0


if __name__ == "__main__":
    sys.exit(main())
