"""DS-003 気象庁 沿岸海面水温の検査。

期待値の出所は**気象庁の説明ページ(eg_info.html)**である。
説明が言っていることを、データから独立に再現できるかを見る。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "data" / "canonical" / "ocean_areas.json"
RAW = ROOT / "data" / "raw" / "jma_sst"

sys.path.insert(0, str(ROOT / "data-pipeline"))

pytestmark = pytest.mark.validation

# 気象庁 eg_info.html の記載(2026-09-09 取得):
# 「大阪湾」「播磨灘・備讃瀬戸」「備後灘・燧灘」「安芸灘・伊予灘」「周防灘」は速報値のみで、
# 平年値データが存在しない。TXT は 2016 年からの推移である。
PROVISIONAL_ONLY = {"大阪湾", "播磨灘・備讃瀬戸", "備後灘・燧灘", "安芸灘・伊予灘", "周防灘"}


@pytest.fixture(scope="module")
def areas() -> list[dict]:
    if not CANON.exists():
        pytest.skip("海域データが未生成(python data-pipeline/integrate/build_ocean.py)")
    return json.loads(CANON.read_text(encoding="utf-8"))


def test_t027_documented_provisional_areas_are_exactly_those_without_normals(areas):
    """T-027: 説明ページが名指しした 5 海域が、平年値を持たない 5 海域と一致する。

    非循環である —— 名前の一覧は気象庁の**文章**から、
    平年値の有無は**データファイル**から、それぞれ独立に来ている。
    """
    without_normal = {a["area_name"] for a in areas if not a["has_normal"]}
    assert without_normal == PROVISIONAL_ONLY

    # 同じ 5 海域が 2016 年始まりであることも、説明ページが言っている
    short = {a["area_name"] for a in areas if a["trend"]["first_year"] == 2016}
    assert short == PROVISIONAL_ONLY


def test_t028_long_series_start_in_1982(areas):
    """T-028: 長期系列は 1982 年に始まる(気象庁の解析開始年)。"""
    long = [a for a in areas if a["area_name"] not in PROVISIONAL_ONLY]
    assert long, "長期系列が 0 件では、この検査は何も言っていない"
    assert {a["trend"]["first_year"] for a in long} == {1982}


def test_t029_partial_year_excluded(areas):
    """T-029: 取得時点の当年(部分年)が回帰に入っていない。"""
    last_obs_year = max(int(a["last_observation"][:4]) for a in areas)
    assert [a["area_no"] for a in areas if a["trend"]["last_year"] >= last_obs_year] == []


def test_t030_normal_period_read_from_file(areas):
    """T-030: 平年値の期間をファイルから読んでいる(定数で決め打ちしていない)。

    実測(2026-09-09)では全海域が 1991-2020。値そのものではなく、
    **全海域で同一の期間が読めていること**を不変量にする。
    """
    periods = {a["normal_period"] for a in areas if a["has_normal"]}
    assert len(periods) == 1
    assert periods != {None}


def test_t031_trend_is_reproducible_from_series(areas):
    """T-031 / G-12: 出荷した年系列から傾きを再計算して一致する(Python 側)。

    TypeScript 側の独立実装との照合は tests/frontend/ocean.test.ts にある。
    ここは「出荷した系列と出荷した傾きが同じデータから来ている」ことを見る。
    """
    from integrate.build_ocean import ols_trend  # noqa: PLC0415

    for area in areas:
        years = [s["y"] for s in area["series"]]
        means = [s["mean"] for s in area["series"]]
        again = ols_trend(years, means)
        assert again["slope_per_decade"] == pytest.approx(
            area["trend"]["slope_per_decade"], abs=1e-9
        ), area["area_name"]
        assert again["n_years"] == area["trend"]["n_years"]


def test_t032_positive_control_trend_detects_a_shifted_series():
    """T-032 **陽性対照**: 回帰が、傾きのある系列とない系列を区別する。"""
    from integrate.build_ocean import ols_trend  # noqa: PLC0415

    years = list(range(1982, 2026))
    flat = ols_trend(years, [15.0] * len(years))
    assert flat["slope_per_decade"] == 0.0

    rising = ols_trend(years, [15.0 + 0.03 * (y - 1982) for y in years])
    assert rising["slope_per_decade"] == pytest.approx(0.3, abs=1e-9)
    assert rising["p"] < 1e-6


def test_t033_no_port_sst_assignment_is_shipped():
    """T-033: 港と海域の対応を出荷していない(測って捨てた判断が実装に効いている)。

    海域名からの割当は偽の一致を出したので採らないと決めた(SPEC §7)。
    その判断は文書だけでなく、**配信物に対応表が無いこと**で守られる。
    """
    public = ROOT / "public" / "data"
    if not public.exists():
        pytest.skip("配信物が未生成")
    assert not (public / "ocean" / "port-area-map.json").exists()

    sample = sorted((public / "ports").glob("*.json"))
    assert sample, "港の詳細が 0 件では、この検査は何も言っていない"
    detail = json.loads(sample[0].read_text(encoding="utf-8"))
    assert detail["ocean"]["status"] == "not_available"
    assert "ポリゴン" in detail["ocean"]["note"]
