"""海域ごとの海洋熱波(異常検知)。SPEC §4 G-35〜G-38 / §7.6 E6〜E8(実測前に登録)。

## 定義(G-35)

気象庁・東京大学・北海道大学・海洋研究開発機構の報道発表(2024-07-19)の用語注に合わせる:
「その海域・時期としては 10 年に 1 度程度(10%)しか起きないような著しく高い海面水温が 5 日以上連続」。

- 平年期間は 1991〜2020 年(気象庁の平年値と同じ)
- 日付ごとに、前後 5 日(11 日の窓)の平年期間の値から、平年(平均)と 90 パーセンタイル(numpy の線形補間)を作る
- 閾値を 5 日以上続けて超えた区間を事例の候補にし、候補どうしの途切れが 2 日以下ならつなぐ
- 2 月 29 日は 2 月 28 日と同じ日付として扱う。日付が飛んでいたらそこで区切る
- 平年期間を持たない海域(瀬戸内海の 5 海域は 2016 年から)は出さない
- 速報値(P)の日を含む事例には印を付ける

## 期間を分ける(G-38)

平年は固定なので、温暖化の傾き(§7.2)がそのまま平年期間後の事例を増やす。
平年期間内と後の頻度を別々に出し、両者を混ぜた順位は作らない。
気象大気アトラスでは、異常度が「その期間が学習に使われたか」を測っていた(HC-251)。

使い方: python data-pipeline/integrate/build_marine_heatwaves.py
"""

from __future__ import annotations

import collections
import json
import statistics
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "jma_sst"
CANON = ROOT / "data" / "canonical"
OUT = CANON / "marine_heatwaves.json"

BASE = (1991, 2020)
WINDOW_HALF = 5
PERCENTILE = 90
MIN_DAYS = 5
MAX_GAP = 2
AFTER_START = date(BASE[1] + 1, 1, 1)

SOURCE = (
    "気象庁・東京大学・北海道大学・海洋研究開発機構 報道発表「2023年北日本の歴代1位の暑夏への海洋熱波の影響がより明らかに」"
    "(2024-07-19)の用語注の定義"
)

DECLARED = {
    "E6": "2023 年 6〜8 月、岩手県北部沿岸(132)・岩手県南部沿岸(133)・宮城県沿岸(135)の 2 海域以上で、海洋熱波の日が 46 日(期間の半分)以上",
    "E7": "同じ期間、十勝地方沿岸(121)・釧路地方沿岸(122)・根室地方太平洋沿岸(123)の 2 海域以上で、海洋熱波の日が 46 日以上",
    "E8": "平年期間より後(2021 年〜)の海洋熱波の日の割合が、平年期間内より高い海域が過半数",
}


def doy_key(d: date) -> int:
    """2 月 29 日を 2 月 28 日に寄せた、365 日の通し番号(0..364)。"""
    return date(2001, d.month, 28 if (d.month == 2 and d.day == 29) else d.day).timetuple().tm_yday - 1


def read_daily(area: str) -> list[tuple[date, str, float]]:
    rows = []
    for line in (RAW / f"area{area}.txt").read_text(encoding="utf-8").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 6 or not parts[0].isdigit():
            continue
        rows.append((date(int(parts[0]), int(parts[1]), int(parts[2])), parts[4], float(parts[5])))
    return rows


def read_norm(area: str) -> dict[tuple[int, int], float] | None:
    path = RAW / f"area{area}-stat.txt"
    if not path.exists():
        return None
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 8 and parts[0] == "0000" and parts[4]:
            out[(int(parts[1]), int(parts[2]))] = float(parts[4])
    return out or None


def climatology(rows: list[tuple[date, str, float]], percentile: float = PERCENTILE) -> tuple[list[float], list[float]]:
    """(平年 365, 閾値 365)。平年期間の値を日付ごとに集め、前後 WINDOW_HALF 日の窓で平均とパーセンタイルを取る。"""
    by_doy: dict[int, list[float]] = collections.defaultdict(list)
    for d, _, v in rows:
        if BASE[0] <= d.year <= BASE[1]:
            by_doy[doy_key(d)].append(v)
    means, thresholds = [], []
    for doy in range(365):
        window = [v for k in range(-WINDOW_HALF, WINDOW_HALF + 1) for v in by_doy[(doy + k) % 365]]
        if not window:
            raise RuntimeError(f"日付 {doy} の平年期間の値が無い")
        means.append(statistics.fmean(window))
        thresholds.append(float(np.percentile(window, percentile)))
    return means, thresholds


def detect_events(
    days: list[date],
    values: list[float],
    flags: list[str],
    threshold: Callable[[date], float],
    mean: Callable[[date], float],
) -> list[dict]:
    """閾値を MIN_DAYS 日以上続けて超えた区間を事例にし、途切れが MAX_GAP 日以下の事例どうしをつなぐ。"""
    runs: list[list[int]] = []  # 閾値を連続して超えた日の添字 [開始, 終了]
    for i, (d, v) in enumerate(zip(days, values)):
        above = v > threshold(d)
        contiguous = i > 0 and (d - days[i - 1]).days == 1
        if above and runs and runs[-1][1] == i - 1 and contiguous:
            runs[-1][1] = i
        elif above:
            runs.append([i, i])
    candidates = [r for r in runs if r[1] - r[0] + 1 >= MIN_DAYS]

    merged: list[list[int]] = []
    for r in candidates:
        if merged:
            gap = (days[r[0]] - days[merged[-1][1]]).days - 1
            if gap <= MAX_GAP:
                merged[-1][1] = r[1]
                continue
        merged.append(list(r))

    events = []
    for s, e in merged:
        intensity = [values[i] - mean(days[i]) for i in range(s, e + 1)]
        events.append({
            "start": days[s].isoformat(),
            "end": days[e].isoformat(),
            "duration_days": (days[e] - days[s]).days + 1,
            "max_intensity": max(intensity),
            "mean_intensity": statistics.fmean(intensity),
            "provisional": any(flags[i] == "P" for i in range(s, e + 1)),
        })
    return events


