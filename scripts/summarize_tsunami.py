"""津波浸水想定の構築結果を全国でまとめる(SPEC・解説に書く数の出所。HC-152)。

文書に書く数は手で数えず、このスクリプトの出力から写す。再実行すれば同じ数が出る。

使い方: python scripts/summarize_tsunami.py
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANON = ROOT / "data" / "canonical" / "tsunami_ports.json"
INTERIM = ROOT / "data" / "interim" / "tsunami"


def main() -> None:
    data = json.loads(CANON.read_text(encoding="utf-8"))
    meta, ports = data["meta"], data["ports"]
    order = meta["rank_order"]
    radii = meta["radii_m"]

    print(f"港 {len(ports):,}")
    print("方針ごとの港数:", dict(collections.Counter(p["policy"] for p in ports.values())))
    print("方針ごとの都道府県数:", dict(collections.Counter(e["policy"] for e in meta["policy"].values())))

    with_values = {k: p for k, p in ports.items() if p["radii"] is not None}
    redistribute = [p for p in ports.values() if p["policy"] == "redistribute"]
    print(f"出す県の港 {len(redistribute):,} / うち値のある港 {len(with_values):,} "
          f"(座標が無くて値の無い港 {len(redistribute) - len(with_values):,})")
    print(f"区分の並び({len(order)} 種): {order}")

    for i, radius in enumerate(radii):
        dist = collections.Counter(
            "区域が掛からない" if p["radii"][i]["max_rank"] is None else p["radii"][i]["max_rank"]
            for p in with_values.values()
        )
        none = dist.pop("区域が掛からない", 0)
        ordered = {label: dist[label] for label in order if dist.get(label)}
        print(f"R={radius} m: 区域が掛からない {none:,} / {ordered}")

    def level(entry):
        return -1 if entry["max_rank"] is None else order.index(entry["max_rank"])

    violations = sum(
        1 for p in with_values.values()
        if any(level(b) < level(a) for a, b in zip(p["radii"], p["radii"][1:]))
    )
    print(f"単調性の違反: {violations}")
    for a, b in zip(range(len(radii)), range(1, len(radii))):
        changed = sum(1 for p in with_values.values() if level(p["radii"][a]) != level(p["radii"][b]))
        print(f"R={radii[a]} → R={radii[b]} m で区分が変わった港: {changed:,}/{len(with_values):,} "
              f"({changed / len(with_values) * 100:.1f}%)")

    vintages_used = collections.Counter(
        e["vintage"] for p in with_values.values() for e in p["radii"] if e["vintage"] is not None
    )
    print("値に使われた年度:", dict(sorted(vintages_used.items())))

    totals = collections.Counter()
    print("\n県ごと(面の総数 / 港の近く / 年度で切り取り / 消えた / 年度):")
    for cache in sorted(INTERIM.glob("*.json")):
        r = json.loads(cache.read_text(encoding="utf-8"))
        s = r.get("stats", {})
        totals.update({k: v for k, v in s.items() if isinstance(v, int)})
        print(f"  {r['prefecture']:<5} {s.get('polygons_total', 0):>9,} {s.get('polygons_near_ports', 0):>8,} "
              f"{s.get('clipped', 0):>6,} {s.get('dropped_by_newer', 0):>6,}  {r.get('vintages')}")
    print("合計:", dict(totals))


if __name__ == "__main__":
    main()
