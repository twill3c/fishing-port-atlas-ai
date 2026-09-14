"""L0 実測用プローブ(loop_006 / F-08): 類似漁港とクラスタが成り立つ土台があるかを測る。

製品のコードではない。判定の規則を SPEC に書く前に、次を数える(HC-259 の縮退を先に見る)。

1. 学習表の縮退: 特徴がまったく同じ行・標準化後の最近傍距離 0・上位 10 の境界の同点
2. 標準化した希少な二値特徴が距離を支配していないか(列ごとの z の最大・最近傍距離への寄与)
3. 類似漁港の外部の手がかり: 特徴に入れていない**公式の種別**が近傍で一致する率。
   対照は (a) 無作為に選んだ港 (b) 規模 2 特徴だけの近傍
4. クラスタ: k=2..10 の silhouette、列ごとに並べ替えた帰無、乱数替え・80% 部分標本の ARI、群の大きさ

使い方: python scripts/probe_similar.py > 出力ファイル
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data-pipeline"))

from ml.features import CLASSES, FEATURES_FULL, FEATURES_SCALE, build_feature_table  # noqa: E402

K_NEIGHBORS = 10
SEED = 20260915


def standardize(x: np.ndarray) -> np.ndarray:
    sd = x.std(axis=0)
    if np.any(sd == 0):
        raise SystemExit(f"分散 0 の列がある: {np.flatnonzero(sd == 0)}")
    return (x - x.mean(axis=0)) / sd


def pairwise(z: np.ndarray) -> np.ndarray:
    sq = (z * z).sum(axis=1)
    d2 = sq[:, None] + sq[None, :] - 2 * z @ z.T
    np.maximum(d2, 0, out=d2)
    return np.sqrt(d2)


def neighbors(d: np.ndarray, k: int) -> np.ndarray:
    """自分を除く距離の昇順、同距離は行番号の昇順(np.lexsort で決定的に)。"""
    n = len(d)
    out = np.empty((n, k), dtype=int)
    idx = np.arange(n)
    for i in range(n):
        di = d[i].copy()
        di[i] = np.inf
        order = np.lexsort((idx, di))
        out[i] = order[:k]
    return out


def class_agreement(nb: np.ndarray, labels: np.ndarray) -> dict[str, float]:
    per_class = {}
    for c in CLASSES:
        rows = np.flatnonzero(labels == c)
        per_class[c] = float((labels[nb[rows]] == c).mean())
    per_class["macro"] = float(np.mean([per_class[c] for c in CLASSES]))
    return per_class


def random_agreement(labels: np.ndarray) -> dict[str, float]:
    """無作為に別の港を選んだときの一致率の期待値 (n_c - 1)/(n - 1)。閉形式(学習器を通さない)。"""
    n = len(labels)
    counts = collections.Counter(labels.tolist())
    out = {c: (counts[c] - 1) / (n - 1) for c in CLASSES}
    out["macro"] = float(np.mean([out[c] for c in CLASSES]))
    return out


def main() -> None:
    table = build_feature_table()
    labels = np.array([r["port_class"] for r in table])
    x_full = np.array([[r[f] for f in FEATURES_FULL] for r in table], dtype=float)
    x_scale = np.array([[r[f] for f in FEATURES_SCALE] for r in table], dtype=float)
    n = len(table)
    print(f"港 {n:,} / 特徴 {len(FEATURES_FULL)}")
    print("種別の内訳:", dict(collections.Counter(labels.tolist())))

    # ---- 1. 縮退
    rows = collections.Counter(map(tuple, x_full.tolist()))
    dup_groups = {k: v for k, v in rows.items() if v > 1}
    print(f"\n[1] 特徴がまったく同じ行: {sum(dup_groups.values()):,} 行 / {len(dup_groups):,} 組"
          f"(最大の組 {max(dup_groups.values()) if dup_groups else 0} 行)")
    scale_rows = collections.Counter(map(tuple, x_scale.tolist()))
    zero_scale = [k for k in scale_rows if k == (0.0, 0.0)]
    print(f"    規模 2 特徴が同じ行: {sum(v for v in scale_rows.values() if v > 1):,} 行 / "
          f"係留・外郭とも 0 の行 {scale_rows.get((0.0, 0.0), 0):,}")
    print(f"    係留 0 の行 {int((x_scale[:, 0] == 0).sum()):,} / 外郭 0 の行 {int((x_scale[:, 1] == 0).sum()):,}")

    z = standardize(x_full)
    d = pairwise(z)
    np.fill_diagonal(d, np.inf)
    nearest = d.min(axis=1)
    print(f"    標準化後の最近傍距離 0 の港: {int((nearest < 1e-9).sum()):,}"
          f" / 最近傍距離 分位 5/50/95%: {np.percentile(nearest, [5, 50, 95]).round(3).tolist()}")
    sorted_d = np.sort(d, axis=1)
    boundary_ties = int((np.abs(sorted_d[:, K_NEIGHBORS - 1] - sorted_d[:, K_NEIGHBORS]) < 1e-9).sum())
    print(f"    上位 {K_NEIGHBORS} の境界({K_NEIGHBORS} 位と {K_NEIGHBORS + 1} 位)が同距離の港: {boundary_ties:,}")

    # ---- 2. 列ごとの支配
    print("\n[2] 標準化後の列(平均・1 の割合・z の最大・最近傍との差の二乗和に占める割合の中央値)")
    nb1 = np.argmin(d, axis=1)
    diff2 = (z - z[nb1]) ** 2
    share = diff2 / np.maximum(diff2.sum(axis=1, keepdims=True), 1e-12)
    for j, f in enumerate(FEATURES_FULL):
        col = x_full[:, j]
        binary = set(np.unique(col).tolist()) <= {0.0, 1.0}
        ones = f"{col.mean():.3f}" if binary else "  —  "
        print(f"    {f:<28} 二値={str(binary):<5} 1の割合={ones} |z|最大={np.abs(z[:, j]).max():6.2f} "
              f"最近傍差の寄与 中央値={np.median(share[:, j]):.3f} 平均={share[:, j].mean():.3f}")
    mismatch_binary = 0
    binary_cols = [j for j in range(len(FEATURES_FULL)) if set(np.unique(x_full[:, j]).tolist()) <= {0.0, 1.0}]
    mismatch_binary = int((x_full[:, binary_cols] != x_full[nb1][:, binary_cols]).any(axis=1).sum())
    print(f"    最近傍と二値特徴が 1 つでも違う港: {mismatch_binary:,}/{n:,}")

    # ---- 3. 近傍の種別一致(外部の手がかり)
    d[np.arange(n), np.arange(n)] = np.inf
    nb_full = neighbors(d, K_NEIGHBORS)
    z_scale = standardize(x_scale)
    d_scale = pairwise(z_scale)
    np.fill_diagonal(d_scale, np.inf)
    nb_scale = neighbors(d_scale, K_NEIGHBORS)
    print(f"\n[3] 上位 {K_NEIGHBORS} 近傍の種別一致率(種別は特徴に入れていない)")
    for name, agr in (("無作為(閉形式)", random_agreement(labels)),
                      ("規模 2 特徴だけ", class_agreement(nb_scale, labels)),
                      ("規模+属性 12 特徴", class_agreement(nb_full, labels))):
        print(f"    {name:<16} " + " ".join(f"{c}={agr[c]:.3f}" for c in (*CLASSES, "macro")))
    overlap = np.mean([len(set(a) & set(b)) / K_NEIGHBORS for a, b in zip(nb_full, nb_scale)])
    print(f"    規模だけの近傍と 12 特徴の近傍の重なり(上位 {K_NEIGHBORS} の平均): {overlap:.3f}")

    # ---- 4. クラスタ
    print("\n[4] k-means(標準化 12 特徴)")
    rng = np.random.default_rng(SEED)
    null = z.copy()
    for j in range(null.shape[1]):
        null[:, j] = rng.permutation(null[:, j])
    for k in range(2, 11):
        km = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit(z)
        sil = silhouette_score(z, km.labels_)
        sil_null = silhouette_score(null, KMeans(n_clusters=k, n_init=10, random_state=SEED).fit(null).labels_)
        seeds_ari = [
            adjusted_rand_score(km.labels_, KMeans(n_clusters=k, n_init=10, random_state=s).fit(z).labels_)
            for s in (1, 2, 3)
        ]
        boot_ari = []
        for b in range(5):
            sub = rng.choice(n, size=int(n * 0.8), replace=False)
            sub_labels = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit(z[sub]).labels_
            boot_ari.append(adjusted_rand_score(km.labels_[sub], sub_labels))
        sizes = sorted(collections.Counter(km.labels_.tolist()).values(), reverse=True)
        print(f"    k={k:>2} silhouette={sil:.3f} 帰無={sil_null:.3f} 乱数替え ARI 最小={min(seeds_ari):.3f} "
              f"部分標本 ARI 最小={min(boot_ari):.3f} 大きさ={sizes}")

    print("\n[4b] k=4 の群を特徴の中央値・二値の割合で言語化する")
    km = KMeans(n_clusters=4, n_init=10, random_state=SEED).fit(z)
    for c in range(4):
        m = km.labels_ == c
        desc = []
        for j, f in enumerate(FEATURES_FULL):
            col = x_full[m, j]
            if j in binary_cols:
                desc.append(f"{f}={col.mean():.2f}")
            else:
                desc.append(f"{f}~{np.median(col):.2f}")
        cls = dict(collections.Counter(labels[m].tolist()))
        print(f"    群{c} n={int(m.sum())} 種別={cls}")
        print("        " + " ".join(desc))


if __name__ == "__main__":
    main()
