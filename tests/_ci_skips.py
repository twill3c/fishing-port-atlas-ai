"""G-30: 積まない生データに依存する検査の skip を、宣言した一覧と照合する(loop_007)。

生データ(`data/raw`)は Git に入れない(実装仕様書 §12)。だから新しい clone や CI では、
生データを読む検査は走れない。走れないこと自体は正常だが、**skip は緑と見分けが付かない**。

- 生データが無ければ `require_raw` が理由(どのファイルが無く、何で取得するか)を付けて skip する。
  在るのに合わなければ、検査はそのまま失敗する(skip にしない)
- CI(環境変数 CI=true)では、skip した検査の集合を `ci_expected_skips.txt` と照合する。
  宣言に無い skip も、宣言したのに skip しなかった検査も、どちらも失敗にする。
  前者は検査が黙って消えたこと、後者は一覧が古くなったことを意味する

照合の関数は tests/pipeline/test_ci_skips.py が両方向の陽性対照で確かめる。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
EXPECTED = Path(__file__).with_name("ci_expected_skips.txt")


def require_raw(relative: str, how_to_fetch: str) -> Path:
    """`data/raw/<relative>` が無ければ理由つきで skip する。在ればそのパスを返す。"""
    path = RAW / relative
    if not path.exists():
        pytest.skip(f"生データ未取得: data/raw/{relative}({how_to_fetch})")
    return path


def require_c09() -> Path:
    """国土数値情報 C09-06(漁港データ)の点の属性表。取得スクリプトは無く、配布ページから手で展開した。"""
    return require_raw(
        "ksj/C09-06/C09-06_FishingPort.dbf",
        "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-C09.html から C09-06_GML.zip を取得して "
        "data/raw/ksj/C09-06 に展開",
    )


def expected_skips(path: Path = EXPECTED) -> set[str]:
    """宣言した一覧。空行と # で始まる行は読まない。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")}


def compare(actual: set[str], expected: set[str]) -> tuple[list[str], list[str]]:
    """(宣言に無い skip, 宣言したのに skip しなかった検査)。どちらも空なら一致。"""
    return sorted(actual - expected), sorted(expected - actual)
