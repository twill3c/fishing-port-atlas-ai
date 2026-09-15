"""漁港マスタの二文書突合。

期待値の出所はすべて**明細 PDF とは別の文書**(総括表 sub81-256 / 都道府県別 sub81-257)である。
明細を数えた値を明細の検査に使っていない —— 取込器を壊しても、この 2 枚は動かない。
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "data" / "canonical" / "ports.json"
COUNTS = ROOT / "data" / "normalized" / "jfa_official_counts.json"

pytestmark = pytest.mark.validation


@pytest.fixture(scope="module")
def ports() -> list[dict]:
    if not CANON.exists():
        pytest.skip("canonical が未生成(python data-pipeline/integrate/build_port_master.py)")
    return json.loads(CANON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def official() -> dict:
    if not COUNTS.exists():
        pytest.skip("集計表が未生成(python data-pipeline/normalize/parse_jfa_summary.py)")
    return json.loads(COUNTS.read_text(encoding="utf-8"))


def test_t001_total_matches_official(ports, official):
    """T-001 / G-01: 港数が総括表の総計と一致する。

    期待値は定数で書かない —— 総括表 PDF から読んだ値をそのまま使う。
    公式が更新されれば期待値も動き、「公式が動いた」ことが分かる(SPEC §7)。
    """
    assert len(ports) == official["overall"]["by_class"]["total"]


def test_t002_class_breakdown_matches_official(ports, official):
    """T-002 / G-02: 種別内訳が総括表と一致する。"""
    got = collections.Counter(p["port_class"] for p in ports)
    want = official["overall"]["by_class"]
    assert {k: got[k] for k in ("1", "2", "3", "special_3", "4")} == {
        k: want[k] for k in ("1", "2", "3", "special_3", "4")
    }


def test_t003_prefecture_totals_match_official(ports, official):
    """T-003 / G-03: 40 都道府県すべての港数が都道府県別表と一致する。"""
    got = collections.Counter(p["prefecture"] for p in ports)
    want = {k: v["total"] for k, v in official["by_prefecture"]["prefectures"].items()}
    # 集合として一致していること(片側だけの検査にしない)
    assert set(got) == set(want)
    assert {k: got[k] for k in want} == want


def test_t004_prefecture_class_matches_official(ports, official):
    """T-004 / G-03: 都道府県 × 種別。

    都道府県別表の「第３種」は**特定第３種を含む**(実測 2026-09-08: 101 + 13 = 114)。
    仕様書の §1.1 にはこの注意が無い。3 と special_3 を足して比べる。
    """
    for pref, want in official["by_prefecture"]["prefectures"].items():
        rows = [p for p in ports if p["prefecture"] == pref]
        got = collections.Counter(p["port_class"] for p in rows)
        assert got["1"] == want["by_class"]["1"], pref
        assert got["2"] == want["by_class"]["2"], pref
        assert got["3"] + got["special_3"] == want["by_class"]["3_incl_special"], pref
        assert got["4"] == want["by_class"]["4"], pref


def test_t005_administrator_split_matches_official(ports, official):
    """T-005 / G-03: 管理者区分。

    明細の「漁港管理者」欄の**文字列**から導いた区分(県名と一致するか)を、
    別文書の集計と突き合わせる。導出規則そのものを外部の数が検算している。
    """
    for pref, want in official["by_prefecture"]["prefectures"].items():
        rows = [p for p in ports if p["prefecture"] == pref]
        got = collections.Counter(p["administrator_type"] for p in rows)
        assert got["prefecture"] == want["by_administrator"]["prefecture"], pref
        assert got["municipality"] == want["by_administrator"]["municipality"], pref


def test_t006_special_class_3_set(ports, official):
    """T-006 / G-04: 特定第３種の集合が総括表脚注の 13 港名と一致する。

    港名は全国で一意ではない(第 1 種の「長崎」が別に存在する。実測 2026-09-08)ので、
    1 件ずつ名前で判定せず、集合として比べる。
    """
    got = {p["name_ja"] for p in ports if p["port_class"] == "special_3"}
    want = set(official["overall"]["special_class_3_names"])
    assert got == want


def test_t007_port_no_unique(ports):
    """T-007 / G-05: 漁港番号が全国で一意である。"""
    counter = collections.Counter(p["port_no"] for p in ports)
    assert [k for k, v in counter.items() if v > 1] == []


def test_t008_coordinate_coverage(ports):
    """T-008 / G-06: 座標充足率が 90% 以上。

    閾値は SPEC G-06 の下限。実測は 98.30%(2,721/2,768、2026-09-08)。
    実測値そのものを期待値にすると、データが動くたびに壊れる(HC-016)。
    """
    with_geom = sum(1 for p in ports if p["lat"] is not None)
    assert with_geom / len(ports) >= 0.90


def test_t009_coordinates_in_japan(ports):
    """T-009 / G-07: 座標が日本の範囲に入る。"""
    out = [
        (p["port_no"], p["lat"], p["lon"])
        for p in ports
        if p["lat"] is not None and not (20 <= p["lat"] <= 46 and 122 <= p["lon"] <= 154)
    ]
    assert out == []


def test_t009b_no_zero_filled_coordinates(ports):
    """T-009 / G-08: 座標が無い港を (0, 0) で埋めていない。"""
    assert [p["port_no"] for p in ports if p["lat"] == 0 or p["lon"] == 0] == []


def test_t010_official_tables_are_internally_consistent(official):
    """T-010: オラクル側そのものの内部整合(HC-223: 源の内側も整合とは限らない)。"""
    by_pref = official["by_prefecture"]
    assert sum(r["total"] for r in by_pref["prefectures"].values()) == by_pref["total"]["total"]
    for pref, r in by_pref["prefectures"].items():
        assert sum(r["by_class"].values()) == r["total"], pref
        assert sum(r["by_administrator"].values()) == r["total"], pref
    overall = official["overall"]["by_class"]
    assert (
        overall["1"] + overall["2"] + overall["3"] + overall["special_3"] + overall["4"]
        == overall["total"]
    )


def test_t012_positive_control_count_check_detects_a_missing_port(ports, official):
    """T-012 **陽性対照**: 1 港削った入力を、件数照合が実際に落とすことを確かめる。

    「違反 0 件」は「検査した」を意味しない。この対照が無いと、
    照合が緩んだときも壊れたときも緑のままになる。
    """
    broken = ports[:-1]
    assert len(broken) != official["overall"]["by_class"]["total"]

    pref = broken[-1]["prefecture"]
    got = collections.Counter(p["prefecture"] for p in broken)
    want = official["by_prefecture"]["prefectures"]
    mismatches = [k for k in want if got[k] != want[k]["total"]]
    assert mismatches, "1 港削っても都道府県別の照合が気づかない = 照合が効いていない"


def test_t014_prefecture_code_table_verified_against_c09():
    """T-014: 都道府県コード定数表が C09 の市区町村コードとの多数決を通る。

    検算が**空振りしていない**ことも同時に確かめる(30 県以上で票が立つこと)。
    """
    import sys

    from _ci_skips import require_c09  # noqa: PLC0415

    require_c09()  # 生データが無ければ理由つきで skip(SPEC G-30)
    sys.path.insert(0, str(ROOT / "data-pipeline"))
    from integrate.build_port_master import load_c09, verify_pref_table  # noqa: PLC0415

    ports_norm = json.loads(
        (ROOT / "data" / "normalized" / "jfa_ports.json").read_text(encoding="utf-8")
    )
    verify_pref_table(load_c09(), ports_norm)  # 違反があれば IntegrateError で落ちる


def test_t022_every_port_has_sources(ports):
    """T-022 / F-09: すべての港が出典に辿れる。"""
    assert [p["port_no"] for p in ports if not p["source_pdf"]] == []
    with_geom = [p for p in ports if p["lat"] is not None]
    assert with_geom, "座標つきの港が 0 件では、この検査は何も言っていない"
    assert [p["port_no"] for p in with_geom if not p["geometry_source"]] == []
