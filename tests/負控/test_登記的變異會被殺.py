"""負控 runner 的執行驗收與自身負控。"""

from pathlib import Path

import pytest

from . import 執行器
from .登記 import 替換一次, 登記, 變異

專案根目錄 = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("一筆", 登記, ids=[一筆.識別 for 一筆 in 登記])
def test_登記的變異會被殺(一筆: 變異) -> None:
    執行器.執行變異(一筆, 根目錄=專案根目錄)


def test_本地腦的防護都有固定負控() -> None:
    """本地腦的每條保證都要真的交給固定負控 runner 執行。"""
    應被負控釘住 = {
        "tests/整合/test_命令列.py::Test本地腦沒有審查資格::test_本地腦不准當審查員",
        "tests/單元/test_派工門面.py::test_門面不准本地腦當審查員",
        "tests/單元/test_本地派工.py::test_本地腦只作例行最後備援",
    }
    已登記 = {測試 for 一筆 in 登記 for 測試 in 一筆.該紅}

    assert 應被負控釘住 <= 已登記, (
        f"本地腦的防護沒有都登進固定負控：{sorted(應被負控釘住 - 已登記)}"
    )


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


def test_行號由操作推導且點錯先報WRONG_TEST_正常變異是KILLED(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不填行號時，走不到錨點的測試要先被辨認；真正走到的才算 KILLED。"""
    操作 = 替換一次("思考深度: str", '思考深度: str = "high"')
    點錯的變異 = 變異(
        識別="推導位置點錯",
        目標檔=Path("src/nova/契約/派工.py"),
        操作=操作,
        必須覆蓋=frozenset(),
        該紅=("tests/負控/test_登記的變異會被殺.py::test_存活變異會讓runner紅",),
        最多秒=2.0,
    )

    with pytest.raises(執行器.負控錯誤, match="WRONG_TEST"):
        執行器.執行變異(點錯的變異, 根目錄=專案根目錄)

    正常的變異 = 變異(
        識別="推導位置正常",
        目標檔=點錯的變異.目標檔,
        操作=操作,
        必須覆蓋=frozenset(),
        該紅=("tests/單元/test_派工表.py::test_派法必須明確指定思考深度",),
        最多秒=2.0,
    )
    判決: list[str] = []
    原本判定結果 = 執行器._判定結果

    def 記錄判決(
        退出碼: int | None,
        *,
        已收集: bool,
        逾時: bool,
        預期掛住: bool,
    ) -> str:
        結果 = 原本判定結果(
            退出碼,
            已收集=已收集,
            逾時=逾時,
            預期掛住=預期掛住,
        )
        判決.append(結果)
        return 結果

    monkeypatch.setattr(執行器, "_判定結果", 記錄判決)
    執行器.執行變異(正常的變異, 根目錄=專案根目錄)

    assert 判決 == ["KILLED"]


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
