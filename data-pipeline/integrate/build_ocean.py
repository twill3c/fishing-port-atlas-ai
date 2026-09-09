"""海域ごとの海面水温トレンドを出す。

## 何を測るか

海域ごとに、**完全な年**の年平均水温を年に対して最小二乗回帰し、傾き(℃/10年)と
その有意性を出す。「完全な年」は有効日数が閾値以上の年で、部分年(取得時点の当年)は外す。

## 測らないと決めたこと(実測 2026-09-09)

漁港と海域の対応は付けない。気象庁は海域ポリゴンを配布しておらず、
海域名から場所を引く規則を書いて実測すると **107 海域のうち都道府県名を含むのは 29** で、
市町村名での照合は偽の一致を出した —— 青森県深浦町(日本海側)が
郡名「西津軽郡」経由で「津軽海峡」に当たる。近いから、たぶんここだろう、では割り当てない。

## 有意性の出し方

回帰係数の t 検定(自由度 n-2)。年平均どうしは独立ではない(自己相関がある)ので、
**p 値は目安であり、傾きの符号と大きさを読むための添え物**である。
この但し書きは画面にも出す。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
NORM = ROOT / "data" / "normalized"
RAW = ROOT / "data" / "raw" / "jma_sst"
CANON = ROOT / "data" / "canonical"

# 年平均に採用する最低有効日数。1 年 365 日のうち 9 割。
MIN_VALID_DAYS = 330


class OceanError(RuntimeError):
    pass


def ols_trend(years: list[int], values: list[float]) -> dict:
    """最小二乗回帰。傾きは ℃/10年 に直して返す。

    numpy の polyfit ではなく、正規方程式を素直に書く。
    TypeScript 側(tests/frontend/ocean.test.ts)が同じ式を独立に実装し、
    出荷した年系列から同じ値を再現できることを確かめる(SPEC G-12)。
    """
    n = len(years)
    if n < 10:
        raise OceanError(f"年数が {n} 件では回帰しない")
    x = np.asarray(years, dtype=float)
    y = np.asarray(values, dtype=float)
    x_mean, y_mean = x.mean(), y.mean()
    sxx = float(((x - x_mean) ** 2).sum())
    sxy = float(((x - x_mean) * (y - y_mean)).sum())
    slope = sxy / sxx
    intercept = y_mean - slope * x_mean
    resid = y - (slope * x + intercept)
    sse = float((resid**2).sum())
    sst_total = float(((y - y_mean) ** 2).sum())
    se = float(np.sqrt(sse / (n - 2) / sxx))
    t = slope / se if se > 0 else float("inf")
    p = float(2 * stats.t.sf(abs(t), df=n - 2))
    return {
        "slope_per_decade": round(slope * 10, 4),
        "se_per_decade": round(se * 10, 4),
        "t": round(t, 3),
        "p": p,
        "r2": round(1 - sse / sst_total, 4) if sst_total > 0 else None,
        "n_years": n,
        "first_year": int(x.min()),
        "last_year": int(x.max()),
    }


def build() -> Path:
    areas = json.loads((NORM / "jma_sst_annual.json").read_text(encoding="utf-8"))
    manifest = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))
    regions = {a["area_no"]: a["region"] for a in manifest["areas"]}

    out_areas = []
    for area in areas:
        annual = area["annual"]
        complete = {
            int(y): v
            for y, v in annual.items()
            if v["valid_days"] >= MIN_VALID_DAYS
        }
        if not complete:
            raise OceanError(f"{area['area_no']}: 完全な年が 1 つも無い")
        years = sorted(complete)
        trend = ols_trend(years, [complete[y]["mean"] for y in years])

        series = [
            {
                "y": y,
                "mean": complete[y]["mean"],
                "min": complete[y]["min"],
                "max": complete[y]["max"],
                "anomaly": complete[y]["anomaly"],
            }
            for y in years
        ]
        out_areas.append(
            {
                "area_no": area["area_no"],
                "area_name": area["area_name"],
                "region": regions[area["area_no"]],
                "has_normal": area["has_normal"],
                "normal_period": area["normal_period"],
                "monthly_normal": area["monthly_normal"],
                "last_observation": area["last_date"],
                "trend": trend,
                "series": series,
            }
        )

    # 部分年(取得時点の当年)が外れていることを、その場で確かめる
    dropped = {
        a["area_no"]
        for a in areas
        if max(int(y) for y in a["annual"]) not in {s["y"] for s in next(
            o["series"] for o in out_areas if o["area_no"] == a["area_no"]
        )}
    }
    if not dropped:
        raise OceanError("部分年が 1 つも落ちていない。有効日数の閾値が効いていない")

    CANON.mkdir(parents=True, exist_ok=True)
    out = CANON / "ocean_areas.json"
    out.write_text(json.dumps(out_areas, ensure_ascii=False, indent=1), encoding="utf-8")

    slopes = [a["trend"]["slope_per_decade"] for a in out_areas]
    rising = sum(1 for s in slopes if s > 0)
    sig = sum(1 for a in out_areas if a["trend"]["p"] < 0.05 and a["trend"]["slope_per_decade"] > 0)
    print(f"海域 {len(out_areas)} -> {out}")
    print(f"傾きが正: {rising}/{len(out_areas)} / うち p<0.05: {sig}")
    print(f"傾きの中央値: {float(np.median(slopes)):+.3f} ℃/10年")
    print(f"最大: {max(slopes):+.3f} / 最小: {min(slopes):+.3f}")
    print(f"部分年を落とした海域: {len(dropped)}")
    return out


if __name__ == "__main__":
    build()
