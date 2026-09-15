"""T-056 / G-30: skip の照合そのものが働くことを、両方向の陽性対照で確かめる(loop_007)。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _ci_skips import EXPECTED, compare, expected_skips, require_raw  # noqa: E402

pytestmark = pytest.mark.unit


def test_t056_compare_detects_both_directions():
    declared = {"tests/a.py::test_x", "tests/b.py::test_y"}
    assert compare({"tests/a.py::test_x", "tests/b.py::test_y"}, declared) == ([], [])
    # 陽性対照 1: 宣言に無い skip(検査が黙って消えた)
    assert compare(declared | {"tests/c.py::test_z"}, declared) == (["tests/c.py::test_z"], [])
    # 陽性対照 2: 宣言したのに skip しなかった(一覧が古い)
    assert compare({"tests/a.py::test_x"}, declared) == ([], ["tests/b.py::test_y"])


def test_t056_declared_list_is_readable_and_not_empty():
    declared = expected_skips()
    assert declared, f"{EXPECTED.name} が空では、照合は何も言っていない"
    assert all("::" in nodeid and nodeid.startswith("tests/") for nodeid in declared), declared


def test_t056_expected_skips_ignores_comments_and_blanks(tmp_path):
    path = tmp_path / "skips.txt"
    path.write_text("# 説明\n\ntests/a.py::test_x\n  tests/b.py::test_y  \n", encoding="utf-8")
    assert expected_skips(path) == {"tests/a.py::test_x", "tests/b.py::test_y"}


def test_t056_require_raw_skips_with_reason_when_missing():
    with pytest.raises(pytest.skip.Exception) as caught:
        require_raw("存在しない/ファイル.dbf", "取得コマンドの例")
    assert "生データ未取得" in str(caught.value) and "取得コマンドの例" in str(caught.value)
