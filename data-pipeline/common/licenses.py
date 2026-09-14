"""データの再配布条件の台帳(SPEC G-21 / 実装仕様書 §49・§52)。

## 津波浸水想定(国土数値情報 A40、2024 年度ページ)

`page_class` はページの記載をそのまま写したもの。T-043 が、保存したページから機械で抜いた
一覧(tests/fixtures/a40_license_2024.txt)と集合として照合する —— ここを手で書き写し、
照合相手は機械で抜くので、写し間違いは照合で落ちる。

`policy` は区分から次の規則で決める(規則そのものも T-043 が見る):

- open(再配信可)→ redistribute
- conditional(条件付き)→ 条件の中身を読んで、再配布を妨げないと確かめた県だけ redistribute、
  事前の連絡が要る県は link_only(連絡を取れないので、仕様書 §10.1 どおりリンクだけにする)
- not_provided(提供不可)→ not_provided
- absent(ページに載っていない = 配布が無い)→ no_data
"""

from __future__ import annotations

A40_PAGE_URL = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A40-2024.html"
A40_ATTRIBUTION = "出典: 国土交通省「国土数値情報(津波浸水想定データ)」を加工して作成"

_OPEN = (
    "北海道 青森県 岩手県 秋田県 山形県 福島県 茨城県 東京都 神奈川県 新潟県 富山県 石川県 "
    "福井県 岐阜県 静岡県 愛知県 大阪府 兵庫県 和歌山県 鳥取県 岡山県 広島県 山口県 徳島県 "
    "愛媛県 高知県 福岡県 佐賀県 熊本県 宮崎県 鹿児島県 沖縄県"
).split()

# 条件付き 7 府県の条件を読んだ結果(2026-09-14)
_CONDITIONAL = {
    "宮城県": (
        "redistribute",
        "県と市町村共同オープンデータポータルの規約が CC BY 4.0(数値データは著作権の対象外)。"
        "出所の表示を求める(https://miyagi.dataeye.jp/pages/terms)",
    ),
    "千葉県": (
        "redistribute",
        "条件は県の解説「津波浸水想定について」を確認すること。解説の留意事項"
        "(最大クラスの津波が悪条件下で発生した場合の想定、それより大きな津波が起きないというものではない、"
        "第二波以降に最大となる場所もある)を表示に添える。再配布の制限は無い",
    ),
    "三重県": (
        "redistribute",
        "三重県オープンデータ利用規約が CC BY 4.0(https://odcs.bodik.jp/240001/tos/)",
    ),
    "京都府": ("link_only", "商用利用を希望する場合は京都府災害対策課への連絡が要る"),
    "島根県": (
        "redistribute",
        "島根県オープンデータポータルの規約が CC BY 4.0(https://shimane-opendata.jp/pages/terms)",
    ),
    "長崎県": ("link_only", "商用利用・再配信を希望する場合は、事前に長崎県への連絡が要る"),
    "大分県": (
        "redistribute",
        "大分県オープンデータ利用規約が CC BY 4.0(https://odcs.bodik.jp/440001/tos/)",
    ),
}

CONDITIONAL_REVIEWED_REDISTRIBUTE = frozenset(
    pref for pref, (policy, _reason) in _CONDITIONAL.items() if policy == "redistribute"
)

TSUNAMI_POLICY: dict[str, dict[str, str]] = {}
for _pref in _OPEN:
    TSUNAMI_POLICY[_pref] = {
        "page_class": "open",
        "policy": "redistribute",
        "reason": "A40 ページでオープンデータとして利用可(商用利用可・再配信可)",
    }
for _pref, (_policy, _reason) in _CONDITIONAL.items():
    TSUNAMI_POLICY[_pref] = {"page_class": "conditional", "policy": _policy, "reason": _reason}
TSUNAMI_POLICY["香川県"] = {
    "page_class": "not_provided",
    "policy": "not_provided",
    "reason": "A40 ページで「国土数値情報としてダウンロード提供不可」",
}
TSUNAMI_POLICY["滋賀県"] = {
    "page_class": "absent",
    "policy": "no_data",
    "reason": "A40 に配布が無い(津波防災地域づくり法の津波浸水想定の対象外)",
}


def short_name(pref: str) -> str:
    """A40 ページの配布表は「北海道」以外を都・府・県を落とした短い名で書く。"""
    return pref if pref == "北海道" else pref[:-1]
