"""学習表(1 港 1 行)を作る。SPEC §7.3 / G-08 / G-17。

問いは「公式の種別は、施設の規模で読めるのか」。種別は法令上「利用範囲」で定義されており、
規模ではない。だから特徴の選び方そのものが結論を左右する —— 何を入れ、何を入れないかを
ここに一か所で持ち、テスト(T-037)が禁止リストとの交わりを見る。

## 入れないもの(G-17)

- **漁港管理者の区分**: 第3・第4種はほぼ都道府県が管理する。種別の帰結であって手がかりではない
  (予想 E5 で、これだけで当たってしまうことを陽性対照として測る)
- **座標・都道府県・市町村**: 地域を覚えて当ててしまう
- **漁港番号・港名**: 識別子

## 施設延長が何の数か(G-24、loop_006)

C09 のメタデータは、外郭施設延長・係留施設延長を「普通交付税算定基準に基づく数値であり、
実際の施設延長数値とは異なる」と書いている。**施設の規模そのものではなく、交付税の算定に使う数**。
規模と相関はするはずだが、同じものとして呼ばない。

## 欠損の扱い(G-08 / G-23)

- 施設延長(C09)が無い港は**学習表に入れない**。0 で埋めない
- **C09 の施設延長 0 は欠測の符号**(実測 2026-09-15: 八戸・釜石・舞鶴・油津が係留も外郭も 0、
  0 は青森 46.2%・岩手 37.2% に固まり、正の値は最小 3 m の整数で 0 と連続しない)。
  係留・外郭のどちらかが 0 の港は学習表に入れない。0 と 3 m のあいだの値が現れたら仮定が崩れたので止める
- 記号欄の空欄は「指定なし」であり欠測ではないので 0 にする(水産庁の一覧の書式)
- 仮定が崩れたら黙って通さず例外にする(HC-075): 未知の記号・未知の離島半島区分・
  読めない指定年月日
"""

from __future__ import annotations

import collections
import json
import math
import re
from pathlib import Path

import shapefile

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "data" / "canonical"
C09_POINT = ROOT / "data" / "raw" / "ksj" / "C09-06" / "C09-06_FishingPort"

CLASSES = ("1", "2", "3", "special_3", "4")

# C09 の施設延長の正の値の最小(実測 2026-09-15、scripts/probe_c09_zeros.py)。0 はこれと連続しない
MIN_POSITIVE_LENGTH_M = 3.0

WHITE_CIRCLE = "○"  # ○
BULLSEYE = "◎"  # ◎

FEATURES_SCALE = ("log_mooring_m", "log_outer_m")
FEATURES_FULL = FEATURES_SCALE + (
    "is_island",
    "is_peninsula",
    "is_border_island",
    "port_regulation_circle",
    "port_regulation_double",
    "visitor_berth",
    "subdistrict_count",
    "coast_conservation_circle",
    "coast_conservation_double",
    "designation_year",
)
FORBIDDEN_FEATURES = (
    "administrator_type",
    "administrator_name",
    "lat",
    "lon",
    "pref_code",
    "prefecture",
    "municipality",
    "fishery_coop",
    "port_no",
    "name_ja",
)

# 離島・半島欄の値(実測 2026-09-14: 半島 833 / 離島 431 / 奄美 35 / 離島半島 32 / 空欄)
ISLAND_VALUES = {"離島", "奄美", "離島半島"}
PENINSULA_VALUES = {"半島", "離島半島"}
KNOWN_ISLAND_PENINSULA = ISLAND_VALUES | PENINSULA_VALUES

ERA_BASE = {"S": 1925, "H": 1988, "R": 2018}
DATE_RE = re.compile(r"^([SHR])(\d{1,2})\.(\d{1,2})\.(\d{1,2})$")


class FeatureError(RuntimeError):
    pass


def _flag(value: str | None, mark: str) -> int:
    if value is None:
        return 0
    if value not in {WHITE_CIRCLE, BULLSEYE}:
        raise FeatureError(f"記号欄に想定外の値 {value!r}(G-18 の畳み込みが効いていない)")
    return int(value == mark)


def _designation_year(value: str | None) -> int:
    m = DATE_RE.match(value or "")
    if not m:
        raise FeatureError(f"指定年月日が読めない: {value!r}")
    return ERA_BASE[m.group(1)] + int(m.group(2))


