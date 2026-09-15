"""CI では skip の集合を宣言した一覧と照合する(SPEC G-30 / T-056、loop_007)。

手元(CI が立っていない)では何もしない。生データを取得済みの手元で一覧と照合すると、
宣言した skip がすべて「skip しなかった」になって必ず落ちるため。
"""

from __future__ import annotations

import os

from _ci_skips import EXPECTED, compare, expected_skips

_skipped: set[str] = set()


def _record(report) -> None:
    if report.skipped:
        _skipped.add(report.nodeid)


def pytest_runtest_logreport(report) -> None:
    _record(report)


def pytest_collectreport(report) -> None:
    # モジュール単位の skip(allow_module_level)は実行の報告に出ず、収集の報告にだけ出る
    _record(report)


def pytest_sessionfinish(session, exitstatus) -> None:
    if os.environ.get("CI", "").lower() != "true":
        return
    unexpected, missing = compare(_skipped, expected_skips())
    if not unexpected and not missing:
        print(f"\nskip の照合: 宣言どおり {len(_skipped)} 件({EXPECTED.name})")
        return
    print(f"\nskip の照合が {EXPECTED.name} と一致しない(SPEC G-30)")
    for nodeid in unexpected:
        print(f"  宣言に無い skip(検査が黙って消えた): {nodeid}")
    for nodeid in missing:
        print(f"  宣言したのに skip しなかった(一覧が古い): {nodeid}")
    session.exitstatus = 1
