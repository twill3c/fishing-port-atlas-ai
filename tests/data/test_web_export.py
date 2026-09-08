"""配信物(public/data)と、そこに乗る規律の検査。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "public" / "data"

sys.path.insert(0, str(ROOT / "data-pipeline"))

pytestmark = pytest.mark.validation

STATUS_VOCAB = {
    "observed",
    "estimated",
    "suppressed",
    "not_available",
    "not_applicable",
    "missing_source",
}


@pytest.fixture(scope="module")
def ports_min() -> list[dict]:
    path = PUBLIC / "ports.min.json"
    if not path.exists():
        pytest.skip("配信物が未生成(python data-pipeline/export/export_web.py)")
    return json.loads(path.read_text(encoding="utf-8"))


def _detail(port_no: str) -> dict:
    return json.loads((PUBLIC / "ports" / f"{port_no}.json").read_text(encoding="utf-8"))


def test_t013_bbox_guard_positive_control():
    """T-013 **陽性対照**: 外接矩形ガードが実際に落とすことを確かめる。

    期待値の出所: 実測(2026-09-08)。石川県「中島」(2410125)の漁港区域線の重心は
    35.611N / 134.467E で、石川県の既知座標の外接矩形
    [136.32, 36.35, 137.36, 37.85] の外にある。ガードが無ければこの点が採用され、
    石川県の漁港が鳥取県沖に置かれる。
    """
    from integrate.build_port_master import within_prefecture_bbox  # noqa: PLC0415

    ishikawa = [136.32, 36.35, 137.36, 37.85]
    # 陰性(実データの正常な部分から取る): 県内の港は通る
    assert within_prefecture_bbox(ishikawa, 37.0, 136.8)
    # 陽性: 実際に踏んだ誤りは落ちる
    assert not within_prefecture_bbox(ishikawa, 35.611, 134.467)
    # 余裕の縁: 0.5 度は通し、それを超えたら落ちる
    assert within_prefecture_bbox(ishikawa, 36.35 - 0.4, 136.8)
    assert not within_prefecture_bbox(ishikawa, 36.35 - 0.6, 136.8)
    # bbox が無い県(座標つきの港が 1 つも無い)は採らない
    assert not within_prefecture_bbox(None, 35.0, 136.0)


def test_t015_no_zero_filled_fields(ports_min):
    """T-015 / G-08: 欠損を 0 で埋めていない。status 語彙だけを使う。

    全 2,768 本の詳細 JSON を走査する(標本ではない)。
    """
    files = sorted((PUBLIC / "ports").glob("*.json"))
    assert len(files) == len(ports_min), "詳細 JSON の本数が ports.min.json と合わない"

    seen_status: set[str] = set()
    for path in files:
        detail = json.loads(path.read_text(encoding="utf-8"))
        for section in ("administration", "attributes"):
            for key, mark in detail[section].items():
                assert set(mark) == {"value", "status"}, f"{path.name}:{key}"
                assert mark["status"] in STATUS_VOCAB, f"{path.name}:{key}={mark['status']}"
                seen_status.add(mark["status"])
                if mark["value"] is None:
                    assert mark["status"] != "observed", f"{path.name}:{key}"
                else:
                    # 値があるのに 0 や空文字を「観測」として置いていない
                    assert mark["value"] not in (0, "", "0"), f"{path.name}:{key}"

    # 走査が空振りしていないこと: 欠損と実測の両方が実際に現れている
    assert "observed" in seen_status
    assert seen_status & {"not_available", "not_applicable", "missing_source"}


def test_t015_missing_source_is_labelled(ports_min):
    """T-015: e-Stat 由来の欄は 0 ではなく「未取得」と言っている。"""
    detail = _detail(ports_min[0]["id"])
    assert detail["landing"]["status"] == "missing_source"
    assert detail["species"]["status"] == "missing_source"
    assert "e-Stat" in detail["landing"]["note"]


def test_t020_no_secrets_in_client_bundle():
    """T-020 / N-02: 認証情報の名前が配信物に現れない。

    陽性対照つき: 検査器が「秘密らしきもの」を実際に捕まえられることを、
    偽の文字列で確かめてから本番の木に当てる。
    """
    secret_names = ["MSIL_API_KEY", "ESTAT_APP_ID", "Ocp-Apim-Subscription-Key"]

    def scan(text: str) -> list[str]:
        return [name for name in secret_names if name in text]

    # 陽性対照: 撃つべきものを撃つ
    assert scan("const k = process.env.MSIL_API_KEY;") == ["MSIL_API_KEY"]
    # 陰性対照: 正当な文字列では撃たない
    assert scan("const ports = await fetch('/data/ports.min.json');") == []

    out = ROOT / "out"
    if not out.exists():
        pytest.skip("out/ が未生成(npm run build)")
    targets = [p for p in out.rglob("*") if p.suffix in {".js", ".html", ".json", ".css"}]
    assert targets, "走査対象が空では、この検査は何も言っていない"
    hits = []
    for path in targets:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name in scan(text):
            hits.append(f"{path.relative_to(out)}: {name}")
    assert hits == []


def test_t021_text_hygiene():
    """T-021 / G-09: 日本語本文に別字種・制御文字が混入していない。"""
    result = subprocess.run(
        [sys.executable, str(ROOT / "harness" / "text_hygiene.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_manifest_and_sources_are_consistent(ports_min):
    """配信物どうしの整合。manifest の件数と実体が一致する。"""
    manifest = json.loads((PUBLIC / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["datasets"]["ports"]["count"] == len(ports_min)
    assert set(manifest["statusVocabulary"]) == STATUS_VOCAB

    sources = json.loads((PUBLIC / "sources.json").read_text(encoding="utf-8"))
    ids = {s["id"] for s in sources}
    assert {"DS-001", "DS-002"} <= ids
    for source in sources:
        assert source["url"].startswith("https://")
        assert source["attribution"]

    stats = json.loads((PUBLIC / "stats.json").read_text(encoding="utf-8"))
    assert stats["built"]["total"] == len(ports_min)
    assert stats["built"]["with_coordinates"] == sum(1 for p in ports_min if p["y"] is not None)
