"""F-08: 類似漁港とクラスタ。SPEC §4 G-25〜G-28(実測前に登録)。

## 何を「似ている」とするか

学習表(`ml.features.build_feature_table`、施設延長 0 の港は欠測として外した 2,533 港)の
12 特徴を標準化し、ユークリッド距離の近い順に上位 10 港。種別・座標・都道府県は入れない(G-17)。

**これは一つの選び方にすぎない。** loop_006 のプローブでは、施設延長 2 特徴だけの近傍と
上位 10 の重なりが平均 0.074 だった。だから重なりを報告に載せ(G-26)、0.5 未満なら画面で断る。

## 同距離の並び(G-27)

学習表には特徴がまったく同じ行がある。距離を 1e-9 の格子に丸めた整数の昇順、同じなら港番号の昇順。
TypeScript(`lib/similar.ts`)も同じ規則で独立に計算し、全港で照合する。
丸めずに浮動小数のまま比べると、計算の順序で 1e-16 だけずれた「ほぼ同点」が二実装で入れ替わる。

## クラスタ(G-28)

k=3〜8 の k-means について (a) 列ごとに並べ替えた帰無との silhouette の差 (b) 初期化の乱数替えの ARI
(c) 80% 部分標本の ARI (d) 単一の二値特徴で切った 2 群との ARI を測る。規則を満たす k が無ければ
クラスタは出さない(割り当てを書き出さない)。
"""

from __future__ import annotations

import collections
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.features import CLASSES, FEATURES_FULL, FEATURES_SCALE, build_feature_table  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "data" / "canonical"

K = 10
SEED = 20260915
DISTANCE_GRID = 1e-9

# 事前登録(SPEC §4)。実測後に動かさない
G25_THRESHOLD = 0.10
G26_THRESHOLD = 0.5
G28_K_RANGE = range(3, 9)
G28_SILHOUETTE_MARGIN = 0.05
G28_ARI_MIN = 0.80
G28_SINGLE_FLAG_ARI_MAX = 0.80
G28_INIT_SEEDS = (1, 2, 3)
G28_SUBSAMPLES = 5
G28_SUBSAMPLE_FRACTION = 0.8

SENSITIVITY_NOTICE = (
    "特徴の選び方で似た港は大きく変わる。ここでは下の特徴を同じ重みで使った。"
    "施設延長だけで選ぶと、上位 10 港のうち平均 {overlap_pct} しか重ならない"
)


def standardize(x: np.ndarray) -> np.ndarray:
    sd = x.std(axis=0)
    if np.any(sd == 0):
        raise RuntimeError(f"分散 0 の列がある: {np.flatnonzero(sd == 0).tolist()}")
    return (x - x.mean(axis=0)) / sd


def nearest(z: np.ndarray, port_nos: list[str], k: int = K) -> list[list[tuple[str, float]]]:
    """各港の上位 k(自分を除く)。距離を 1e-9 の格子に丸めた整数の昇順、同じなら港番号の昇順。"""
    order_no = np.array([int(no) for no in port_nos])
    out = []
    for i in range(len(port_nos)):
        d = np.sqrt(((z - z[i]) ** 2).sum(axis=1))
        grid = np.floor(d / DISTANCE_GRID + 0.5)
        grid[i] = np.inf
        idx = np.lexsort((order_no, grid))[:k]
        out.append([(port_nos[j], float(d[j])) for j in idx])
    return out


def _agreement(port_nos: list[str], labels: list[str], nb: list[list[tuple[str, float]]]) -> dict[str, float]:
    label_of = dict(zip(port_nos, labels))
    per = {}
    for c in CLASSES:
        rows = [i for i, lab in enumerate(labels) if lab == c]
        hits = sum(label_of[m] == c for i in rows for m, _ in nb[i])
        per[c] = hits / (len(rows) * K)
    per["macro"] = float(np.mean([per[c] for c in CLASSES]))
    return per


def _random_closed_form(labels: list[str]) -> dict[str, float]:
    n = len(labels)
    counts = collections.Counter(labels)
    per = {c: (counts[c] - 1) / (n - 1) for c in CLASSES}
    per["macro"] = float(np.mean([per[c] for c in CLASSES]))
    return per


