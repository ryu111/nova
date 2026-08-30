"""負控 runner 的執行驗收與自身負控。"""

# ruff: noqa: I001

from pathlib import Path

import pytest

from . import 執行器
from .登記 import 替換一次, 登記, 變異

專案根目錄 = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("一筆", 登記, ids=[一筆.識別 for 一筆 in 登記])
def test_登記的變異會被殺(一筆: 變異) -> None:
    執行器.執行變異(一筆, 根目錄=專案根目錄)


def test_存活變異會讓runner紅() -> None:
    with pytest.raises(執行器.負控錯誤, match="SURVIVED"):
        執行器._判定結果(0, 已收集=True, 逾時=False, 預期掛住=False)


def test_點錯測試會先報WRONG_TEST() -> None:
    一筆 = 變異(
        識別="點錯",
        目標檔=Path("某檔.py"),
        操作=替換一次("甲", "乙"),
        必須覆蓋=frozenset({7}),
        該紅=("錯的測試",),
        最多秒=1.0,
    )
    with pytest.raises(執行器.負控錯誤, match="WRONG_TEST"):
        執行器._判定覆蓋(一筆, {6})


@pytest.mark.parametrize("內容", ["", "甲甲"])
def test_錨點零次與兩次都會紅(tmp_path: Path, 內容: str) -> None:
    檔案 = tmp_path / "檔案.py"
    檔案.write_text(內容, encoding="utf-8")
    with pytest.raises(AssertionError):
        替換一次("甲", "乙").套用(檔案)


def test_baseline本來紅不是killed() -> None:
    with pytest.raises(執行器.負控錯誤, match="BASELINE_RED"):
        執行器._判定基線(1, "某支測試", "失敗")


def test_pytest跑不起來不是killed() -> None:
    with pytest.raises(執行器.負控錯誤, match="RUN_ERROR"):
        執行器._判定結果(2, 已收集=True, 逾時=False, 預期掛住=False)


def test_找不到nodeid不是killed() -> None:
    with pytest.raises(執行器.負控錯誤, match="RUN_ERROR"):
        執行器._判定結果(5, 已收集=False, 逾時=False, 預期掛住=False)


def test_預期逾時算killed() -> None:
    assert 執行器._判定結果(None, 已收集=True, 逾時=True, 預期掛住=True) == "KILLED"


def test_非預期逾時讓閘紅() -> None:
    with pytest.raises(執行器.負控錯誤, match="RUN_ERROR"):
        執行器._判定結果(None, 已收集=True, 逾時=True, 預期掛住=False)


def test_變異測試前會清pycache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    事件: list[str] = []

    def 清除(_: Path) -> None:
        事件.append("清除")

    def 執行(_: Path, __: 變異) -> None:
        事件.append("執行")

    monkeypatch.setattr(執行器, "_丟掉pycache", 清除)
    monkeypatch.setattr(執行器, "_跑變異測試", 執行)
    一筆 = 變異(
        識別="清快取",
        目標檔=Path("某檔.py"),
        操作=替換一次("甲", "乙"),
        必須覆蓋=frozenset(),
        該紅=("某支測試",),
        最多秒=1.0,
    )

    執行器._執行變異副本(tmp_path, 一筆)

    assert 事件 == ["清除", "執行"]
