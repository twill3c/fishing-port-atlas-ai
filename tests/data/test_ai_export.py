"""AI の配信物の検査(loop_004)。

- 港ごとの AI 欄が、学習器の分割外予測と一致し、施設延長の無い港は「無い理由」を出す
- 公開した報告が canonical と同じ
- MLP の初期化乱数を替えた頑健性が、報告の数から再計算して一致する
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "public" / "data"
CANON = ROOT / "data" / "canonical"

pytestmark = pytest.mark.validation


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def report() -> dict:
    return _load(CANON / "ai_class_report.json")


@pytest.fixture(scope="module")
def oof() -> dict:
    return _load(CANON / "ai_class_oof.json")


@pytest.fixture(scope="module")
def ports() -> list[dict]:
    return _load(CANON / "ports.json")


def test_t041_every_port_detail_has_an_ai_section(ports, oof):
    """T-041 / G-10 / G-08: 全港の詳細に AI 欄があり、推定値か「無い理由」のどちらか。"""
    estimated = unavailable = 0
    for port in ports:
        ai = _load(PUBLIC / "ports" / f"{port['port_no']}.json")["ai"]
        if port["port_no"] in oof:
            assert ai["status"] == "estimated", port["port_no"]
            assert ai["official_class"] == port["port_class"], port["port_no"]
            assert ai["predicted_class"] == oof[port["port_no"]]["predicted"], port["port_no"]
            assert ai["agrees"] is (ai["predicted_class"] == ai["official_class"])
            assert ai["baseline_macro_f1"] < ai["model_macro_f1"]
            assert ai["data_vintage"]["infrastructure"] and ai["data_vintage"]["master"]
            estimated += 1
        else:
            assert ai["status"] == "not_available", port["port_no"]
            assert "0 で埋めない" in ai["note"], port["port_no"]
            unavailable += 1
    # 両方の枝が実際に通っていること(片方が 0 件なら、その枝は何も検査していない)
    assert estimated > 2000
    assert unavailable > 0


def test_t041_public_report_is_the_canonical_report(report):
    """T-041: 公開した報告は canonical と同一(配信の途中で数が変わっていない)。"""
    assert _load(PUBLIC / "ai" / "class-report.json") == report
    manifest = _load(PUBLIC / "manifest.json")
    assert manifest["datasets"]["aiClass"]["shippedModel"] == report["shipped_model"]


def test_t042_seed_robustness_recomputed_from_report(report):
    """T-042 / G-11: 初期化乱数の頑健性を、報告の数から再計算して一致させる。"""
    gate = report["gates"]["G-11"]
    robust = gate["init_seed_robustness"]
    means = robust["macro_f1_mean_by_seed"]
    assert len(means) >= 5

    best = next(m for m in report["models"] if m["name"] == gate["best_non_nn"])
    line = best["macro_f1_mean"] + best["macro_f1_se"]
    assert robust["line"] == pytest.approx(line, abs=1e-12)
    assert robust["seeds_above_line"] == [s for s, v in means.items() if v > line]
    assert robust["holds_for_all_seeds"] is all(v > line for v in means.values())


def test_t042_robustness_used_the_same_configuration_as_the_shipped_model(report):
    """T-042 **経路の照合**(HC-065): 出荷時の乱数での頑健性の値が、本体の mlp_full と一致する。

    頑健性の計算がモデルの設定や分割を書き写していたら、ここで食い違う。
    一致するのは、同じ設定・同じ分割・同じ重みで学習した場合だけである。
    """
    means = report["gates"]["G-11"]["init_seed_robustness"]["macro_f1_mean_by_seed"]
    mlp = next(m for m in report["models"] if m["name"] == "mlp_full")
    assert means[str(report["cv"]["seed"])] == pytest.approx(mlp["macro_f1_mean"], abs=1e-12)
