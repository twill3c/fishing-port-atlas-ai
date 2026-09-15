"""F-08 類似漁港とクラスタの検査(loop_006)。ゲートは SPEC §4 G-25〜G-28(実測前に登録)。

- 報告の判定を、報告を通さずに配信物と公式の種別から数え直して確かめる
- 無作為の期待値は閉形式 (n_c - 1)/(n - 1) で出す(学習器・近傍計算を通さない)
- 施設延長 2 特徴だけの近傍は、ここで numpy から別に計算する(本体の関数を呼ばない)
- 検査が働くことは陽性対照(無作為に入れ替えた偽の近傍)で確かめる
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "data" / "canonical"
PUBLIC = ROOT / "public" / "data" / "similar"
CLASSES = ("1", "2", "3", "special_3", "4")
K = 10

sys.path.insert(0, str(ROOT / "data-pipeline"))

pytestmark = pytest.mark.validation


@pytest.fixture(scope="module")
def report() -> dict:
    path = CANON / "similar_report.json"
    if not path.exists():
        # skip にしない —— ゲートを誰も守っていないのに守られて見える
        pytest.fail("similar_report.json が無い(python data-pipeline/ml/similar.py)")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def neighbors() -> dict[str, list[dict]]:
    path = PUBLIC / "neighbors.json"
    if not path.exists():
        pytest.fail("neighbors.json が無い(python data-pipeline/export/export_web.py)")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def classes() -> dict[str, str]:
    ports = json.loads((CANON / "ports.json").read_text(encoding="utf-8"))
    return {p["port_no"]: p["port_class"] for p in ports}


def _agreement(nb: dict[str, list[str]], classes: dict[str, str]) -> dict[str, float]:
    per = {}
    for c in CLASSES:
        rows = [no for no in nb if classes[no] == c]
        hits = sum(classes[m] == c for no in rows for m in nb[no])
        per[c] = hits / (len(rows) * K)
    per["macro"] = float(np.mean([per[c] for c in CLASSES]))
    return per


def _random_closed_form(ports: list[str], classes: dict[str, str]) -> dict[str, float]:
    n = len(ports)
    counts = collections.Counter(classes[no] for no in ports)
    per = {c: (counts[c] - 1) / (n - 1) for c in CLASSES}
    per["macro"] = float(np.mean([per[c] for c in CLASSES]))
    return per


# ---------------------------------------------------------------- G-25


def test_t052_agreement_recomputed_from_shipped_neighbors(report, neighbors, classes):
    """T-052 / G-25: 近傍の種別一致率と判定を、配信した近傍と公式の種別から数え直す。"""
    assert len(neighbors) == report["n_ports"]
    assert all(len(v) == K for v in neighbors.values())
    nb = {no: [e["port_no"] for e in v] for no, v in neighbors.items()}
    assert all(no not in v for no, v in nb.items()), "自分自身が近傍に入っている"

    shipped = _agreement(nb, classes)
    random = _random_closed_form(list(nb), classes)
    for key in (*CLASSES, "macro"):
        assert report["class_agreement"]["shipped"][key] == pytest.approx(shipped[key], abs=1e-12)
        assert report["class_agreement"]["random"][key] == pytest.approx(random[key], abs=1e-12)

    gate = report["gates"]["G-25"]
    assert gate["threshold"] == 0.10
    assert gate["margin"] == pytest.approx(shipped["macro"] - random["macro"], abs=1e-12)
    assert gate["passed"] is (gate["margin"] >= 0.10)


def test_t052_positive_control_shuffled_neighbors_fail_the_gate(neighbors, classes):
    """T-052 **陽性対照**: 近傍を無作為に入れ替えると、一致率は無作為の期待値に寄り、判定は不通過になる。"""
    ports = list(neighbors)
    rng = np.random.default_rng(20260915)
    fake = {}
    for no in ports:
        pool = rng.choice(len(ports), size=K + 1, replace=False)
        fake[no] = [ports[i] for i in pool if ports[i] != no][:K]
    margin = _agreement(fake, classes)["macro"] - _random_closed_form(ports, classes)["macro"]
    assert margin < 0.10, margin


# ---------------------------------------------------------------- G-26


def test_t053_sensitivity_to_feature_choice(report, neighbors):
    """T-053 / G-26: 施設延長 2 特徴だけの近傍を numpy で別に計算し、重なりと注意書きの有無を確かめる。"""
    from _ci_skips import require_c09  # noqa: PLC0415
    from ml.features import FEATURES_SCALE, build_feature_table  # noqa: PLC0415

    require_c09()  # 生データが無ければ理由つきで skip(SPEC G-30)
    table = build_feature_table()
    ports = [row["port_no"] for row in table]
    assert sorted(ports) == sorted(neighbors), "学習表と配信した近傍の港が違う"
    x = np.array([[row[f] for f in FEATURES_SCALE] for row in table], dtype=float)
    z = (x - x.mean(axis=0)) / x.std(axis=0)
    order_no = np.array([int(no) for no in ports])
    overlaps = []
    for i, no in enumerate(ports):
        d = np.sqrt(((z - z[i]) ** 2).sum(axis=1))
        grid = np.floor(d / 1e-9 + 0.5)  # 宣言した同点の規則(SPEC G-27): 1e-9 の格子、同じなら港番号の昇順
        grid[i] = np.inf
        idx = np.lexsort((order_no, grid))[:K]
        scale_nb = {ports[j] for j in idx}
        shipped_nb = {e["port_no"] for e in neighbors[no]}
        overlaps.append(len(scale_nb & shipped_nb) / K)
    overlap = float(np.mean(overlaps))

    gate = report["gates"]["G-26"]
    assert gate["threshold"] == 0.5
    assert gate["overlap_with_lengths_only"] == pytest.approx(overlap, abs=1e-12)
    assert gate["notice_required"] is (overlap < 0.5)

    meta = json.loads((PUBLIC / "meta.json").read_text(encoding="utf-8"))
    if gate["notice_required"]:
        assert "特徴の選び方" in meta["sensitivity_notice"]
        assert meta["features"] == report["features"]
        assert len(meta["features"]) >= 2


# ---------------------------------------------------------------- G-28


def test_t055_cluster_gate_recomputed_from_report(report):
    """T-055 / G-28: k=3〜8 の (a)〜(d) から判定を再計算し、不通過ならクラスタを配らない。"""
    gate = report["gates"]["G-28"]
    by_k = gate["by_k"]
    assert sorted(int(k) for k in by_k) == [3, 4, 5, 6, 7, 8]
    qualifying = []
    for k, m in by_k.items():
        ok = (
            m["silhouette"] - m["null_silhouette"] >= 0.05
            and m["seed_ari_min"] >= 0.80
            and m["subsample_ari_min"] >= 0.80
            and m["max_single_flag_ari"] < 0.80
        )
        assert m["qualifies"] is ok, k
        if ok:
            qualifying.append((m["silhouette"] - m["null_silhouette"], int(k)))
    expected_k = max(qualifying)[1] if qualifying else None
    assert gate["selected_k"] == expected_k
    assert gate["passed"] is (expected_k is not None)
    assert (PUBLIC / "clusters.json").exists() is gate["passed"]
    if gate["passed"]:
        # 群は言語化して出す(HC-259)。事後に測った値は判定と区別できる印を持つ
        clusters = report["clusters"]
        assert clusters["k"] == expected_k
        assert len(clusters["profiles"]) == expected_k
        assert sum(p["size"] for p in clusters["profiles"]) == report["n_ports"]
        assert clusters["best_two_flag"]["post_hoc"] is True
        assert len(clusters["best_two_flag"]["flags"]) == 2
