"""DS-003 気象庁 沿岸海面水温の TXT を正規化する。

## ファイル形式(eg_info.html の記載を実物で確かめた。2026-09-09)

日別値 `area{N}.txt`:

```
yyyy,mm,dd,areaNo.,flag,Temp.
1982,01,01,137,R, 15.14
```

- `flag` は `P`(速報値)/ `R`(再解析値)
- 欠測は `-9999`

平年値・5年統計値 `area{N}-stat.txt`(実物 2026-09-09):

```
Period of Norm. : 1991-2020
Period of Ave./Max./Min. : 2021-2025
yyyy,mm,dd,areaNo.,Norm.,Ave.,Max.,Min.
0000,01,01,101, 1.80, 2.74, 4.66, 1.65
```

- **表頭の前に期間を書いた行が 2 本ある。** 平年値の期間はここから読む
  (「1991–2020」と決め打ちしない —— 気象庁は平年値を 10 年ごとに更新する)
- 平年値が存在しない海域がある(瀬戸内海の速報のみ海域)。その場合は偏差を出さない

## 仮定と、その場で落ちる検算

- A1: 1 行 6 列(日別)/ 8 列(統計)である → 違えば例外
- A2: ファイル名の海域番号と行の海域番号が一致する → 違えば例外
- A3: 日付が暦日として妥当で、同じ日が 2 度現れない → 違えば例外
- A4: 欠測でない水温は -5〜40℃ に入る → 違えば例外(SPEC の port-year.schema と同じ範囲)
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "jma_sst"
OUT = ROOT / "data" / "normalized"

MISSING = -9999.0
SST_MIN, SST_MAX = -5.0, 40.0

FILE_RE = re.compile(r"^area(\d+)(-stat)?\.txt$")


class SstError(RuntimeError):
    pass


@dataclass(frozen=True)
class AreaSeries:
    area_no: str
    area_name: str
    daily: dict[date, tuple[float, str]]      # 日付 -> (水温, フラグ)
    normal: dict[tuple[int, int], float]      # (月, 日) -> 平年値
    has_normal: bool
    normal_period: str | None                 # 平年値の期間(ファイル冒頭の記載)


def _num(token: str) -> float | None:
    value = float(token)
    return None if value == MISSING else value


def parse_daily(path: Path, area_no: str) -> dict[date, tuple[float, str]]:
    out: dict[date, tuple[float, str]] = {}
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("yyyy"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 6:
            raise SstError(f"{path.name}:{lineno} 列数が {len(parts)}(期待 6)")
        if parts[3] != area_no:
            raise SstError(f"{path.name}:{lineno} 海域番号 {parts[3]} がファイル名と不一致")
        try:
            day = date(int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError as exc:
            raise SstError(f"{path.name}:{lineno} 日付が不正: {line}") from exc
        if day in out:
            raise SstError(f"{path.name}:{lineno} 同じ日が 2 度現れる: {day}")
        value = _num(parts[5])
        if value is None:
            continue
        if not SST_MIN <= value <= SST_MAX:
            raise SstError(f"{path.name}:{lineno} 水温が範囲外: {value}")
        flag = parts[4]
        if flag not in {"P", "R"}:
            raise SstError(f"{path.name}:{lineno} 未知のフラグ {flag!r}")
        out[day] = (value, flag)
    return out


NORMAL_PERIOD_RE = re.compile(r"Period of Norm\.\s*:\s*(\d{4})-(\d{4})")


def parse_stat(path: Path, area_no: str) -> tuple[dict[tuple[int, int], float], str | None]:
    """平年値と、その平年値の期間(ファイル冒頭の記載)を返す。"""
    out: dict[tuple[int, int], float] = {}
    period: str | None = None
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("yyyy"):
            continue
        m = NORMAL_PERIOD_RE.match(line)
        if m:
            period = f"{m.group(1)}-{m.group(2)}"
            continue
        if line.startswith("Period"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 8:
            raise SstError(f"{path.name}:{lineno} 列数が {len(parts)}(期待 8)")
        if parts[3] != area_no:
            raise SstError(f"{path.name}:{lineno} 海域番号 {parts[3]} がファイル名と不一致")
        try:
            month, day = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        value = _num(parts[4])
        if value is None:
            continue
        if not SST_MIN <= value <= SST_MAX:
            raise SstError(f"{path.name}:{lineno} 平年値が範囲外: {value}")
        out[(month, day)] = value
    return out, period


def load_all() -> list[AreaSeries]:
    manifest = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))
    names = {a["area_no"]: a["area_name"] for a in manifest["areas"]}

    series: list[AreaSeries] = []
    for area_no, area_name in sorted(names.items()):
        daily_path = RAW / f"area{area_no}.txt"
        if not daily_path.exists():
            continue
        daily = parse_daily(daily_path, area_no)
        stat_path = RAW / f"area{area_no}-stat.txt"
        normal, period = parse_stat(stat_path, area_no) if stat_path.exists() else ({}, None)
        series.append(
            AreaSeries(
                area_no,
                area_name,
                daily,
                normal,
                has_normal=bool(normal),
                normal_period=period,
            )
        )
    if not series:
        raise SstError(f"海域の系列を 1 件も読めなかった: {RAW}")
    return series


def annual_summary(area: AreaSeries) -> dict[int, dict]:
    """年ごとの平均・最低・最高・有効日数・偏差。

    偏差は「日ごとに平年値を引いた差」の平均である。年平均どうしの差ではない ——
    欠測が季節に偏っている年で、両者は一致しない。
    """
    buckets: dict[int, list[tuple[float, float | None, str]]] = defaultdict(list)
    for day, (value, flag) in area.daily.items():
        normal = area.normal.get((day.month, day.day))
        buckets[day.year].append((value, normal, flag))

    out: dict[int, dict] = {}
    for year, rows in sorted(buckets.items()):
        values = [v for v, _, _ in rows]
        diffs = [v - n for v, n, _ in rows if n is not None]
        out[year] = {
            "mean": round(sum(values) / len(values), 3),
            "min": round(min(values), 3),
            "max": round(max(values), 3),
            "valid_days": len(values),
            # 速報値(P)の日数。再解析値(R)との系統差がトレンドに乗っていないかを
            # 後段で確かめるために残す。捨てると確かめようがなくなる。
            "provisional_days": sum(1 for _, _, f in rows if f == "P"),
            "anomaly": round(sum(diffs) / len(diffs), 3) if diffs else None,
        }
    return out


def monthly_climatology(area: AreaSeries) -> list[float | None]:
    """平年値の月平均(1–12)。平年値が無い海域は None が並ぶ。"""
    buckets: dict[int, list[float]] = defaultdict(list)
    for (month, _day), value in area.normal.items():
        buckets[month].append(value)
    return [
        round(sum(buckets[m]) / len(buckets[m]), 3) if buckets.get(m) else None
        for m in range(1, 13)
    ]


def build() -> Path:
    series = load_all()
    OUT.mkdir(parents=True, exist_ok=True)

    payload = []
    for area in series:
        annual = annual_summary(area)
        days = sorted(area.daily)
        payload.append(
            {
                "area_no": area.area_no,
                "area_name": area.area_name,
                "first_date": days[0].isoformat(),
                "last_date": days[-1].isoformat(),
                "total_days": len(days),
                "has_normal": area.has_normal,
                "normal_period": area.normal_period,
                "annual": {str(y): v for y, v in annual.items()},
                "monthly_normal": monthly_climatology(area),
            }
        )

    out = OUT / "jma_sst_annual.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    with_normal = sum(1 for p in payload if p["has_normal"])
    total_days = sum(p["total_days"] for p in payload)
    print(f"海域 {len(payload)} / 平年値あり {with_normal} / 日別値 {total_days:,} 日 -> {out}")
    return out


if __name__ == "__main__":
    build()
