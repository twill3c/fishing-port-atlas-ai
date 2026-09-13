"""AI: 公式の種別は、施設の規模で読めるのか。SPEC §7.3 / G-10 / G-11 / G-16 / G-17。

## 手順(実測より前に固定した)

- 層化 5 分割 × 5 反復の交差検証(RepeatedStratifiedKFold、seed 固定)
- 反復ごとに分割外予測(out-of-fold)を全港ぶん集め、その反復の macro-F1 を 1 つ出す。
  平均と標準誤差は**反復 5 つの値**から取る(同じ反復の分割どうしは独立でないため)
- 種別の偏りは全モデルで同じ重みで補正する。ロジスティック回帰と勾配ブースティングは
  `class_weight="balanced"`、MLP は同じ重みを `sample_weight` で渡す
  (scikit-learn 1.9 の MLPClassifier.fit が sample_weight を受け取ることを実測で確認)
- **ハイパーパラメータは調整していない。** 下の設定は実測前に一度だけ決めた
- 予想 E1〜E5 の**判定式もここで実測前に決めた**。文面は SPEC §7.3 と同じ

## モデル

| 名前 | 特徴 | 役割 |
|---|---|---|
| majority | — | 多数派ベースライン(常に第1種) |
| logistic_scale | 規模だけ | G-16 の判定に使う |
| logistic_full | 規模+属性 | E2・E3 |
| hist_gradient_boosting_full | 規模+属性 | 非 NN の本命 |
| mlp_full | 規模+属性 | G-11: 勝ったときだけ出す |
| logistic_admin_only | 管理者区分だけ | E5 の陽性対照。**出荷しない**(G-17) |
"""

from __future__ import annotations

import collections
import json
import statistics
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, f1_score, recall_score
from sklearn.model_selection import RepeatedStratifiedKFold
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.features import (  # noqa: E402
    CLASSES,
    FEATURES_FULL,
    FEATURES_SCALE,
    FORBIDDEN_FEATURES,
    build_feature_table,
)

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "data" / "canonical"

FOLDS = 5
REPEATS = 5
SEED = 20260914
G16_THRESHOLD = 0.20  # 事前登録(SPEC §4 G-16)。実測後に動かさない

# SPEC §7.3 の文面そのまま(HC-064)
DECLARED = {
    "E1": "規模だけのロジスティック回帰は、多数派ベースラインの macro-F1 を上回る",
    "E2": "第4種の再現率は、規模だけより属性を足したほうが高い",
    "E3": "特定第3種は第3種と取り違えられやすい",
    "E4": "MLP は勾配ブースティングを 1 標準誤差を超えて上回らない",
    "E5": "管理者区分だけを特徴にすると、第3・第4種の再現率が規模だけより高い",
}

NOT_SHIPPABLE = {"majority", "logistic_admin_only"}


def _models() -> list[dict]:
    return [
        {"name": "majority", "features": FEATURES_SCALE, "weight": "none",
         "make": lambda: DummyClassifier(strategy="most_frequent")},
        {"name": "logistic_scale", "features": FEATURES_SCALE, "weight": "class_weight",
         "make": lambda: make_pipeline(
             StandardScaler(), LogisticRegression(max_iter=5000, class_weight="balanced"))},
        {"name": "logistic_full", "features": FEATURES_FULL, "weight": "class_weight",
         "make": lambda: make_pipeline(
             StandardScaler(), LogisticRegression(max_iter=5000, class_weight="balanced"))},
        {"name": "hist_gradient_boosting_full", "features": FEATURES_FULL, "weight": "class_weight",
         "make": lambda: HistGradientBoostingClassifier(
             class_weight="balanced", learning_rate=0.05, max_iter=300, random_state=SEED)},
        {"name": "mlp_full", "features": FEATURES_FULL, "weight": "sample_weight",
         "make": lambda: make_pipeline(
             StandardScaler(),
             MLPClassifier(hidden_layer_sizes=(32, 16), alpha=1e-3, max_iter=2000,
                           random_state=SEED))},
        {"name": "logistic_admin_only", "features": ("is_prefecture_managed",), "weight": "class_weight",
         "make": lambda: make_pipeline(
             StandardScaler(), LogisticRegression(max_iter=5000, class_weight="balanced"))},
    ]


