"""L0 実測用プローブ(loop_006): C09 の施設延長 0 は「無い」のか「記録が無い」のか。

loop_004 の学習表は係留施設延長・外郭施設延長の 0 をそのまま値として使った。
類似漁港のプローブで、規模 0 の港 164 が一つの群になった(HC-259 の縮退の形)。
0 が欠測の符号なら G-08(欠損を 0 で埋めない)違反なので、判定の前に次を数える。

1. C09 の列(名前・型)と、施設延長 0 の行で他の数値列も 0 か
2. 0 の行の都道府県ごとの偏り(記録の仕方の差なら少数の県に固まる)
3. 0 の近くの値の分布(0 と最小の正の値のあいだに隙間があるか)
4. 学習表に入った港での、0 の種別の内訳

使い方: python scripts/probe_c09_zeros.py > 出力ファイル
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import shapefile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data-pipeline"))

from ml.features import C09_POINT, _c09_attributes  # noqa: E402

PREF_TOTAL_MIN = 20


def main() -> None:
    reader = shapefile.Reader(str(C09_POINT), encoding="cp932")
    fields = [f[:2] for f in reader.fields[1:]]
    print("列:", fields)
    records = reader.records()
    reader.close()
    print(f"行 {len(records):,}")
    print("先頭 3 行:", [list(r) for r in records[:3]])

    outer_i, moor_i = 8, 9
    numeric = [i for i, (_, kind) in enumerate(fields) if kind in ("N", "F")]
    print("数値列の位置:", numeric)

    zero_moor = [r for r in records if float(r[moor_i]) == 0]
    zero_outer = [r for r in records if float(r[outer_i]) == 0]
    zero_both = [r for r in records if float(r[moor_i]) == 0 and float(r[outer_i]) == 0]
    print(f"\n[1] 係留 0: {len(zero_moor):,} / 外郭 0: {len(zero_outer):,} / 両方 0: {len(zero_both):,}")
    for i in numeric:
        if i in (outer_i, moor_i):
            continue
        z_all = sum(1 for r in records if r[i] in (0, 0.0))
        z_both = sum(1 for r in zero_both if r[i] in (0, 0.0))
        print(f"    列 {fields[i][0]}: 全体で 0 {z_all:,}/{len(records):,} / 両方 0 の行で 0 {z_both:,}/{len(zero_both):,}")
    negative = [r for r in records if float(r[moor_i]) < 0 or float(r[outer_i]) < 0]
    print(f"    負の値: {len(negative)}")

    print("\n[2] 都道府県ごと(行が 20 以上の県。0 の割合の降順)")
    by_pref = collections.defaultdict(lambda: [0, 0, 0, 0])
    for r in records:
        p = str(r[2])[:2]
        by_pref[p][0] += 1
        by_pref[p][1] += float(r[moor_i]) == 0
        by_pref[p][2] += float(r[outer_i]) == 0
        by_pref[p][3] += float(r[moor_i]) == 0 and float(r[outer_i]) == 0
    rows = [(p, *v) for p, v in by_pref.items() if v[0] >= PREF_TOTAL_MIN]
    rows.sort(key=lambda t: -(t[4] / t[1]))
    for p, total, zm, zo, zb in rows:
        print(f"    {p} 行 {total:>4} 係留0 {zm:>3}({zm / total:5.1%}) 外郭0 {zo:>3}({zo / total:5.1%}) 両方0 {zb:>3}({zb / total:5.1%})")
    concentrated = sorted(((v[3], p) for p, v in by_pref.items()), reverse=True)
    top = concentrated[:5]
    print(f"    両方 0 の上位 5 県: {top} / 合計 {sum(c for c, _ in top)}/{len(zero_both)}")

    print("\n[3] 小さい値の分布(m)")
    for name, idx in (("係留", moor_i), ("外郭", outer_i)):
        vals = sorted(float(r[idx]) for r in records if float(r[idx]) > 0)
        bins = collections.Counter()
        for v in vals:
            for edge in (1, 5, 10, 20, 50, 100):
                if v <= edge:
                    bins[edge] += 1
                    break
        print(f"    {name}: 最小の正の値 {vals[:5]} / (0,1] {bins[1]} (1,5] {bins[5]} (5,10] {bins[10]} "
              f"(10,20] {bins[20]} (20,50] {bins[50]} (50,100] {bins[100]}")
        print(f"          値の端数: 整数 {sum(1 for v in vals if v == int(v)):,}/{len(vals):,}")

    print("\n[4] 学習表に入った港での内訳(座標と同じ行選び)")
    ports = json.loads((ROOT / "data" / "canonical" / "ports.json").read_text(encoding="utf-8"))
    attrs = _c09_attributes(ports)
    by_no = {p["port_no"]: p for p in ports}
    cls_zero_moor = collections.Counter()
    cls_zero_both = collections.Counter()
    cls_all = collections.Counter()
    island_zero = collections.Counter()
    for no, (moor, outer) in attrs.items():
        c = by_no[no]["port_class"]
        cls_all[c] += 1
        if moor == 0:
            cls_zero_moor[c] += 1
        if moor == 0 and outer == 0:
            cls_zero_both[c] += 1
            island_zero[by_no[no]["island_peninsula"]] += 1
    cls_zero_any = collections.Counter(
        by_no[no]["port_class"] for no, (m, o) in attrs.items() if m == 0 or o == 0
    )
    for c in ("1", "2", "3", "special_3", "4"):
        print(f"    種別 {c}: 港 {cls_all[c]:>4} 係留0 {cls_zero_moor[c]:>3} 両方0 {cls_zero_both[c]:>3} "
              f"どちらか0 {cls_zero_any[c]:>3} → 0 を欠測にすると {cls_all[c] - cls_zero_any[c]:>4}")
    print(f"    合計: 港 {sum(cls_all.values()):,} / どちらか 0 {sum(cls_zero_any.values()):,} / "
          f"残り {sum(cls_all.values()) - sum(cls_zero_any.values()):,}")
    print("    両方 0 の港の離島・半島区分:", dict(island_zero))
    named = [by_no[no] for no, (m, o) in attrs.items() if m == 0 and o == 0 and by_no[no]["port_class"] != "1"]
    print("    両方 0 の第1種以外(最大 10 件):",
          [(p["port_no"], p["name_ja"], p["prefecture"], p["port_class"]) for p in named[:10]])


if __name__ == "__main__":
    main()
