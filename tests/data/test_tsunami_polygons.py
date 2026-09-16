"""津波浸水想定の区域の面(地図に重ねる)の検査。loop_009。ゲートは SPEC §4 G-31〜G-33(実測前に登録)。

- **表と面の一致は、構築のコードを使わず配信物だけから計算し直す**(別経路)。
  港の座標は ports.min.json、区分の並びは tsunami-meta.json、比べる相手は港の詳細の tsunami.radii
- 検査が働くことは陽性対照で確かめる(最も深い区分の面を消す・京都府の港番号のファイルを混ぜる)
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest
from shapely import affinity
from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "public" / "data"
AREAS = PUBLIC / "hazards" / "tsunami"
REPORT = ROOT / "data" / "canonical" / "tsunami_areas_report.json"
RADII = (100, 200, 500)
MAX_BYTES = 300_000
MAX_AREA_CHANGE = 0.01
EXCLUDED = {"link_only", "not_provided", "no_data"}

pytestmark = pytest.mark.validation


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def area_files() -> dict[str, Path]:
    if not AREAS.exists():
        # skip にしない —— 面が無いまま緑になると、G-31〜G-33 を誰も守っていないのに守られて見える
        pytest.fail("public/data/hazards/tsunami/ が無い(python data-pipeline/integrate/build_tsunami_areas.py と export_web.py)")
    return {p.stem: p for p in AREAS.glob("*.json")}


@pytest.fixture(scope="module")
def ports() -> dict[str, dict]:
    return {r["id"]: r for r in _load(PUBLIC / "ports.min.json")}


@pytest.fixture(scope="module")
def order() -> list[str]:
    return _load(PUBLIC / "hazards" / "tsunami-meta.json")["rank_order"]


def _detail_tsunami(port_no: str) -> dict:
    return _load(PUBLIC / "ports" / f"{port_no}.json")["tsunami"]


def _max_rank(collection: dict, lon: float, lat: float, radius: float, order: list[str]):
    """配った面だけから、港の局所平面で半径 radius の円と交わる面の最大区分(同じ区分なら新しい年度)。"""
    mx, my = 111_320 * math.cos(math.radians(lat)), 110_574
    disc = Point(0, 0).buffer(radius, quad_segs=32)
    best = None
    for feature in collection["features"]:
        local = affinity.affine_transform(shape(feature["geometry"]), [mx, 0, 0, my, -lon * mx, -lat * my])
        if local.is_empty or not local.intersects(disc):
            continue
        cand = (order.index(feature["properties"]["rank"]), feature["properties"]["vintage"])
        if best is None or cand > best:
            best = cand
    return (None, None) if best is None else (order[best[0]], best[1])


def _mismatches(collection: dict, port: dict, radii: list[dict], order: list[str]) -> list[int]:
    return [
        r["radius_m"]
        for r in radii
        if _max_rank(collection, port["x"], port["y"], r["radius_m"], order) != (r["max_rank"], r["vintage"])
    ]


# ---------------------------------------------------------------- G-31


def test_t058_shipped_polygons_reproduce_the_radius_table(area_files, ports, order):
    """T-058 / G-31: 配った面だけから計算し直した半径 3 通りの最大区分と年度が、全港で詳細の値と一致する。"""
    assert len(area_files) > 1000, "面のファイルが少なすぎる(構築が空振りしている疑い)"
    bad = {}
    for port_no, path in area_files.items():
        radii = _detail_tsunami(port_no)["radii"]
        mismatch = _mismatches(_load(path), ports[port_no], radii, order)
        if mismatch:
            bad[port_no] = mismatch
    assert bad == {}


def test_t058_positive_control_removing_deepest_polygons_is_detected(area_files, ports, order):
    """T-058 **陽性対照**: 半径 100 m に区分がある港で、その最も深い区分の面を全部消すと、照合が食い違いを出す。"""
    for port_no, path in sorted(area_files.items()):
        radii = _detail_tsunami(port_no)["radii"]
        if radii[0]["max_rank"] is None:
            continue
        collection = _load(path)
        deepest = radii[-1]["max_rank"]
        forged = {**collection, "features": [f for f in collection["features"] if f["properties"]["rank"] != deepest]}
        assert _mismatches(forged, ports[port_no], radii, order), port_no
        return
    pytest.fail("半径 100 m に区分がある港が 1 つも無く、対照が成り立たない")


# ---------------------------------------------------------------- G-32


def test_t059_simplification_within_tolerance(area_files):
    """T-059 / G-32: 簡略化の幅は 1 m 以下の既定の段、座標は小数 6 桁、港ごとの面積の変化は最大 1% 以内。

    1 m で 1% を超える港だけが小さい幅を使う(2026-09-17 の改訂。北海道 1136010 が 1 m で 1.22%)。
    """
    report = _load(REPORT)
    assert report["simplify_m"] == 1.0
    assert report["coord_decimals"] == 6
    assert set(report["ports"]) == set(area_files)
    changes = [entry["area_change"] for entry in report["ports"].values()]
    assert report["max_area_change"] == pytest.approx(max(changes), abs=1e-12)
    assert max(changes) <= MAX_AREA_CHANGE
    for port_no, entry in report["ports"].items():
        assert entry["simplify_m"] in (1.0, 0.5, 0.25, 0.0), port_no
        if entry["simplify_m"] < 1.0:
            # 小さい幅は、1 m では上限を超えた港にだけ許す
            assert entry["area_change_at_1m"] > MAX_AREA_CHANGE, port_no
    too_many_decimals = re.compile(r"\d\.\d{7,}")
    offenders = [no for no, path in area_files.items() if too_many_decimals.search(path.read_text(encoding="utf-8"))]
    assert offenders == []


# ---------------------------------------------------------------- G-33


def expected_area_ports(details: dict[str, dict]) -> set[str]:
    """面を配るべき港: 出す方針の県で、半径 500 m に区分がある港。"""
    return {
        no for no, t in details.items()
        if t["policy"] == "redistribute" and t.get("radii") and t["radii"][-1]["max_rank"] is not None
    }


def scope_violations(shipped: set[str], details: dict[str, dict]) -> dict[str, list[str]]:
    expected = expected_area_ports(details)
    return {
        "missing": sorted(expected - shipped),
        "unexpected": sorted(shipped - expected),
        "excluded_policy": sorted(no for no in shipped if details.get(no, {}).get("policy") in EXCLUDED),
    }


def test_t060_files_exist_exactly_for_ports_with_areas(area_files, ports):
    """T-060 / G-33: 面のファイルがある港 = 出す県で区域が 500 m に掛かる港。出さない県の港には無い。300 KB 以下。"""
    details = {no: _detail_tsunami(no) for no in ports}
    assert scope_violations(set(area_files), details) == {"missing": [], "unexpected": [], "excluded_policy": []}
    too_big = {no: p.stat().st_size for no, p in area_files.items() if p.stat().st_size > MAX_BYTES}
    assert too_big == {}


def test_t060_positive_control_kyoto_file_is_detected(area_files, ports):
    """T-060 **陽性対照**: リンクだけの京都府の港番号のファイルが混ざると、範囲の検査が落ちる。"""
    details = {no: _detail_tsunami(no) for no in ports}
    kyoto = next(no for no, t in details.items() if t["policy"] == "link_only" and ports[no]["p"] == "京都府")
    violations = scope_violations(set(area_files) | {kyoto}, details)
    assert kyoto in violations["unexpected"] and kyoto in violations["excluded_policy"]
