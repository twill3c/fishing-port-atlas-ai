"""取込器の幾何仮定に対する陽性対照。

取込器は「仮定が崩れたらその場で落ちる」ことを設計に入れている(HC-075)。
その仕掛けが**実際に撃つ**ことを確かめるのがここの役目である。
撃たない検査は、緩めたときも壊れたときも緑のままになる。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data-pipeline"))

from normalize.parse_jfa_ports import (  # noqa: E402
    N_COLUMNS,
    ParseError,
    _column_edges,
    _data_band,
    _text_lines,
    normalize_text,
    parse_pdf,
)

pytestmark = pytest.mark.unit

AKITA = ROOT / "data" / "raw" / "jfa" / "sub81-262.pdf"


class _FakePage:
    """罫線だけを持つ最小のページ。pdfplumber の page と同じ形で rects を返す。"""

    def __init__(self, rects, page_number=1):
        self.rects = rects
        self.page_number = page_number


def _v(x, top=40.0, bottom=400.0):
    return {"x0": x, "x1": x + 0.6, "top": top, "bottom": bottom, "width": 0.6, "height": bottom - top}


def _h(y, x0=10.0, x1=560.0):
    return {"x0": x0, "x1": x1, "top": y, "bottom": y + 0.6, "width": x1 - x0, "height": 0.6}


def test_t011_column_edges_require_17_rules():
    """T-011 陽性対照: 縦罫が 17 本でなければ落ちる(A1)。"""
    good = _FakePage([_v(20.0 + 30 * i) for i in range(N_COLUMNS + 1)])
    assert len(_column_edges(good)) == N_COLUMNS + 1

    bad = _FakePage([_v(20.0 + 30 * i) for i in range(N_COLUMNS)])  # 1 本足りない
    with pytest.raises(ParseError, match="縦罫"):
        _column_edges(bad)


def test_t011_data_band_requires_two_horizontal_rules():
    """T-011 陽性対照: 横罫が 1 本しかなければ落ちる(A2)。"""
    verticals = [_v(20.0 + 30 * i) for i in range(N_COLUMNS + 1)]
    good = _FakePage(verticals + [_h(38.0), _h(100.0)])
    top, bottom = _data_band(good)
    assert (top, bottom) == (100.3, 400.0)

    bad = _FakePage(verticals + [_h(38.0)])
    with pytest.raises(ParseError, match="横罫"):
        _data_band(bad)


def test_t011_data_band_bottom_comes_from_vertical_rules():
    """T-011: 下端は縦罫の終端から取る。

    実測(2026-09-08): 表の下に注記枠がある県(秋田県)では外枠矩形が表より下まで伸びる。
    外枠を下端に使うと、注記の文字がデータ行に混ざる。
    """
    verticals = [_v(20.0 + 30 * i, bottom=381.24) for i in range(N_COLUMNS + 1)]
    frame = {"x0": 13.9, "x1": 562.9, "top": 37.7, "bottom": 479.4, "width": 549.0, "height": 441.7}
    page = _FakePage(verticals + [_h(37.0), _h(100.8), _h(380.6), frame])
    _, bottom = _data_band(page)
    assert bottom == pytest.approx(381.24)


def test_t011_text_lines_group_by_tolerance():
    """T-011: 行の束ね方。同一行の微差は 1 行、行間は別行になる。"""
    assert _text_lines([]) == []
    assert _text_lines([100.0, 100.4, 112.7, 113.1]) == pytest.approx([100.2, 112.9])


def test_normalize_text_folds_width_and_kana():
    """漁港名・読みの正規化(SPEC §17.2 相当)。

    期待値の出所: 実際の PDF から採った文字列(小樽市の漁協欄は字間に空白が入る、
    読みは半角カナ)。NFKC は半角カナを全角へ畳む。
    """
    assert normalize_text("小 樽 市") == "小樽市"
    assert normalize_text("ｼｬﾅｲ") == "シャナイ"
    assert normalize_text("美谷(歌棄)") == "美谷(歌棄)"


@pytest.mark.integration
def test_akita_row_count_and_shape():
    """実 PDF 1 県分の取込。件数の出所は都道府県別表(別文書)。"""
    if not AKITA.exists():
        pytest.skip("PDF 未取得(python data-pipeline/download/fetch_jfa_ports.py)")
    import json

    counts = json.loads(
        (ROOT / "data" / "normalized" / "jfa_official_counts.json").read_text(encoding="utf-8")
    )
    want = counts["by_prefecture"]["prefectures"]["秋田県"]["total"]

    rows = parse_pdf(AKITA, "秋田県")
    assert len(rows) == want
    assert all(len(r.port_no) == 7 and r.port_no.isdigit() for r in rows)
    assert all(r.name_ja for r in rows), "港名が空の行がある"
    assert all(r.port_class in {"1", "2", "3", "特3", "4"} for r in rows)
