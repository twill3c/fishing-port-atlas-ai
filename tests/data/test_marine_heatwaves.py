"""海洋熱波(異常検知)の検査。loop_010。ゲートは SPEC §4 G-35〜G-38、予想は §7.6 E6〜E8(実測前に登録)。

- 平年の照合は、気象庁が別に配る平年値(`-stat.txt`)と比べる(非循環)
- 閾値は numpy を使わず並べ替えと線形補間で計算し直す(独立の経路)
- 事例の数え方は、答えが定義から決まる合成の系列で確かめる
- 予想の成否は、報告の事例から数え直す(報告の自己申告を信じない)
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_REPORT = ROOT / "public" / "data" / "ocean" / "marine-heatwaves.json"
RAW = ROOT / "data" / "raw" / "jma_sst"
BASE = (1991, 2020)

sys.path.insert(0, str(ROOT / "data-pipeline"))

pytestmark = pytest.mark.validation


@pytest.fixture(scope="module")
def report() -> dict:
    if not PUBLIC_REPORT.exists():
        # skip にしない —— 報告が無いまま緑になると、G-35〜G-38 を誰も守っていないのに守られて見える
        pytest.fail("marine-heatwaves.json が無い(python data-pipeline/integrate/build_marine_heatwaves.py と export_web.py)")
    return json.loads(PUBLIC_REPORT.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- G-36(生データを読む)


def _jma_norm(area: str) -> dict[tuple[int, int], float]:
    out = {}
    for line in (RAW / f"area{area}-stat.txt").read_text(encoding="utf-8").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 8 and parts[0] == "0000" and parts[4]:
            out[(int(parts[1]), int(parts[2]))] = float(parts[4])
    return out


def test_t062_climatology_matches_jma_normals(report):
    """T-062 / G-36: 報告の平年(11 日の窓)と気象庁の平年値の差が、中央値 0.05 ℃以下・最大 0.5 ℃以下。"""
    from _ci_skips import require_raw  # noqa: PLC0415

    require_raw("jma_sst/area101-stat.txt", "python data-pipeline/download/fetch_jma_sst.py")
    diffs = []
    for area, entry in report["areas"].items():
        norm = _jma_norm(area)
        for (m, d), jma in norm.items():
            if m == 2 and d == 29:
                continue
            doy = date(2001, m, d).timetuple().tm_yday - 1
            diffs.append(abs(entry["climatology_mean"][doy] - jma))
    assert len(report["areas"]) == 102
    assert statistics.median(diffs) <= 0.05
    assert max(diffs) <= 0.5


# ---------------------------------------------------------------- G-35 / G-37(生データを読む)


def _percentile_linear(values: list[float], q: float) -> float:
    """numpy.percentile の既定(linear)を、並べ替えと線形補間だけで書き直したもの。"""
    xs = sorted(values)
    pos = (len(xs) - 1) * q / 100
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _baseline_by_doy(area: str) -> dict[int, list[float]]:
    by_doy: dict[int, list[float]] = {i: [] for i in range(365)}
    for line in (RAW / f"area{area}.txt").read_text(encoding="utf-8").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 6 or not parts[0].isdigit():
            continue
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        if not BASE[0] <= y <= BASE[1]:
            continue
        doy = date(2001, m, 28 if (m == 2 and d == 29) else d).timetuple().tm_yday - 1
        by_doy[doy].append(float(parts[5]))
    return by_doy


def test_t063_thresholds_recomputed_independently(report):
    """T-063 / G-35: 抜き取り 5 海域で、11 日の窓の 90 パーセンタイルを独立に計算し直し、報告と 1e-9 で一致。"""
    from _ci_skips import require_raw  # noqa: PLC0415

    require_raw("jma_sst/area101.txt", "python data-pipeline/download/fetch_jma_sst.py")
    for area in sorted(report["areas"])[::21][:5]:
        by_doy = _baseline_by_doy(area)
        for doy in range(365):
            window = [v for k in range(-5, 6) for v in by_doy[(doy + k) % 365]]
            assert report["areas"][area]["threshold_p90"][doy] == pytest.approx(_percentile_linear(window, 90), abs=1e-9), (area, doy)


def test_t063_baseline_exceedance_rate_and_mutant(report):
    """T-063 / G-37: 平年期間内の 90 パーセンタイル超過率が全海域で 5〜15%。50 パーセンタイルの変異体は外れる。"""
    rates = [entry["baseline_exceed_rate"] for entry in report["areas"].values()]
    assert all(0.05 <= r <= 0.15 for r in rates), (min(rates), max(rates))
    assert report["gates"]["G-37"]["passed"] is True
    mutant = report["gates"]["G-37"]["mutant_p50_exceed_rate_median"]
    assert not 0.05 <= mutant <= 0.15, mutant


# ---------------------------------------------------------------- G-35(合成の系列)


def _series(pattern: str, start: date = date(2023, 6, 1)):
    """pattern の 1 文字が 1 日。'H' は閾値超え、'.' は下回る、'P' は速報値で閾値超え。"""
    days = [start + timedelta(days=i) for i in range(len(pattern))]
    thresh = 20.0
    values = [21.0 if c in "HP" else 19.0 for c in pattern]
    flags = ["P" if c == "P" else "R" for c in pattern]
    return days, values, flags, thresh


def test_t064_event_rules_on_synthetic_series():
    """T-064 / G-35: 4 日は事例にならず 5 日はなる。2 日の途切れはつながり 3 日は分かれる。速報値を含むと印が付く。"""
    from integrate.build_marine_heatwaves import detect_events  # noqa: PLC0415

    def run(pattern):
        days, values, flags, thresh = _series(pattern)
        return detect_events(days, values, flags, threshold=lambda d: thresh, mean=lambda d: 19.5)

    assert run("..HHHH..") == []
    five = run("..HHHHH..")
    assert len(five) == 1 and five[0]["duration_days"] == 5 and five[0]["start"] == "2023-06-03"
    joined = run("HHHHH..HHHHH")
    assert len(joined) == 1 and joined[0]["duration_days"] == 12
    split = run("HHHHH...HHHHH")
    assert len(split) == 2
    assert run("HHPHH")[0]["provisional"] is True
    assert run("HHHHH")[0]["provisional"] is False
    assert five[0]["max_intensity"] == pytest.approx(1.5)


# ---------------------------------------------------------------- G-38


def test_t065_baseline_and_after_are_reported_separately(report):
    """T-065 / G-38: 平年期間内と後の頻度が別々にあり、両者を混ぜた順位の欄が無い。港の海洋の欄は対応なしのまま。"""
    for area, entry in report["areas"].items():
        share = entry["mhw_day_share"]
        assert set(share) == {"baseline", "after"}, area
        assert "rank" not in entry and "score" not in entry, area
    detail = json.loads((ROOT / "public" / "data" / "ports" / "1110050.json").read_text(encoding="utf-8"))
    assert detail["ocean"]["status"] == "not_available"


# ---------------------------------------------------------------- E6〜E8


def _days_in(events: list[dict], start: date, end: date) -> int:
    covered = set()
    for e in events:
        s = date.fromisoformat(e["start"])
        for i in range(e["duration_days"]):
            d = s + timedelta(days=i)
            if start <= d <= end:
                covered.add(d)
    return len(covered)


def test_t066_expectations_recomputed_from_events(report):
    """T-066: 予想 E6〜E8 の成否を、報告の事例から数え直して一致させる(外れも出荷する)。"""
    exp = report["expectations"]
    assert set(exp) == {"E6", "E7", "E8"}
    summer = (date(2023, 6, 1), date(2023, 8, 31))
    for key, areas in (("E6", ("132", "133", "135")), ("E7", ("121", "122", "123"))):
        counts = {a: _days_in(report["areas"][a]["events"], *summer) for a in areas}
        held = sum(1 for c in counts.values() if c >= 46) >= 2
        assert exp[key]["held"] is held, (key, counts)
        assert exp[key]["declared"] and exp[key]["observed"]
    higher = sum(1 for e in report["areas"].values() if e["mhw_day_share"]["after"] > e["mhw_day_share"]["baseline"])
    assert exp["E8"]["held"] is (higher > len(report["areas"]) / 2)