def _cluster_gate(z: np.ndarray, x: np.ndarray) -> dict:
    rng = np.random.default_rng(SEED)
    null = z.copy()
    for j in range(null.shape[1]):
        null[:, j] = rng.permutation(null[:, j])
    binary_cols = [j for j in range(x.shape[1]) if set(np.unique(x[:, j]).tolist()) <= {0.0, 1.0}]
    subsamples = [rng.choice(len(z), size=int(len(z) * G28_SUBSAMPLE_FRACTION), replace=False)
                  for _ in range(G28_SUBSAMPLES)]

    by_k = {}
    for k in G28_K_RANGE:
        labels = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit(z).labels_
        sil = float(silhouette_score(z, labels))
        null_sil = float(silhouette_score(null, KMeans(n_clusters=k, n_init=10, random_state=SEED).fit(null).labels_))
        seed_ari = [float(adjusted_rand_score(labels, KMeans(n_clusters=k, n_init=10, random_state=s).fit(z).labels_))
                    for s in G28_INIT_SEEDS]
        sub_ari = [float(adjusted_rand_score(labels[sub], KMeans(n_clusters=k, n_init=10, random_state=SEED).fit(z[sub]).labels_))
                   for sub in subsamples]
        flag_ari = {FEATURES_FULL[j]: float(adjusted_rand_score(labels, x[:, j].astype(int))) for j in binary_cols}
        top_flag = max(flag_ari, key=flag_ari.get)
        qualifies = (
            sil - null_sil >= G28_SILHOUETTE_MARGIN
            and min(seed_ari) >= G28_ARI_MIN
            and min(sub_ari) >= G28_ARI_MIN
            and flag_ari[top_flag] < G28_SINGLE_FLAG_ARI_MAX
        )
        by_k[str(k)] = {
            "silhouette": sil,
            "null_silhouette": null_sil,
            "seed_ari_min": min(seed_ari),
            "subsample_ari_min": min(sub_ari),
            "max_single_flag_ari": flag_ari[top_flag],
            "max_single_flag": top_flag,
            "sizes": sorted(collections.Counter(labels.tolist()).values(), reverse=True),
            "qualifies": qualifies,
        }
        print(f"  k={k} silhouette {sil:.3f} 帰無 {null_sil:.3f} 乱数 ARI 最小 {min(seed_ari):.3f} "
              f"部分標本 ARI 最小 {min(sub_ari):.3f} 単一の印 {top_flag} ARI {flag_ari[top_flag]:.3f} -> {qualifies}")

    qualifying = [(m["silhouette"] - m["null_silhouette"], int(k)) for k, m in by_k.items() if m["qualifies"]]
    selected = max(qualifying)[1] if qualifying else None
    return {
        "rule": "(a) silhouette - null >= 0.05 かつ (b) seed_ari_min >= 0.80 かつ (c) subsample_ari_min >= 0.80 "
                "かつ (d) max_single_flag_ari < 0.80。複数なら (a) の差が最大の k",
        "by_k": by_k,
        "selected_k": selected,
        "passed": selected is not None,
    }