def _matrix(table: list[dict], columns: tuple[str, ...]) -> np.ndarray:
    return np.array([[float(row[c]) for c in columns] for row in table], dtype=float)


def _admin_column(table: list[dict]) -> dict[str, int]:
    """E5 の陽性対照だけが使う列。学習表そのものには入れない(G-17)。"""
    ports = json.loads((CANON / "ports.json").read_text(encoding="utf-8"))
    admin = {p["port_no"]: p["administrator_type"] for p in ports}
    unknown = {admin[r["port_no"]] for r in table} - {"prefecture", "municipality"}
    if unknown:
        raise RuntimeError(f"未知の管理者区分: {unknown}")
    return {r["port_no"]: int(admin[r["port_no"]] == "prefecture") for r in table}


def run() -> dict:
    table = build_feature_table()
    admin = _admin_column(table)
    scratch = [dict(row, is_prefecture_managed=admin[row["port_no"]]) for row in table]

    y = np.array([row["port_class"] for row in table])
    counts = collections.Counter(y.tolist())
    if min(counts[c] for c in CLASSES) < FOLDS:
        raise RuntimeError(f"層化 {FOLDS} 分割に足りない種別がある: {dict(counts)}")

    splitter = RepeatedStratifiedKFold(n_splits=FOLDS, n_repeats=REPEATS, random_state=SEED)
    splits = list(splitter.split(np.zeros(len(y)), y))

    results = []
    oof_votes: dict[str, list[list[str]]] = {}
    convergence_warnings = collections.Counter()

    for spec in _models():
        X = _matrix(scratch, spec["features"])
        repeat_f1: list[float] = []
        pooled_true: list[str] = []
        pooled_pred: list[str] = []
        votes = [[] for _ in range(len(y))]

        for r in range(REPEATS):
            oof = np.empty(len(y), dtype=object)
            for train_idx, test_idx in splits[r * FOLDS:(r + 1) * FOLDS]:
                model = spec["make"]()
                fit_kwargs = {}
                if spec["weight"] == "sample_weight":
                    fit_kwargs["mlpclassifier__sample_weight"] = compute_sample_weight(
                        "balanced", y[train_idx])
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", ConvergenceWarning)
                    model.fit(X[train_idx], y[train_idx], **fit_kwargs)
                convergence_warnings[spec["name"]] += sum(
                    1 for w in caught if issubclass(w.category, ConvergenceWarning))
                oof[test_idx] = model.predict(X[test_idx])
            if any(v is None for v in oof):
                raise RuntimeError(f"{spec['name']}: 分割外予測に穴がある(分割が全港を覆っていない)")
            repeat_f1.append(float(f1_score(y, oof.astype(str), labels=list(CLASSES),
                                            average="macro", zero_division=0)))
            pooled_true.extend(y.tolist())
            pooled_pred.extend(oof.astype(str).tolist())
            for i, pred in enumerate(oof):
                votes[i].append(str(pred))

        recalls = recall_score(pooled_true, pooled_pred, labels=list(CLASSES),
                               average=None, zero_division=0)
        cm = confusion_matrix(pooled_true, pooled_pred, labels=list(CLASSES))
        results.append({
            "name": spec["name"],
            "features": list(spec["features"]),
            "class_weighting": spec["weight"],
            "macro_f1_mean": statistics.fmean(repeat_f1),
            "macro_f1_se": statistics.stdev(repeat_f1) / (REPEATS ** 0.5),
            "macro_f1_by_repeat": repeat_f1,
            "per_class_recall": {c: float(v) for c, v in zip(CLASSES, recalls)},
            "confusion_pooled": {"labels": list(CLASSES), "matrix": cm.tolist()},
        })
        oof_votes[spec["name"]] = votes

    by = {m["name"]: m for m in results}

    # ---- G-16(規模で読めるか)----
    margin = by["logistic_scale"]["macro_f1_mean"] - by["majority"]["macro_f1_mean"]
    g16 = {"threshold": G16_THRESHOLD, "margin": margin, "passed": margin >= G16_THRESHOLD}

    # ---- G-11(MLP は勝ったときだけ)----
    candidates = [m for m in results if m["name"] not in NOT_SHIPPABLE | {"mlp_full"}]
    best = max(candidates, key=lambda m: m["macro_f1_mean"])
    mlp = by["mlp_full"]
    mlp_wins = mlp["macro_f1_mean"] > best["macro_f1_mean"] + best["macro_f1_se"]
    shipped = "mlp_full" if mlp_wins else best["name"]
    g11 = {"best_non_nn": best["name"], "mlp_shipped": mlp_wins,
           "rule": "mlp.mean > best_non_nn.mean + best_non_nn.se"}

    # ---- G-11 の頑健性: MLP の初期化乱数を替えても線を越えるか ----
    # 交差検証の反復は「分割」のばらつきしか見ていない。MLP の勝ちが初期化の乱数 1 つに
    # 依存していないかを、**同じ分割で乱数だけ**替えて測る。
    # 採用の規則(G-11)は変えない —— 事前登録した規則で決め、頑健性は併記するだけにする。
    # モデルの設定は _models() から取り直す(設定を書き写すと、ここだけ古い設定で測ってしまう)。
    x_full = _matrix(scratch, FEATURES_FULL)
    line = best["macro_f1_mean"] + best["macro_f1_se"]
    mlp_spec = next(s for s in _models() if s["name"] == "mlp_full")
    seed_means: dict[str, float] = {}
    for init_seed in (1, 2, 3, 4, SEED):
        seed_f1: list[float] = []
        for r in range(REPEATS):
            oof = np.empty(len(y), dtype=object)
            for train_idx, test_idx in splits[r * FOLDS:(r + 1) * FOLDS]:
                model = mlp_spec["make"]()
                model.set_params(mlpclassifier__random_state=init_seed)
                model.fit(
                    x_full[train_idx],
                    y[train_idx],
                    mlpclassifier__sample_weight=compute_sample_weight("balanced", y[train_idx]),
                )
                oof[test_idx] = model.predict(x_full[test_idx])
            seed_f1.append(float(f1_score(y, oof.astype(str), labels=list(CLASSES),
                                          average="macro", zero_division=0)))
        seed_means[str(init_seed)] = statistics.fmean(seed_f1)
    g11["init_seed_robustness"] = {
        "seeds": list(seed_means),
        "macro_f1_mean_by_seed": seed_means,
        "line": line,
        "seeds_above_line": [s for s, v in seed_means.items() if v > line],
        "holds_for_all_seeds": all(v > line for v in seed_means.values()),
    }
    print("MLP 初期化乱数ごとの macro-F1:",
          {s: round(v, 4) for s, v in seed_means.items()}, f"/ 線 {line:.4f}")

    # ---- 予想の判定(式は実測前に固定)----
    lf_cm = np.array(by["logistic_full"]["confusion_pooled"]["matrix"])
    i_sp, i_3 = CLASSES.index("special_3"), CLASSES.index("3")
    sp_row = lf_cm[i_sp].copy()
    sp_row[i_sp] = 0
    modal_wrong = CLASSES[int(np.argmax(sp_row))] if sp_row.sum() else None
    hgb = by["hist_gradient_boosting_full"]
    rs, rf, ra = (by[n]["per_class_recall"] for n in ("logistic_scale", "logistic_full", "logistic_admin_only"))
    expectations = {
        "E1": {"held": by["logistic_scale"]["macro_f1_mean"] > by["majority"]["macro_f1_mean"],
               "observed": f"規模だけ LR {by['logistic_scale']['macro_f1_mean']:.3f} / 多数派 {by['majority']['macro_f1_mean']:.3f}"},
        "E2": {"held": rf["4"] > rs["4"],
               "observed": f"第4種の再現率 規模だけ {rs['4']:.3f} → 属性あり {rf['4']:.3f}"},
        "E3": {"held": modal_wrong == "3",
               "observed": f"特定第3種の誤りの最頻先 = {modal_wrong}(誤り {int(sp_row.sum())} 件中 第3種 {int(lf_cm[i_sp][i_3])} 件、logistic_full・5 反復の合算)"},
        "E4": {"held": not (mlp["macro_f1_mean"] > hgb["macro_f1_mean"] + hgb["macro_f1_se"]),
               "observed": f"MLP {mlp['macro_f1_mean']:.3f} / 勾配ブースティング {hgb['macro_f1_mean']:.3f} ± {hgb['macro_f1_se']:.3f}"},
        "E5": {"held": ra["3"] > rs["3"] and ra["4"] > rs["4"],
               "observed": f"再現率 管理者区分だけ 第3種 {ra['3']:.3f}・第4種 {ra['4']:.3f} / 規模だけ 第3種 {rs['3']:.3f}・第4種 {rs['4']:.3f}"},
    }
    for key in expectations:
        expectations[key] = {"declared": DECLARED[key], **expectations[key]}

    # ---- 出荷モデルの港ごとの分割外予測(5 反復の多数決)----
    port_predictions = {}
    for row, votes in zip(table, oof_votes[shipped]):
        top, n_top = collections.Counter(votes).most_common(1)[0]
        port_predictions[row["port_no"]] = {
            "official": row["port_class"],
            "predicted": top,
            "vote_share": n_top / REPEATS,
            "agrees": top == row["port_class"],
        }

    report = {
        "question": "公式の種別は、施設の規模で読めるのか",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
        "n_ports": len(table),
        "class_counts": {c: counts[c] for c in CLASSES},
        "features": {"scale": list(FEATURES_SCALE), "full": list(FEATURES_FULL),
                     "forbidden": list(FORBIDDEN_FEATURES)},
        "cv": {"folds": FOLDS, "repeats": REPEATS, "seed": SEED,
               "se_definition": "反復ごとの分割外 macro-F1(5 値)の標本標準偏差 / sqrt(5)"},
        "data_vintage": {"master": "水産庁 漁港一覧(令和8年4月1日現在)",
                         "infrastructure": "国土数値情報 漁港データ C09-06(平成18年度)"},
        "models": results,
        "convergence_warnings": dict(convergence_warnings),
        "gates": {"G-16": g16, "G-11": g11},
        "shipped_model": shipped,
        "expectations": expectations,
        "agreement_rate_shipped": sum(p["agrees"] for p in port_predictions.values()) / len(port_predictions),
    }

    CANON.mkdir(parents=True, exist_ok=True)
    (CANON / "ai_class_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (CANON / "ai_class_oof.json").write_text(
        json.dumps(port_predictions, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"港 {len(table)} / 種別 {dict(counts)}")
    for m in results:
        rec = " ".join(f"{c}:{v:.2f}" for c, v in m["per_class_recall"].items())
        print(f"  {m['name']:<28} macro-F1 {m['macro_f1_mean']:.3f} ± {m['macro_f1_se']:.3f}  再現率 {rec}")
    print(f"G-16 margin {margin:.3f}(閾値 {G16_THRESHOLD}) -> {'通過' if g16['passed'] else '不通過'}")
    print(f"G-11 最良の非 NN = {best['name']} / MLP 採用 = {mlp_wins} / 出荷 = {shipped}")
    for key, e in expectations.items():
        print(f"  {key} {'成立' if e['held'] else '不成立'}: {e['observed']}")
    print("収束警告:", dict(convergence_warnings))
    return report


if __name__ == "__main__":
    run()
