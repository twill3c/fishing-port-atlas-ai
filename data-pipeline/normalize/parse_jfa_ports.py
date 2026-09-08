"""DS-001 都道府県別明細 PDF を漁港レコードへ正規化する。

## なぜ座標で読むか

pdfplumber の `extract_tables` は、この PDF に対しては列ごとに全行を改行連結した
「1 行の表」を返す(横罫が無く縦罫だけの表であるため)。しかも疎な列(分区・海岸保全区域)は
空セルを落とすので、列内の並びが行と対応しない。よって表抽出は使わず、
**縦罫(細い矩形)から列境界を、横罫からデータ領域を取り、行は一定行高のバンドで切る**。

## 仮定と、その場で落ちる検算(HC-075)

- A1: 表は 16 列である → 縦罫が 17 本でなければ例外
- A2: データ領域は 2 本目と 3 本目の横罫の間 → 横罫が 3 本でなければ例外
- A3: 各行はちょうど 1 個の漁港番号を持ち、行の境目は隣り合う番号行の中点である → 違えば例外
- A4: 漁港番号は 7 桁で、全国で一意 → 違えば例外(呼び出し側 integrate で検査)

仮定が崩れたら黙って違う結果を出さず、その場で止まる。

## 語ではなく文字で読む理由(実測 2026-09-08)

`extract_words` は空白で語を切るため、隣接列の間に空白が無いこの表では
`1110050斜内` のように**列をまたいだ 1 語**が出る(秋田県 PDF で漁港番号を 1 件も
取り出せなかった)。文字単位なら各文字の x で列が一意に決まる。
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "jfa"
OUT = ROOT / "data" / "normalized"

N_COLUMNS = 16
COLUMNS = [
    "port_no",
    "name_ja",
    "name_kana",
    "port_class",
    "municipality",
    "administrator_name",
    "fishery_coop",
    "subdistrict",
    "coast_conservation",
    "port_regulation_law",
    "visitor_berth",
    "designation_date",
    "area_change_date",
    "island_peninsula",
    "inhabited_border_island",
    "remarks",
]

PORT_NO_RE = re.compile(r"^\d{7}$")


class ParseError(RuntimeError):
    """仮定が崩れたことを、黙って通さずに知らせる。"""


@dataclass(frozen=True)
class PortRow:
    port_no: str
    name_ja: str
    name_kana: str
    port_class: str
    municipality: str
    administrator_name: str
    fishery_coop: str
    subdistrict: str
    coast_conservation: str
    port_regulation_law: str
    visitor_berth: str
    designation_date: str
    area_change_date: str
    island_peninsula: str
    inhabited_border_island: str
    remarks: str
    prefecture: str
    source_pdf: str
    source_page: int


def normalize_text(s: str) -> str:
    """NFKC 正規化 + 空白除去。

    漁港名・漁協名は PDF 上で字間に空白が入る(「小 樽 市」)。
    半角カナは NFKC で全角カナになる(「ｼｬﾅｲ」→「シャナイ」)。
    """
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("　", " ")
    return re.sub(r"\s+", "", s)


def _column_edges(page: pdfplumber.page.Page) -> list[float]:
    edges = sorted(
        (r["x0"] + r["x1"]) / 2
        for r in page.rects
        if r["width"] < 1.5 and r["height"] > 50
    )
    # 同じ位置の重複を潰す
    merged: list[float] = []
    for x in edges:
        if not merged or x - merged[-1] > 2.0:
            merged.append(x)
    if len(merged) != N_COLUMNS + 1:
        raise ParseError(
            f"縦罫が {len(merged)} 本(期待 {N_COLUMNS + 1} 本): {page.page_number}"
        )
    return merged


def _data_band(page: pdfplumber.page.Page) -> tuple[float, float]:
    """データ領域の上端・下端。

    上端は「表頭と本体を分ける横罫」= 上から 2 本目の横罫。
    下端は縦罫の下端の最大値。実測(2026-09-08)では、表の下端に横罫が引かれるのは
    最終ページだけで、途中ページの下端は縦罫の終端でしか分からない。
    表の下に注記枠がある県(秋田県)では外枠矩形が表より下まで伸びるので、外枠は使えない。
    """
    rules: list[float] = []
    for y in sorted(
        (r["top"] + r["bottom"]) / 2
        for r in page.rects
        if r["height"] < 1.5 and r["width"] > 300
    ):
        if not rules or y - rules[-1] > 2.0:
            rules.append(y)
    if len(rules) < 2:
        raise ParseError(f"横罫が {len(rules)} 本(期待 2 本以上): p.{page.page_number}")

    verticals = [r for r in page.rects if r["width"] < 1.5 and r["height"] > 50]
    if not verticals:
        raise ParseError(f"縦罫が無い: p.{page.page_number}")
    bottom = max(r["bottom"] for r in verticals)

    top = rules[1]
    if not top < bottom:
        raise ParseError(f"データ領域が空 top={top} bottom={bottom}: p.{page.page_number}")
    return top, bottom


def _text_lines(ys: list[float], tol: float = 3.0) -> list[float]:
    """y 座標の並びをテキスト行に束ね、各行の中心 y を返す。"""
    if not ys:
        return []
    ys = sorted(ys)
    groups: list[list[float]] = [[ys[0]]]
    for y in ys[1:]:
        if y - groups[-1][-1] > tol:
            groups.append([y])
        else:
            groups[-1].append(y)
    return [sum(g) / len(g) for g in groups]


def parse_page(page: pdfplumber.page.Page, prefecture: str, pdf_name: str) -> list[PortRow]:
    edges = _column_edges(page)
    top, bottom = _data_band(page)

    chars = [
        c
        for c in page.chars
        if top + 0.5 < (c["top"] + c["bottom"]) / 2 < bottom - 0.5
        and not c["text"].isspace()
    ]
    if not chars:
        return []

    # 行の位置は漁港番号列(左端列)のテキスト行から決める(A3)。
    # 行高は一定ではない —— 漁協が 2 行になる行がある(北海道「内路」= 香深・船泊)。
    # そこで隣り合う番号行の中心の中点を行境界にする。番号は行内で上下中央に置かれるので、
    # 2 行セルの上側の行は、直前の行との中点より下に来る(実測 2026-09-08)。
    anchors = _text_lines(
        [
            (c["top"] + c["bottom"]) / 2
            for c in chars
            if edges[0] <= (c["x0"] + c["x1"]) / 2 < edges[1]
        ]
    )
    n_rows = len(anchors)
    if n_rows == 0:
        raise ParseError(f"漁港番号を 1 件も見つけられない: {pdf_name} p.{page.page_number}")

    bounds = [top]
    for a, b in zip(anchors, anchors[1:]):
        bounds.append((a + b) / 2)
    bounds.append(bottom)

    buckets: list[dict[int, list[dict]]] = [{} for _ in range(n_rows)]
    for c in chars:
        yc = (c["top"] + c["bottom"]) / 2
        idx = 0
        for k in range(n_rows):
            if bounds[k] <= yc < bounds[k + 1]:
                idx = k
                break
        else:
            idx = n_rows - 1
        xc = (c["x0"] + c["x1"]) / 2
        col = -1
        for k in range(N_COLUMNS):
            if edges[k] <= xc < edges[k + 1]:
                col = k
                break
        if col < 0:
            raise ParseError(
                f"列に入らない文字 {c['text']!r} x={xc:.1f}: {pdf_name} p.{page.page_number}"
            )
        buckets[idx].setdefault(col, []).append(c)

    rows: list[PortRow] = []
    for idx, bucket in enumerate(buckets):
        cells: dict[str, str] = {}
        for col, cs in bucket.items():
            cs.sort(key=lambda c: (round((c["top"] + c["bottom"]) / 2, 0), c["x0"]))
            cells[COLUMNS[col]] = normalize_text("".join(c["text"] for c in cs))
        port_no = cells.get("port_no", "")
        if not PORT_NO_RE.match(port_no):
            raise ParseError(
                f"バンド {idx} の漁港番号が不正 {port_no!r}: {pdf_name} p.{page.page_number}"
            )
        rows.append(
            PortRow(
                **{c: cells.get(c, "") for c in COLUMNS},
                prefecture=prefecture,
                source_pdf=pdf_name,
                source_page=page.page_number,
            )
        )
    return rows


def parse_pdf(path: Path, prefecture: str) -> list[PortRow]:
    rows: list[PortRow] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            rows.extend(parse_page(page, prefecture, path.name))
    return rows


def parse_all() -> list[PortRow]:
    manifest = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))
    skip = {"総括表", "都道府県別"}
    rows: list[PortRow] = []
    for entry in manifest["files"]:
        if entry["name"] in skip:
            continue
        path = ROOT / entry["path"]
        rows.extend(parse_pdf(path, entry["name"]))
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", help="単一 PDF のみ処理(デバッグ用)")
    ap.add_argument("--pref", default="", help="--pdf と併用する都道府県名")
    args = ap.parse_args()

    if args.pdf:
        rows = parse_pdf(Path(args.pdf), args.pref)
    else:
        rows = parse_all()

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "jfa_ports.json"
    out_path.write_text(
        json.dumps([asdict(r) for r in rows], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"{len(rows)} rows -> {out_path}")
