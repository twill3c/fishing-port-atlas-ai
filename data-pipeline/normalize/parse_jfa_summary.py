"""DS-001 の集計表 2 枚を機械可読にする。

この 2 枚は明細 PDF とは**別の文書**であり、明細から作った漁港マスタを突き合わせる
非循環オラクルになる(明細を数えた値を明細の検査に使わない)。

- sub81-256 総括表: 種別 × 管理者区分の全国計
- sub81-257 都道府県別: 都道府県 × 種別 × 管理者区分

種別の注意: 都道府県別表の「第３種」列は**特定第３種を含む** 114 港である
(総括表の第３種 101 + 特定第３種 13 = 114。実測 2026-09-08)。
明細 PDF の種別欄も 1/2/3/4 の 4 値しか持たず、特定第３種は総括表の脚注に列挙された
13 港名からしか判別できない。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "jfa"
OUT = ROOT / "data" / "normalized"

CLASS_LABELS = {
    "第１種": "1",
    "第２種": "2",
    "第３種": "3",
    "特定第３種": "special_3",
    "第４種": "4",
}


class SummaryError(RuntimeError):
    pass


def _num(token: str) -> int:
    token = token.strip()
    if token in {"-", "－", "―", ""}:
        return 0
    return int(token.replace(",", ""))


def parse_overall() -> dict:
    """総括表 sub81-256: 種別ごとの全国計と、特定第３種 13 港の港名。"""
    path = RAW / "sub81-256.pdf"
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        text = page.extract_text() or ""
        tables = page.extract_tables()

    by_class: dict[str, int] = {}
    for table in tables:
        for row in table:
            label = re.sub(r"\s+", "", str(row[0] or ""))
            if label in CLASS_LABELS and row[1]:
                by_class[CLASS_LABELS[label]] = _num(str(row[1]))
            elif label == "合計" and row[1]:
                by_class["total"] = _num(str(row[1]))

    missing = set(CLASS_LABELS.values()) | {"total"}
    if missing - by_class.keys():
        raise SummaryError(f"総括表から取れなかった区分: {missing - by_class.keys()}")

    m = re.search(r"特定第３種漁港[：:]\s*(.+)", text)
    if not m:
        raise SummaryError("総括表に特定第３種漁港の列挙が見つからない")
    special = [s for s in re.split(r"[・、]", m.group(1).strip()) if s]
    if len(special) != by_class["special_3"]:
        raise SummaryError(
            f"特定第３種の列挙 {len(special)} 件が計 {by_class['special_3']} と合わない"
        )

    checksum = by_class["1"] + by_class["2"] + by_class["3"] + by_class["special_3"] + by_class["4"]
    if checksum != by_class["total"]:
        raise SummaryError(f"種別内訳 {checksum} が合計 {by_class['total']} と合わない")

    return {
        "source_pdf": path.name,
        "by_class": by_class,
        "special_class_3_names": special,
    }


PREF_ROW_RE = re.compile(
    r"^(?P<pref>[^\s\d]+[都道府県])\s+(?P<nums>(?:[\d,]+|[-－―])(?:\s+(?:[\d,]+|[-－―])){14})\s*$"
)
TOTAL_ROW_RE = re.compile(r"^(?P<nums>(?:[\d,]+|[-－―])(?:\s+(?:[\d,]+|[-－―])){14})\s*$")


def parse_by_prefecture() -> dict:
    """都道府県別 sub81-257: 都道府県 × 種別(1/2/3含特定/4) × 管理者(計/都道府県/市町村)。"""
    path = RAW / "sub81-257.pdf"
    with pdfplumber.open(path) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)

    rows: dict[str, dict] = {}
    total_row: list[int] | None = None
    for line in text.splitlines():
        line = line.strip()
        m = PREF_ROW_RE.match(line)
        if m:
            nums = [_num(t) for t in m.group("nums").split()]
            pref = m.group("pref")
            rows[pref] = {
                "total": nums[12],
                "by_class": {"1": nums[0], "2": nums[3], "3_incl_special": nums[6], "4": nums[9]},
                "by_administrator": {"prefecture": nums[13], "municipality": nums[14]},
            }
            continue
        m = TOTAL_ROW_RE.match(line)
        if m:
            total_row = [_num(t) for t in m.group("nums").split()]

    if total_row is None:
        raise SummaryError("都道府県別表の合計行が見つからない")
    if not rows:
        raise SummaryError("都道府県別表から都道府県行を 1 件も取れなかった")

    # 表そのものが内部整合していることを、その場で確かめる(HC-223: 源の内側も整合とは限らない)
    summed = sum(r["total"] for r in rows.values())
    if summed != total_row[12]:
        raise SummaryError(f"都道府県計の和 {summed} が表の合計 {total_row[12]} と合わない")
    for pref, r in rows.items():
        by_class_sum = sum(r["by_class"].values())
        if by_class_sum != r["total"]:
            raise SummaryError(f"{pref}: 種別内訳 {by_class_sum} が総計 {r['total']} と不一致")
        by_admin_sum = sum(r["by_administrator"].values())
        if by_admin_sum != r["total"]:
            raise SummaryError(f"{pref}: 管理者内訳 {by_admin_sum} が総計 {r['total']} と不一致")

    return {
        "source_pdf": path.name,
        "prefectures": rows,
        "total": {
            "total": total_row[12],
            "by_class": {
                "1": total_row[0],
                "2": total_row[3],
                "3_incl_special": total_row[6],
                "4": total_row[9],
            },
            "by_administrator": {
                "prefecture": total_row[13],
                "municipality": total_row[14],
            },
        },
    }


def build() -> Path:
    overall = parse_overall()
    by_pref = parse_by_prefecture()

    # 2 枚の表どうしの整合(どちらも明細を見ていない)
    if overall["by_class"]["3"] + overall["by_class"]["special_3"] != by_pref["total"]["by_class"]["3_incl_special"]:
        raise SummaryError("総括表の第３種+特定第３種が都道府県別表の第３種と合わない")
    if overall["by_class"]["total"] != by_pref["total"]["total"]:
        raise SummaryError("2 枚の集計表の総計が一致しない")

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "jfa_official_counts.json"
    out.write_text(
        json.dumps({"overall": overall, "by_prefecture": by_pref}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(
        f"総計 {overall['by_class']['total']} / 都道府県 {len(by_pref['prefectures'])} 件 -> {out}"
    )
    return out


if __name__ == "__main__":
    build()