def _c09_attributes(ports: list[dict]) -> dict[str, tuple[float, float]]:
    """港ごとの (係留施設延長, 外郭施設延長)。座標と**同じ選び方**で C09 の行を選ぶ。

    C09 には漁港番号が重複する 30 コードがあり、重複行では属性が別の港のものに
    化けている(SPEC §6.2)。座標の突合段階(geometry_method)ごとに、座標を付けたのと
    同じ行から属性を取る。区域線重心(boundary_centroid)の港には点の行が無いので付けない。
    """
    reader = shapefile.Reader(str(C09_POINT), encoding="cp932")
    by_code: dict[str, list[dict]] = collections.defaultdict(list)
    by_pref_name: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for rec in reader.records():
        row = {
            "code": rec[0],
            "name": rec[1],
            "pref": str(rec[2])[:2],
            "outer": float(rec[8]),
            "moor": float(rec[9]),
        }
        by_code[row["code"]].append(row)
        by_pref_name[(row["pref"], row["name"])].append(row)
    reader.close()

    out: dict[str, tuple[float, float]] = {}
    for port in ports:
        method = port["geometry_method"]
        hit = None
        if method in ("code_name_pref", "code_pref"):
            same_pref = [r for r in by_code[port["port_no"]] if r["pref"] == port["pref_code"]]
            exact = [r for r in same_pref if r["name"] == port["name_ja"]]
            if len(exact) == 1:
                hit = exact[0]
            elif len(same_pref) == 1:
                hit = same_pref[0]
        elif method == "name_pref":
            cands = by_pref_name[(port["pref_code"], port["name_ja"])]
            if len(cands) == 1:
                hit = cands[0]
        if hit is None:
            if method in ("code_name_pref", "code_pref", "name_pref"):
                raise FeatureError(
                    f"{port['port_no']}: 座標は {method} で付いたのに属性の行を選べない"
                )
            continue
        if hit["moor"] < 0 or hit["outer"] < 0:
            raise FeatureError(f"{port['port_no']}: 施設延長が負 {hit}")
        if hit["moor"] == 0 or hit["outer"] == 0:
            continue  # 0 は欠測の符号(G-23)。値として入れない
        if hit["moor"] < MIN_POSITIVE_LENGTH_M or hit["outer"] < MIN_POSITIVE_LENGTH_M:
            raise FeatureError(f"{port['port_no']}: 0 と最小の正の値のあいだの値 {hit}(欠測の符号の仮定が崩れた)")
        out[port["port_no"]] = (hit["moor"], hit["outer"])
    return out


def build_feature_table() -> list[dict]:
    """学習表。行は施設延長を持つ港だけ(G-08)。列は FEATURES_FULL と port_no・port_class。"""
    ports = json.loads((CANON / "ports.json").read_text(encoding="utf-8"))
    attrs = _c09_attributes(ports)

    table: list[dict] = []
    for port in ports:
        if port["port_no"] not in attrs:
            continue
        island = port["island_peninsula"]
        if island is not None and island not in KNOWN_ISLAND_PENINSULA:
            raise FeatureError(f"{port['port_no']}: 未知の離島・半島区分 {island!r}")
        subdistrict = port["subdistrict"]
        if subdistrict is not None and not subdistrict.isdigit():
            raise FeatureError(f"{port['port_no']}: 分区数が数でない {subdistrict!r}")
        if port["port_class"] not in CLASSES:
            raise FeatureError(f"{port['port_no']}: 未知の種別 {port['port_class']!r}")

        moor, outer = attrs[port["port_no"]]
        row = {
            "port_no": port["port_no"],
            "port_class": port["port_class"],
            "log_mooring_m": math.log1p(moor),
            "log_outer_m": math.log1p(outer),
            "is_island": int(island in ISLAND_VALUES),
            "is_peninsula": int(island in PENINSULA_VALUES),
            "is_border_island": int(port["inhabited_border_island"] is not None),
            "port_regulation_circle": _flag(port["port_regulation_law"], WHITE_CIRCLE),
            "port_regulation_double": _flag(port["port_regulation_law"], BULLSEYE),
            "visitor_berth": _flag(port["visitor_berth"], WHITE_CIRCLE),
            "subdistrict_count": int(subdistrict) if subdistrict else 0,
            "coast_conservation_circle": _flag(port["coast_conservation"], WHITE_CIRCLE),
            "coast_conservation_double": _flag(port["coast_conservation"], BULLSEYE),
            "designation_year": _designation_year(port["designation_date"]),
        }
        leaked = set(row) & set(FORBIDDEN_FEATURES) - {"port_no"}
        if leaked:
            raise FeatureError(f"禁止特徴が学習表に入った: {sorted(leaked)}")
        table.append(row)

    if not table:
        raise FeatureError("学習表が空")
    return table
