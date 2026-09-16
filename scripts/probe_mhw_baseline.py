"""L0 実測用プローブ(loop_010): 海洋熱波の検出の**土台**だけを測る。検出の結果(特定の年の事例)は見ない。

製品のコードではない。合否と予想を SPEC に登録する前に、次を測る。

1. 自前の平年の日別平均(1991〜2020 年、日付ごと、前後 5 日の窓 = 11 日)が、気象庁の平年値(-stat.txt の Norm.)と
   どれだけ合うか(非循環: 気象庁の平年値は別に配られている)。窓の幅 1 / 11 / 31 日で比べる
2. 平年期間内で、日付ごとの 90 パーセンタイル(11 日の窓)を超える日の割合(定義上およそ 10%。計算の陽性対照)
3. 平年期間内で「5 日以上連続」の条件を満たす日の割合(事例の多さの物差し。平年期間の外は見ない)
4. データの種類(R 確定 / P 速報)の境目と、2 月 29 日の扱い

使い方: python scripts/probe_mhw_baseline.py [海域番号 ...](既定は全海域)
"""

from __future__ import annotations

import collections
import statistics
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "jma_sst"
BASE = (1991, 2020)
MIN_DAYS = 5


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
            try:
                out[(int(parts[1]), int(parts[2]))] = float(parts[4])
            except ValueError:
                pass
    return out or None


def doy_key(d: date) -> int:
    """2 月 29 日を 2 月 28 日と同じ扱いにした、365 日の通し番号(0..364)。"""
    base = date(2001, d.month, 28 if (d.month == 2 and d.day == 29) else d.day)
    return base.timetuple().tm_yday - 1


def main(areas: list[str]) -> None:
    diffs = {w: [] for w in (1, 11, 31)}
    exceed_rates = []
    mhw_rates = []
    flags = collections.Counter()
    skipped = []
    for area in areas:
        norm = read_norm(area)
        rows = read_daily(area)
        if norm is None or not rows or rows[0][0].year > BASE[0]:
            skipped.append(area)
            continue
        flags.update(flag for _, flag, _ in rows)
        base_rows = [(d, v) for d, _, v in rows if BASE[0] <= d.year <= BASE[1]]
        by_doy = collections.defaultdict(list)
        for d, v in base_rows:
            by_doy[doy_key(d)].append(v)

        def window(doy: int, half: int) -> list[float]:
            vals = []
            for k in range(-half, half + 1):
                vals.extend(by_doy[(doy + k) % 365])
            return vals

        for w in diffs:
            for (m, dd), jma in norm.items():
                if m == 2 and dd == 29:
                    continue
                mean = statistics.fmean(window(doy_key(date(2001, m, dd)), w // 2))
                diffs[w].append(abs(mean - jma))

        thresh = {doy: float(np.percentile(window(doy, 5), 90)) for doy in range(365)}
        above = [v > thresh[doy_key(d)] for d, v in base_rows]
        exceed_rates.append(sum(above) / len(above))
        in_event = [False] * len(above)
        run = 0
        for i, flag in enumerate(above):
            run = run + 1 if flag else 0
            if run >= MIN_DAYS:
                for j in range(i - run + 1, i + 1):
                    in_event[j] = True
        mhw_rates.append(sum(in_event) / len(in_event))

    print(f"対象 {len(areas) - len(skipped)} 海域 / 平年期間の無い・短い海域で飛ばした {len(skipped)}: {skipped}")
    print("データの種類:", dict(flags))
    print("\n[1] 自前の平年の日別平均と気象庁の平年値の差(絶対値、℃)")
    for w, d in diffs.items():
        d = sorted(d)
        print(f"    窓 {w:>2} 日: 中央値 {statistics.median(d):.3f} / 95% {d[int(len(d) * 0.95)]:.3f} / 最大 {d[-1]:.3f}")
    print(f"\n[2] 平年期間内の 90 パーセンタイル超過率: 中央値 {statistics.median(exceed_rates):.4f} 最小 {min(exceed_rates):.4f} 最大 {max(exceed_rates):.4f}")
    print(f"[3] 平年期間内で 5 日以上連続の条件を満たす日の割合: 中央値 {statistics.median(mhw_rates):.4f} 最小 {min(mhw_rates):.4f} 最大 {max(mhw_rates):.4f}")


if __name__ == "__main__":
    wanted = sys.argv[1:]
    if not wanted:
        wanted = sorted({p.stem.replace("area", "").replace("-stat", "") for p in RAW.glob("area*.txt")})
    main(wanted)
