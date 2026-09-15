"""AI「公式の種別は、施設の規模で読めるのか」の検査(loop_004)。

ゲートと予想は実装より先に SPEC §4・§7.3 へ事前登録した(HC-064)。
ここはその宣言を守らせる側であり、**報告に書かれた判定を報告の数から再計算して**確かめる。
報告が自分の判定を自己申告するだけなら、判定の式が壊れても緑のままになる。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "data" / "canonical"

sys.path.insert(0, str(ROOT / "data-pipeline"))

pytestmark = pytest.mark.validation

WHITE_CIRCLE = "○"  # ○
BULLSEYE = "◎"  # ◎
MARK_FIELDS = ("coast_conservation", "port_regulation_law", "visitor_berth")
CLASSES = {"1", "2", "3", "special_3", "4"}


@pytest.fixture(scope="module")
def ports() -> list[dict]:
    return json.loads((CANON / "ports.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def report() -> dict:
    path = CANON / "ai_class_report.json"
    if not path.exists():
        # skip にしない —— 報告が無いまま緑になると、ゲートを誰も守っていないのに守られて見える
        pytest.fail("ai_class_report.json が無い(python data-pipeline/ml/train_class.py)")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- G-18


def test_t036_mark_fields_use_only_canonical_symbols(ports):
    """T-036 / G-18: 記号欄は ○ と ◎ だけ。

    期待値の出所: 実測(2026-09-14)。取込前の段階で記号欄に現れた字は
    U+25CB 1,936 / U+25CE 748 / U+3007 3 の三種で、U+3007 は水産庁 PDF 側の揺れ。
    """
    bad = [
        (p["port_no"], field, [f"U+{ord(ch):04X}" for ch in p[field]])
        for p in ports
        for field in MARK_FIELDS
        if p[field] is not None and p[field] not in {WHITE_CIRCLE, BULLSEYE}
    ]
    assert bad == []


def test_t036_positive_control_fold_mark():
    """T-036 **陽性対照**: 畳む関数が、畳むべきものを畳み、畳んではならないものを残す。"""
    from normalize.parse_jfa_ports import fold_mark  # noqa: PLC0415

    assert fold_mark("〇") == WHITE_CIRCLE  # 漢数字のゼロ → ○
    assert fold_mark(WHITE_CIRCLE) == WHITE_CIRCLE
    assert fold_mark(BULLSEYE) == BULLSEYE  # ◎ は別の意味なので畳まない
    assert fold_mark("") == ""
    with pytest.raises(ValueError):
        fold_mark("X")  # 未知の記号を黙って通さない(HC-075)


# ---------------------------------------------------------------- G-17 / G-08


def test_t037_forbidden_features_are_not_used():
    """T-037 / G-17: 種別の帰結と、地域を覚える値を特徴に入れない。"""
    from ml.features import FEATURES_FULL, FEATURES_SCALE, FORBIDDEN_FEATURES  # noqa: PLC0415

    assert FORBIDDEN_FEATURES, "禁止リストが空では、この検査は何も言っていない"
    assert {"administrator_type", "lat", "lon", "pref_code", "prefecture"} <= set(FORBIDDEN_FEATURES)
    assert not (set(FEATURES_FULL) | set(FEATURES_SCALE)) & set(FORBIDDEN_FEATURES)
    assert set(FEATURES_SCALE) < set(FEATURES_FULL)


def test_t037_ports_without_infrastructure_are_excluded_not_zero_filled(ports):
    """T-037 / G-08: 施設延長が無い港は学習表に入れない(0 で埋めない)。"""
    from _ci_skips import require_c09  # noqa: PLC0415
    from ml.features import build_feature_table  # noqa: PLC0415

    require_c09()  # 生データが無ければ理由つきで skip(SPEC G-30)
    table = build_feature_table()
    in_table = {row["port_no"] for row in table}
    without = {
        p["port_no"] for p in ports if p["geometry_method"] in (None, "boundary_centroid")
    }
    assert without, "施設延長を持たない港が 0 件では、対照にならない"
    assert in_table.isdisjoint(without)
    assert len(table) > 2000


# ---------------------------------------------------------------- G-23 / G-24(loop_006)

HACHINOHE = "1230010"  # 八戸。特定第3種で、C09 の係留・外郭施設延長がどちらも 0
META_FIXTURE = ROOT / "tests" / "fixtures" / "c09_meta_note.txt"


def test_t050_zero_lengths_are_missing_not_values(ports):
    """T-050 / G-23: C09 の施設延長 0 は欠測の符号。学習表に 0 を値として入れない。

    期待値の出所: 実測(scripts/probe_c09_zeros.py、2026-09-15)。正の値は最小 3 m の整数で 0 と連続せず、
    0 は青森 46.2%・岩手 37.2% に固まる。0 のどちらかを持つ港 164 を外すと 2,533 港。
    **陽性対照(外部の事実)**: 八戸は特定第3種(総括表の脚注に列挙)で、係留施設が 0 m ではありえない。
    """
    from _ci_skips import require_c09  # noqa: PLC0415
    from ml.features import build_feature_table  # noqa: PLC0415

    require_c09()  # 生データが無ければ理由つきで skip(SPEC G-30)
    table = build_feature_table()
    by_no = {p["port_no"]: p for p in ports}
    assert by_no[HACHINOHE]["port_class"] == "special_3", "対照の前提(八戸は特定第3種)が崩れた"
    assert HACHINOHE not in {row["port_no"] for row in table}
    zero_rows = [row["port_no"] for row in table if row["log_mooring_m"] == 0 or row["log_outer_m"] == 0]
    assert zero_rows == []
    assert len(table) == 2533


def test_t051_report_carries_the_metadata_caveat(report):
    """T-051 / G-24: 施設延長は交付税の算定上の値で、実際の施設延長ではない —— と報告が述べる。

    照合相手は C09 のメタデータから機械で抜いた一文(scripts/extract_c09_meta_note.py)。
    報告の但し書きは手で書くので、写し間違い・言い換えはここで落ちる。
    """
    note = META_FIXTURE.read_text(encoding="utf-8").strip()
    assert "普通交付税算定基準" in note and "実際の施設延長数値とは異なる" in note
    assert report["infrastructure_caveat"] == note
    assert "規模" not in report["question"], "問いが「規模」のまま(交付税の算定上の値を規模と呼んでいる)"


# ---------------------------------------------------------------- G-10 / G-16 / G-11


REQUIRED_MODELS = {
    "majority",
    "logistic_scale",
    "logistic_full",
    "hist_gradient_boosting_full",
    "mlp_full",
    "logistic_admin_only",  # E5 の陽性対照(出荷しない)
}


def test_t038_report_compares_against_baselines(report):
    """T-038 / G-10: 同じ交差検証で全モデルを比べ、出所と年次を併記する。"""
    names = {m["name"] for m in report["models"]}
    assert REQUIRED_MODELS <= names
    for model in report["models"]:
        assert 0.0 <= model["macro_f1_mean"] <= 1.0, model["name"]
        assert model["macro_f1_se"] >= 0.0, model["name"]
        assert set(model["per_class_recall"]) == CLASSES, model["name"]
    assert report["cv"]["folds"] == 5
    assert report["cv"]["repeats"] >= 5
    assert report["data_vintage"]["infrastructure"]
    assert report["data_vintage"]["master"]


def test_t039_gate_g16_recomputed_from_report(report):
    """T-039 / G-16: 閾値は事前登録の 0.20。判定を報告の数から再計算して一致させる。"""
    by_name = {m["name"]: m for m in report["models"]}
    margin = by_name["logistic_scale"]["macro_f1_mean"] - by_name["majority"]["macro_f1_mean"]
    gate = report["gates"]["G-16"]
    assert gate["threshold"] == 0.20
    assert gate["margin"] == pytest.approx(margin, abs=1e-12)
    assert gate["passed"] is (margin >= 0.20)


def test_t039_gate_g11_mlp_shipped_only_if_it_wins(report):
    """T-039 / G-11: MLP は最良の非 NN モデルを 1 標準誤差を超えて上回ったときだけ出す。"""
    candidates = [
        m
        for m in report["models"]
        if m["name"] not in {"mlp_full", "majority", "logistic_admin_only"}
    ]
    best = max(candidates, key=lambda m: m["macro_f1_mean"])
    mlp = next(m for m in report["models"] if m["name"] == "mlp_full")
    wins = mlp["macro_f1_mean"] > best["macro_f1_mean"] + best["macro_f1_se"]
    assert report["gates"]["G-11"]["mlp_shipped"] is wins
    assert report["shipped_model"] == ("mlp_full" if wins else best["name"])
    assert report["shipped_model"] != "logistic_admin_only"  # 陽性対照を出荷しない


def test_t040_expectations_all_present(report):
    """T-040: 事前登録した予想 E1〜E5 が揃い、それぞれに観測と成否が付く。"""
    assert set(report["expectations"]) == {"E1", "E2", "E3", "E4", "E5"}
    for key, exp in report["expectations"].items():
        assert exp["declared"], key
        assert exp["observed"], key
        assert isinstance(exp["held"], bool), key


def test_t040_majority_baseline_matches_closed_form(report):
    """T-040 **非循環**: 多数派ベースラインの macro-F1 を、学習器を通さず閉じた式で出す。

    常に最多種別(第1種)を答える分類器では、第1種の F1 = 2p/(1+p)(p は第1種の割合)、
    他の 4 種別は 0 なので、macro-F1 = 2p/(1+p)/5。層化分割なので各分割の p は全体の p に
    ほぼ等しく、許容幅は分割ごとの端数ぶん(0.005)とする。
    """
    from _ci_skips import require_c09  # noqa: PLC0415
    from ml.features import build_feature_table  # noqa: PLC0415

    require_c09()  # 生データが無ければ理由つきで skip(SPEC G-30)
    table = build_feature_table()
    p = sum(1 for row in table if row["port_class"] == "1") / len(table)
    # 前提の検算: 第1種が本当に最多であること
    counts = {c: sum(1 for row in table if row["port_class"] == c) for c in CLASSES}
    assert max(counts, key=counts.get) == "1"

    closed_form = 2 * p / (1 + p) / 5
    majority = next(m for m in report["models"] if m["name"] == "majority")
    assert majority["macro_f1_mean"] == pytest.approx(closed_form, abs=0.005)
