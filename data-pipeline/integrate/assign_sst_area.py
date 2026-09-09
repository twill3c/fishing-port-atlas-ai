"""漁港に気象庁の沿岸海域を割り当てる —— **測って捨てた実装**(出荷しない)。

このファイルは `build` パイプラインから呼ばれない。捨てた理由が再現できるように残してある。
実行すると当時と同じ数(割当 645/2768 = 23.30%、うち偽の一致を含む)が出る。

なぜ捨てたかは末尾の「測った結果」を読むこと。


## なぜ空間結合ができないか(実測 2026-09-09)

実装仕様書 §18.2 は「漁港点を JMA 沿岸海域 polygon に spatial join する」と書いているが、
**気象庁は海域のポリゴンを配布していない**。配っているのは海域番号と海域名の対応表だけで、
地理的な範囲は各地域ページの画像(クリッカブルマップ)の中にしかない。

海域名から場所を引けるかを測ると、107 海域のうち**都道府県名を含むのは 29 だけ**だった。
残りは「留萌地方沿岸北部」「玄界灘・響灘」「トカラ列島沿岸北部」のように、
振興局名・灘や湾の名前・島名で呼ばれている。

## そこで、名前が名指ししている港にだけ割り当てる

規則は 1 つだけである:

> **海域名が、その港の都道府県名か市町村名(郡名を含む)を含んでいて、
> そういう海域がちょうど 1 つであるとき、その海域を割り当てる。**

0 個または 2 個以上に当たる港は `未割当` にする。近いから、たぶんここだろう、では割り当てない
—— 画面に出す海域名は「この港の海域はここである」という主張であり、
裏づけの無い主張を出さないためである。

割当できなかった港でも、海域の水温そのものは海域一覧から読める。

## 測った結果(2026-09-09)——だから捨てた

| 内訳 | 件数 |
|---|---:|
| ちょうど 1 海域に当たった(市町村名) | 204 |
| ちょうど 1 海域に当たった(都道府県名) | 441 |
| 2 つ以上に当たった | 721 |
| 1 つも当たらなかった | 1,402 |

割当できたのは 645/2768 = 23.30%。曖昧なものを「候補の列挙」に緩めれば 49.10% まで届くが、
**候補を目で見たら偽の一致だった**:

```
大間越(青森県 西津軽郡深浦町) -> 津軽海峡の西側 / 津軽海峡 / 津軽海峡の東側
```

深浦町は日本海に面している。郡名「西津軽郡」に「津軽」が入るせいで、
まったく別の海(津軽海峡)に当たっていた。**規則は数を増やせるが、正しさは増えない。**

出荷しないと決めたのはここである。近いから、たぶんここだろう、で海域名を出せば、
画面はテストが緑のまま嘘をつく。
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NORM = ROOT / "data" / "normalized"
CANON = ROOT / "data" / "canonical"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.prefectures import PREF_CODE  # noqa: E402

# 海域名から「場所を名指ししていない語」を取り除いて、地名部分だけにする。
# ここを緩めると別の県の港に当たるので、語は増やさずに保つ。
QUALIFIERS = [
    "沿岸部",
    "沿岸",
    "地方",
    "北西部",
    "南西部",
    "南東部",
    "北東部",
    "北部",
    "南部",
    "東部",
    "西部",
    "中部",
    "中・東部",
    "の東側",
    "の西側",
    "の南東側",
    "の東",
    "の南",
    "の北",
    "の西",
    "海峡",
    "水道",
    "群島",
    "列島",
    "諸島",
    "海域",
]

# 地名として短すぎて誤爆する語(「灘」「湾」だけの断片など)を落とす下限
MIN_TOKEN = 2


class AssignError(RuntimeError):
    pass


def place_tokens(area_name: str) -> list[str]:
    """海域名から地名らしい語を取り出す。

    「五島列島沿岸西部」→「五島」、「種子島・屋久島沿岸」→「種子島」「屋久島」。
    「日向灘南部」→「日向灘」(灘・湾は地名の一部なので残す)。
    """
    parts = re.split(r"[・、]", area_name)
    tokens: list[str] = []
    for part in parts:
        token = part
        changed = True
        while changed:
            changed = False
            for q in QUALIFIERS:
                if token.endswith(q):
                    token = token[: -len(q)]
                    changed = True
        token = token.strip()
        if len(token) >= MIN_TOKEN:
            tokens.append(token)
    return tokens


def build() -> dict:
    ports = json.loads((CANON / "ports.json").read_text(encoding="utf-8"))
    areas = json.loads((NORM / "jma_sst_annual.json").read_text(encoding="utf-8"))

    pref_stems = {p: p.rstrip("県都府") for p in PREF_CODE}
    # 「北海道」は「道」を落とすと「北海」になり地名として残らないので、そのまま使う
    pref_stems["北海道"] = "北海道"

    area_tokens = {a["area_no"]: place_tokens(a["area_name"]) for a in areas}
    area_names = {a["area_no"]: a["area_name"] for a in areas}

    assignments: dict[str, dict] = {}
    reasons: defaultdict[str, int] = defaultdict(int)

    for port in ports:
        pref = port["prefecture"]
        stem = pref_stems[pref]
        muni = port["municipality"] or ""

        by_pref = [no for no, name in area_names.items() if stem in name]
        by_muni = [
            no
            for no, tokens in area_tokens.items()
            if any(t in muni for t in tokens)
        ]

        # 市町村で名指しされた海域があれば、それを優先する(県名より細かいため)。
        candidates = by_muni or by_pref
        method = "municipality_named" if by_muni else "prefecture_named"

        if len(candidates) == 1:
            area_no = candidates[0]
            assignments[port["port_no"]] = {
                "area_no": area_no,
                "area_name": area_names[area_no],
                "method": method,
            }
            reasons[method] += 1
        elif not candidates:
            reasons["none"] += 1
        else:
            reasons[f"ambiguous_{method}"] += 1

    out = CANON / "port_sst_area_map.json"
    out.write_text(
        json.dumps(assignments, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    total = len(ports)
    assigned = len(assignments)
    print(f"割当 {assigned}/{total} ({assigned / total * 100:.2f}%) -> {out}")
    print("内訳:", dict(sorted(reasons.items())))
    return {"total": total, "assigned": assigned, "reasons": dict(reasons)}


if __name__ == "__main__":
    build()