def _event_days(events: list[dict]) -> set[date]:
    covered = set()
    for ev in events:
        start = date.fromisoformat(ev["start"])
        covered.update(start + timedelta(days=i) for i in range(ev["duration_days"]))
    return covered


def build() -> Path:
    areas_meta = {str(a["area_no"]): a for a in json.loads((CANON / "ocean_areas.json").read_text(encoding="utf-8"))}
    out_areas: dict[str, dict] = {}
    norm_diffs: list[float] = []
    mutant_rates: list[float] = []
    for area in sorted(areas_meta):
        norm = read_norm(area)
        rows = read_daily(area)
        if norm is None or not rows or rows[0][0].year > BASE[0]:
            continue  # 平年期間を持たない海域は出さない(G-35)
        means, thresholds = climatology(rows)
        _, mutant = climatology(rows, percentile=50)

        days = [d for d, _, _ in rows]
        values = [v for _, _, v in rows]
        flags = [f for _, f, _ in rows]
        base_idx = [i for i, d in enumerate(days) if BASE[0] <= d.year <= BASE[1]]
        exceed = sum(values[i] > thresholds[doy_key(days[i])] for i in base_idx) / len(base_idx)
        mutant_rates.append(sum(values[i] > mutant[doy_key(days[i])] for i in base_idx) / len(base_idx))

        for (m, dd), jma in norm.items():
            if not (m == 2 and dd == 29):
                norm_diffs.append(abs(means[date(2001, m, dd).timetuple().tm_yday - 1] - jma))

        events = detect_events(days, values, flags, lambda d: thresholds[doy_key(d)], lambda d: means[doy_key(d)])
        covered = _event_days(events)
        base_days = [days[i] for i in base_idx]
        after_days = [d for d in days if d >= AFTER_START]
        out_areas[area] = {
            "area_name": areas_meta[area]["area_name"],
            "region": areas_meta[area]["region"],
            "last_observation": days[-1].isoformat(),
            "climatology_mean": means,
            "threshold_p90": thresholds,
            "baseline_exceed_rate": exceed,
            "mhw_day_share": {
                "baseline": sum(d in covered for d in base_days) / len(base_days),
                "after": sum(d in covered for d in after_days) / len(after_days) if after_days else None,
            },
            "events": events,
        }

    # ---- ゲート(判定の式は実測前に登録した SPEC のとおり)
    g36 = {"median": statistics.median(norm_diffs), "max": max(norm_diffs)}
    g36["passed"] = g36["median"] <= 0.05 and g36["max"] <= 0.5
    rates = [a["baseline_exceed_rate"] for a in out_areas.values()]
    g37 = {
        "min": min(rates),
        "max": max(rates),
        "mutant_p50_exceed_rate_median": statistics.median(mutant_rates),
        "passed": all(0.05 <= r <= 0.15 for r in rates),
    }

    # ---- 予想(文面は SPEC §7.6 のまま)
    summer = (date(2023, 6, 1), date(2023, 8, 31))

    def summer_days(area: str) -> int:
        return sum(1 for d in _event_days(out_areas[area]["events"]) if summer[0] <= d <= summer[1])

    expectations = {}
    for key, group in (("E6", ("132", "133", "135")), ("E7", ("121", "122", "123"))):
        counts = {a: summer_days(a) for a in group}
        expectations[key] = {
            "declared": DECLARED[key],
            "observed": " / ".join(f"{out_areas[a]['area_name']} {c} 日" for a, c in counts.items()) + "(2023 年 6〜8 月の 92 日のうち)",
            "held": sum(1 for c in counts.values() if c >= 46) >= 2,
        }
    higher = sum(1 for a in out_areas.values() if a["mhw_day_share"]["after"] > a["mhw_day_share"]["baseline"])
    expectations["E8"] = {
        "declared": DECLARED["E8"],
        "observed": f"{len(out_areas)} 海域のうち {higher} 海域で平年期間後のほうが高い",
        "held": higher > len(out_areas) / 2,
    }

    report = {
        "definition": {
            "source": SOURCE,
            "baseline": list(BASE),
            "window_days": 2 * WINDOW_HALF + 1,
            "percentile": PERCENTILE,
            "min_days": MIN_DAYS,
            "max_gap_days": MAX_GAP,
            "feb29": "2 月 28 日と同じ日付として扱う",
        },
        "gates": {"G-36": g36, "G-37": g37},
        "expectations": expectations,
        "areas": out_areas,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    print(f"海域 {len(out_areas)} / G-36 平年の差 中央値 {g36['median']:.3f} 最大 {g36['max']:.3f} -> {g36['passed']}")
    print(f"G-37 超過率 {g37['min']:.4f}〜{g37['max']:.4f}(変異体 p50 中央値 {g37['mutant_p50_exceed_rate_median']:.3f})-> {g37['passed']}")
    for key, e in expectations.items():
        print(f"{key} {'成立' if e['held'] else '不成立'}: {e['observed']}")
    return OUT


if __name__ == "__main__":
    build()