def run() -> dict:
    table = build_feature_table()
    port_nos = [row["port_no"] for row in table]
    labels = [row["port_class"] for row in table]
    x = np.array([[row[f] for f in FEATURES_FULL] for row in table], dtype=float)
    x_scale = np.array([[row[f] for f in FEATURES_SCALE] for row in table], dtype=float)

    z = standardize(x)
    nb = nearest(z, port_nos)
    nb_scale = nearest(standardize(x_scale), port_nos)

    shipped = _agreement(port_nos, labels, nb)
    lengths_only = _agreement(port_nos, labels, nb_scale)
    random = _random_closed_form(labels)
    overlap = float(np.mean([len({m for m, _ in a} & {m for m, _ in b}) / K for a, b in zip(nb, nb_scale)]))

    margin = shipped["macro"] - random["macro"]
    g25 = {"threshold": G25_THRESHOLD, "margin": margin, "passed": margin >= G25_THRESHOLD}
    g26 = {"threshold": G26_THRESHOLD, "overlap_with_lengths_only": overlap, "notice_required": overlap < G26_THRESHOLD}
    print(f"近傍の種別一致 macro: 12 特徴 {shipped['macro']:.3f} / 施設延長だけ {lengths_only['macro']:.3f} / "
          f"無作為 {random['macro']:.3f} -> G-25 差 {margin:.3f} {'通過' if g25['passed'] else '不通過'}")
    print(f"施設延長だけの近傍との重なり {overlap:.3f} -> 注意書き {'要' if g26['notice_required'] else '不要'}")

    rows = collections.Counter(map(tuple, x.tolist()))
    print("クラスタ(G-28):")
    g28 = _cluster_gate(z, x)

    report = {
        "question": "施設延長と属性が近い漁港はどこか。種別の似かたで確かめる",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_ports": len(port_nos),
        "features": list(FEATURES_FULL),
        "k": K,
        "distance": "標準化した特徴のユークリッド距離(標準化は母標準偏差)",
        "tie_rule": "距離を 1e-9 の格子に丸めた整数の昇順、同じなら港番号の昇順",
        "identical_feature_rows": sum(v for v in rows.values() if v > 1),
        "class_agreement": {"shipped": shipped, "lengths_only": lengths_only, "random": random},
        "gates": {"G-25": g25, "G-26": g26, "G-28": g28},
        "sensitivity_notice": (
            SENSITIVITY_NOTICE.format(overlap_pct=f"{overlap * 100:.1f}%") if g26["notice_required"] else None
        ),
    }

    CANON.mkdir(parents=True, exist_ok=True)
    (CANON / "similar_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (CANON / "similar_neighbors.json").write_text(
        json.dumps({no: [{"port_no": m, "distance": d} for m, d in row] for no, row in zip(port_nos, nb)},
                   ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    (CANON / "similar_features.json").write_text(
        json.dumps({"features": list(FEATURES_FULL), "ports": port_nos, "matrix": x.tolist()},
                   ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    if g28["passed"]:
        k = g28["selected_k"]
        assignment = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit(z).labels_
        # 群を特徴で言語化する(HC-259: 統計的な対照は縮退や単一の印で切れた群も通すので、中身を読んで確かめる)
        binary = [j for j in range(x.shape[1]) if set(np.unique(x[:, j]).tolist()) <= {0.0, 1.0}]
        profiles = []
        for c in range(k):
            m = assignment == c
            profiles.append({
                "cluster": c,
                "size": int(m.sum()),
                "class_counts": {cl: int(sum(1 for lab, mm in zip(labels, m) if mm and lab == cl)) for cl in CLASSES},
                "medians": {FEATURES_FULL[j]: float(np.median(x[m, j])) for j in range(x.shape[1]) if j not in binary},
                "flag_shares": {FEATURES_FULL[j]: float(x[m, j].mean()) for j in binary},
            })
            print(f"  群{c} n={int(m.sum())} 種別={profiles[-1]['class_counts']}")
            print("      中央値", {f: round(v, 2) for f, v in profiles[-1]["medians"].items()})
            print("      印の割合", {f: round(v, 2) for f, v in profiles[-1]["flag_shares"].items()})
        # 事後の測定(ゲートではない): 規則 (d) は単一の印しか見ていなかった。言語化すると k=3 の群は
        # 海岸保全区域◎と有人国境離島の二つの印で切れていたので、二つの印の組み合わせで切った分割との ARI を測って併記する
        best_two = {"flags": None, "ari": -1.0}
        for a in range(len(binary)):
            for b in range(a + 1, len(binary)):
                combo = (x[:, binary[a]] * 2 + x[:, binary[b]]).astype(int)
                ari = float(adjusted_rand_score(assignment, combo))
                if ari > best_two["ari"]:
                    best_two = {"flags": [FEATURES_FULL[binary[a]], FEATURES_FULL[binary[b]]], "ari": ari}
        print(f"  事後: 二つの印の組み合わせで切った分割との ARI 最大 {best_two['ari']:.3f} {best_two['flags']}")
        report["clusters"] = {
            "k": k,
            "profiles": profiles,
            "best_two_flag": {**best_two, "post_hoc": True,
                              "note": "ゲート G-28 の規則 (d) は単一の印だけを見ていた。群を言語化した後に測った値で、判定には使っていない"},
        }
        (CANON / "similar_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        (CANON / "similar_clusters.json").write_text(
            json.dumps({"k": k, "assignment": dict(zip(port_nos, map(int, assignment)))}, ensure_ascii=False),
            encoding="utf-8",
        )
    else:
        (CANON / "similar_clusters.json").unlink(missing_ok=True)
    print(f"港 {len(port_nos)} / 特徴がまったく同じ行 {report['identical_feature_rows']} / "
          f"G-28 {'通過 k=' + str(g28['selected_k']) if g28['passed'] else '不通過(クラスタは出さない)'}")
    return report


if __name__ == "__main__":
    run()
