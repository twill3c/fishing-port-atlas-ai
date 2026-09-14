"""津波浸水想定(国土数値情報 A40)の検査。loop_005。

ゲートは SPEC §4 G-19〜G-22、決めごとは §7.4。

- 利用条件の区分表(コードに手で写したもの)を、ページから機械で抜いた抜粋と照合する(非循環)
- 出してはならない県の港に値が出ていないこと、点の内外を出していないことを配信物で見る
- 半径の単調性を配信物の全港で見る。検査そのものが働くことは陽性対照で確かめる
- 半径検索の関数は、答えが幾何で決まる合成の面で確かめる
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "public" / "data"
FIXTURE = ROOT / "tests" / "fixtures" / "a40_license_2024.txt"
RADII = (100, 200, 500)

sys.path.insert(0, str(ROOT / "data-pipeline"))

pytestmark = pytest.mark.validation

EXCLUDED_POLICIES = {"link_only", "not_provided", "no_data"}


# ------------------------------------------------------------------ 抜粋の読み取り


def _between(text: str, start: str, end: str) -> str:
    i = text.index(start) + len(start)
    return text[i : text.index(end, i)]


def _page_lists() -> tuple[set[str], set[str], set[str]]:
    text = FIXTURE.read_text(encoding="utf-8")
    open_block = _between(text, "＜オープンデータとして利用可（商用利用可・再配信可）＞", "＜条件付公開")
    cond_block = _between(text, "＜条件付公開", "＜国土数値情報としてダウンロード提供不可＞")
    ng_block = _between(text, "＜国土数値情報としてダウンロード提供不可＞", "＜END＞")
    opened = {p.strip() for p in open_block.split("、") if p.strip()}
    # 「■京都府 商用利用…」の県名は ■ の直後から空白までの一語。
    # 「[都道府県]で終わる最短一致」にすると「京都府」が「京都」で切れる(2026-09-14 に踏んだ)
    conditional = set(re.findall(r"■\s*([^\s■]+)", cond_block))
    not_provided = {p for p in re.split(r"[\s、]+", ng_block) if p}
    return opened, conditional, not_provided


def test_t043_page_list_reader_positive_control():
    """読み取りの規則そのものを、字面の罠を含む例で確かめる(HC-041)。"""
    sample = (
        "＜オープンデータとして利用可（商用利用可・再配信可）＞ 東京都、大阪府 "
        "＜条件付公開（原則として商用利用可・再配信可）＞ ■京都府 商用利用希望の場合は ■長崎県 事前に "
        "＜国土数値情報としてダウンロード提供不可＞ 香川県 ＜END＞"
    )
    cond = set(re.findall(r"■\s*([^\s■]+)", _between(sample, "＜条件付公開", "＜国土数値情報としてダウンロード提供不可＞")))
    assert cond == {"京都府", "長崎県"}  # 「京都」で切れない
    ng = {p for p in re.split(r"[\s、]+", _between(sample, "＜国土数値情報としてダウンロード提供不可＞", "＜END＞")) if p}
    assert ng == {"香川県"}


# ------------------------------------------------------------------ 検査関数(陽性対照で自分を確かめる)


def _excluded_violations(details: dict[str, dict]) -> list[str]:
    """出してはならない県の港に、区分の値が出ていれば返す。"""
    bad = []
    for port_no, detail in details.items():
        tsunami = detail["tsunami"]
        if tsunami["policy"] in EXCLUDED_POLICIES and tsunami.get("radii") is not None:
            bad.append(port_no)
    return bad


def _monotone_violations(details: dict[str, dict], order: list[str]) -> list[str]:
    """半径が大きいほど最大区分が浅くなっていれば返す。区域なしは最も浅い(-1)として扱う。"""
    bad = []
    for port_no, detail in details.items():
        radii = detail["tsunami"].get("radii")
        if radii is None:
            continue
        levels = []
        for entry in radii:
            rank = entry["max_rank"]
            levels.append(-1 if rank is None else order.index(rank))
        if any(b < a for a, b in zip(levels, levels[1:])):
            bad.append(port_no)
    return bad


INSIDE_KEY = re.compile(r"inside|outside|contains|in_zone|within_zone|区域内|区域外")


def _inside_keys(obj, path="") -> list[str]:
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if INSIDE_KEY.search(key):
                found.append(f"{path}.{key}")
            found.extend(_inside_keys(value, f"{path}.{key}"))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            found.extend(_inside_keys(value, f"{path}[{i}]"))
    return found


# ------------------------------------------------------------------ fixtures


@pytest.fixture(scope="module")
def meta() -> dict:
    path = PUBLIC / "hazards" / "tsunami-meta.json"
    if not path.exists():
        pytest.fail("tsunami-meta.json が無い(python data-pipeline/export/export_web.py)")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def details() -> dict[str, dict]:
    ports = json.loads((ROOT / "data" / "canonical" / "ports.json").read_text(encoding="utf-8"))
    out = {}
    for port in ports:
        detail = json.loads(
            (PUBLIC / "ports" / f"{port['port_no']}.json").read_text(encoding="utf-8")
        )
        if "tsunami" not in detail:
            pytest.fail(f"{port['port_no']} の詳細に tsunami 欄が無い")
        out[port["port_no"]] = detail
    return out


# ------------------------------------------------------------------ T-043 / G-21


def test_t043_fixture_is_not_empty():
    """抜粋が壊れていたら、以降の照合は何も言わない。"""
    opened, conditional, not_provided = _page_lists()
    assert opened and conditional and not_provided


def test_t043_policy_table_matches_the_page():
    """T-043 / G-21: 手で写した区分表が、ページから機械で抜いた一覧と集合として一致する。"""
    from common.licenses import TSUNAMI_POLICY  # noqa: PLC0415

    opened, conditional, not_provided = _page_lists()
    by_class = {
        cls: {p for p, e in TSUNAMI_POLICY.items() if e["page_class"] == cls}
        for cls in ("open", "conditional", "not_provided")
    }
    assert by_class["open"] == opened
    assert by_class["conditional"] == conditional
    assert by_class["not_provided"] == not_provided


def test_t043_every_prefecture_with_ports_has_a_policy():
    from common.licenses import CONDITIONAL_REVIEWED_REDISTRIBUTE, TSUNAMI_POLICY  # noqa: PLC0415

    ports = json.loads((ROOT / "data" / "canonical" / "ports.json").read_text(encoding="utf-8"))
    prefectures = {p["prefecture"] for p in ports}
    assert prefectures <= set(TSUNAMI_POLICY)

    # 区分から方針への規則そのもの(SPEC G-21)
    for pref, entry in TSUNAMI_POLICY.items():
        expected = {
            "open": "redistribute",
            "conditional": "redistribute" if pref in CONDITIONAL_REVIEWED_REDISTRIBUTE else "link_only",
            "not_provided": "not_provided",
            "absent": "no_data",
        }[entry["page_class"]]
        assert entry["policy"] == expected, pref
        assert entry["reason"], pref


# ------------------------------------------------------------------ T-044 / G-21 / AC-012


def test_t044_excluded_prefectures_have_no_values(details):
    assert _excluded_violations(details) == []
    excluded = [d for d in details.values() if d["tsunami"]["policy"] in EXCLUDED_POLICIES]
    assert excluded, "出さない県の港が 0 件では、この検査は何も言っていない"


def test_t044_positive_control_catches_kyoto_with_values(details):
    """陽性対照: 京都府(リンクだけ)の港に値を入れた配信物を、検査が落とす。"""
    kyoto = next(k for k, d in details.items() if d["port"]["prefecture"] == "京都府")
    forged = json.loads(json.dumps(details[kyoto]))
    assert forged["tsunami"]["policy"] == "link_only"
    forged["tsunami"]["radii"] = [{"radius_m": r, "max_rank": None, "vintage": None} for r in RADII]
    assert _excluded_violations({kyoto: forged}) == [kyoto]


# ------------------------------------------------------------------ T-045 / G-19


def test_t045_no_inside_outside_keys(details, meta):
    found = [k for d in details.values() for k in _inside_keys(d["tsunami"], "tsunami")]
    found += _inside_keys(meta, "meta")
    assert found == []
    # 陽性対照: 検査が内外の鍵を実際に見つけられる
    assert _inside_keys({"tsunami": {"inside_zone": True}})


# ------------------------------------------------------------------ T-046 / G-20


def test_t046_radii_are_fixed_and_monotone(details, meta):
    order = meta["rank_order"]
    assert order, "区分の並びが空"
    with_values = [d for d in details.values() if d["tsunami"].get("radii") is not None]
    assert len(with_values) > 1000, "値のある港が少なすぎる(計算が空振りしている疑い)"
    for detail in with_values:
        assert [e["radius_m"] for e in detail["tsunami"]["radii"]] == list(RADII)
        for entry in detail["tsunami"]["radii"]:
            assert entry["max_rank"] is None or entry["max_rank"] in order
            assert (entry["max_rank"] is None) == (entry["vintage"] is None)
    assert _monotone_violations(details, order) == []
    # 「区域なし」の枝が実際に通っていること(福井県で 100 m では 8/44 港が区域なし。実測 2026-09-14)
    assert any(d["tsunami"]["radii"][0]["max_rank"] is None for d in with_values)


def test_t046_positive_control_catches_non_monotone(meta):
    order = meta["rank_order"]
    forged = {
        "X": {
            "tsunami": {
                "radii": [
                    {"radius_m": 100, "max_rank": order[-1], "vintage": 2023},
                    {"radius_m": 200, "max_rank": order[-1], "vintage": 2023},
                    {"radius_m": 500, "max_rank": order[0], "vintage": 2023},
                ]
            }
        }
    }
    assert _monotone_violations(forged, order) == ["X"]


def test_t046_ports_without_coordinates_have_no_values(details):
    """座標の無い港に区分を付けない(0 や最寄りで埋めない)。"""
    for detail in details.values():
        if detail["port"]["lat"] is None:
            assert detail["tsunami"].get("radii") is None


# ------------------------------------------------------------------ T-047 / G-22


SAFETY_NEGATION = "安全という意味ではない"


def _safety_wording_violations(note: str) -> list[int]:
    """「安全」の出現のうち、「安全という意味ではない」と否定していないものの位置。

    切り出す長さは否定の句の長さから決める。長さを手で数えて 10 と書いたとき、
    11 字の句は決して一致せず、許すはずの否定を落とした(2026-09-14)。
    """
    return [
        m.start()
        for m in re.finditer("安全", note)
        if note[m.start() : m.start() + len(SAFETY_NEGATION)] != SAFETY_NEGATION
    ]


def test_t047_safety_wording_check_positive_control():
    assert _safety_wording_violations("区域が掛からなくても、安全という意味ではない。") == []
    assert _safety_wording_violations("この半径は安全です。") == [5]
    assert _safety_wording_violations("安全という意味ではない。ただし安全。") == [15]


def test_t047_disclaimer_and_no_safety_wording(meta, details):
    assert "避難" in meta["disclaimer"] and "公式" in meta["disclaimer"]
    assert all("安全" not in label for label in meta["rank_order"])
    notes = {detail["tsunami"].get("note") or "" for detail in details.values()}
    # 否定の枝が実際に通っていること(値のある港の注記は否定の句を含む)
    assert any(SAFETY_NEGATION in note for note in notes)
    assert {note: v for note in notes if (v := _safety_wording_violations(note))} == {}


# ------------------------------------------------------------------ 半径検索の単体テスト(合成の面)


def test_max_rank_within_uses_geometry_not_rank_order():
    """合成の面: 港から東へ 150–160 m に「深い」区分、1,000 m 先に「最も深い」区分を置く。

    期待値は幾何から決まる: 100 m では何も無い / 200 m では深い区分 / 500 m でも深い区分
    (1,000 m 先の最も深い区分は届かない)。港ごとの局所平面で測っていることも、
    高緯度(北緯 45 度)に置いて確かめる —— 緯度を無視すると東西の距離が 1.4 倍に伸びて外れる。
    """
    from shapely.geometry import box  # noqa: PLC0415

    from integrate.build_tsunami import build_index, max_rank_within  # noqa: PLC0415

    lat, lon = 45.0, 142.0
    m_per_deg_lon = 111_320 * math.cos(math.radians(lat))
    m_per_deg_lat = 110_574

    def square(east_m_from, east_m_to):
        return box(
            lon + east_m_from / m_per_deg_lon,
            lat - 5 / m_per_deg_lat,
            lon + east_m_to / m_per_deg_lon,
            lat + 5 / m_per_deg_lat,
        )

    index = build_index([(square(150, 160), 3, 2023), (square(1000, 1010), 5, 2023)])
    assert max_rank_within(index, lon, lat, 100) == (None, None)
    assert max_rank_within(index, lon, lat, 200) == (3, 2023)
    assert max_rank_within(index, lon, lat, 500) == (3, 2023)
    assert max_rank_within(index, lon, lat, 1100) == (5, 2023)


# ------------------------------------------------------------------ 区分ラベルの読み取り(実測した書式)

# 期待値の出所: 取得した A40 全 51 ファイルの属性表で実測した書式(scripts/probe_a40_labels.py、2026-09-14)。
# 書式ごとに一つずつ、実物の字面をそのまま置く(改行・空白・波ダッシュの有無も実物どおり)。
MEASURED_LABELS = [
    ("～0.3m", (0.0, 0.3), "〜0.3m"),  # 福井 2023
    ("0.3～0.5m", (0.3, 0.5), "0.3〜0.5m"),  # 福井 2023
    ("5m～", (5.0, math.inf), "5m〜"),  # 福井 2023
    ("0.01～0.3m", (0.01, 0.3), "0.01〜0.3m"),  # 大阪 2023
    ("5.0m～", (5.0, math.inf), "5m〜"),  # 大阪 2023(小数点つき)
    ("1m以上 ～ 3m未満", (1.0, 3.0), "1〜3m"),  # 北海道 2021 ほか(ここで止まった)
    ("1.0m以上 ～ 3.0m未満", (1.0, 3.0), "1〜3m"),  # 岩手 2022(同じ区間の別表記)
    ("20m以上", (20.0, math.inf), "20m〜"),
    ("0.3m未満", (0.0, 0.3), "〜0.3m"),
    ("～ 0.3m未満", (0.0, 0.3), "〜0.3m"),  # 北海道 2017(空白入り)
    ("～0.3m未満", (0.0, 0.3), "〜0.3m"),  # 北海道 2023
    ("0.01m以上 0.3m未満", (0.01, 0.3), "0.01〜0.3m"),  # 千葉 2018(波ダッシュ無し)
    ("0.01m以上～0.3m未満\n", (0.01, 0.3), "0.01〜0.3m"),  # 岡山 2016(末尾に改行)
    ("20m以上 ～ 50m未満", (20.0, 50.0), "20〜50m"),  # 福島 2021
]


@pytest.mark.parametrize(("raw", "interval", "canonical"), MEASURED_LABELS)
def test_rank_label_reads_every_measured_format(raw, interval, canonical):
    from integrate.build_tsunami import canonical_label, parse_rank_label  # noqa: PLC0415

    assert parse_rank_label(raw) == pytest.approx(interval)
    assert canonical_label(raw) == canonical


def test_rank_label_positive_control_rejects_unknown_formats():
    """読めない書式は推測せず止める(HC-075)。黙って通る道が無いことを確かめる。"""
    from integrate.build_tsunami import TsunamiError, parse_rank_label  # noqa: PLC0415

    for bad in ("深い", "3～1m", "m以上", "", "1m以上 ～ 1m未満"):
        with pytest.raises(TsunamiError):
            parse_rank_label(bad)


def test_rank_order_is_by_lower_then_upper_bound():
    """区分の並びは下限、次に上限。刻みの違う体系が混ざっても全順序になる。"""
    from integrate.build_tsunami import rank_order  # noqa: PLC0415

    order = rank_order(["2m以上 ～ 5m未満", "1m以上 ～ 3m未満", "0.3m未満", "5m～", "1～2m"])
    assert order == ["〜0.3m", "1〜2m", "1〜3m", "2〜5m", "5m〜"]


# 年度の違う刻みが同じ県に混ざると区間が重なる(青森 2021 の 1〜3m と 2016 の 1〜2m・2〜5m など)。
# 「下限、次に上限」の最大が最大浸水深の区間 [下限の最大, 上限の最大] と一致するのは、
# ある区分が別の区分に**真に含まれる**(下限が大きく上限が小さい)組が無いときだけ。
# 含まれる組があると、狭い区分を「最も深い」として出し、上限を低く見せてしまう。


def test_strictly_nested_pairs_positive_control():
    from integrate.build_tsunami import strictly_nested_pairs  # noqa: PLC0415

    assert strictly_nested_pairs(["1〜5m", "2〜3m", "5m〜"]) == [("1〜5m", "2〜3m")]
    # 境界を共有するだけ・部分的に重なるだけなら最大は正しい(青森・福島の実物の組)
    assert strictly_nested_pairs(["1〜3m", "1〜2m", "2〜5m", "3〜5m", "20m〜", "20〜50m"]) == []


def test_no_prefecture_mixes_strictly_nested_ranks():
    """全県の実物で、真に含まれる組が無いこと。

    中間結果(data/interim/)は積まないので、そこを読むと新しい clone では skip して緑のまま何も見なくなる。
    県ごとの区分の集合は、積んである canonical のメタから読む。
    """
    from integrate.build_tsunami import CANON, strictly_nested_pairs  # noqa: PLC0415

    canonical = CANON / "tsunami_ports.json"
    if not canonical.exists():
        pytest.skip("tsunami_ports.json が無い(build_tsunami.py 未実行)")
    data = json.loads(canonical.read_text(encoding="utf-8"))
    by_prefecture = data["meta"]["labels_by_prefecture"]
    # 照合相手は港の欄: 半径のどれかに区分が出ている港を持つ県。
    # 出す方針の県でも漁港が無ければ(岐阜県)構築しないので、方針の一覧とは比べない
    with_ranks = sorted({
        p["prefecture"]
        for p in data["ports"].values()
        if p["radii"] is not None and any(r["max_rank"] is not None for r in p["radii"])
    })
    assert with_ranks, "区分の出ている港が無い(計算が空振りしている疑い)"
    assert sorted(p for p, labels in by_prefecture.items() if labels) == with_ranks
    offenders = {p: pairs for p, labels in by_prefecture.items() if (pairs := strictly_nested_pairs(labels))}
    assert offenders == {}
