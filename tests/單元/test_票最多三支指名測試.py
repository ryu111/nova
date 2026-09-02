"""守收件匣對人寫票的指名測試數量設上限，並保留自主票的紅證據。"""

from pathlib import Path

import pytest

from nova.載體.收件 import 丟一件, 你敲, 協定, 待處理, 時鐘, 檔案

_三支 = (
    "tests/單元/test_甲.py::test_甲",
    "tests/單元/test_乙.py::test_乙",
    "test/整合/test_丙.py::test_丙",
)
_四支 = (*_三支, "tests/驗收/test_丁.py::test_丁")

_人寫的票案例 = (
    pytest.param("\n".join(_三支), _三支, 你敲, id="你敲三支派得出去"),
    pytest.param("\n".join(_四支), _四支, 檔案, id="檔案來源四支退件"),
    pytest.param(
        "\n".join(
            (
                "tests/單元/test_甲.py::test_甲[a]",
                "tests/單元/test_甲.py::test_甲[b]",
                "tests/單元/test_甲.py::test_甲[a]",
                "tests/單元/test_甲.py::test_甲[b]",
            )
        ),
        (_三支[0],),
        你敲,
        id="參數化同支去重",
    ),
    pytest.param("\n".join(f"FAILED {支}" for 支 in _四支), (), 檔案, id="判準失敗行不算"),
    pytest.param(
        "\n".join(支.replace("::test_", "::Test") for 支 in _四支),
        (),
        檔案,
        id="class形式不算",
    ),
)


@pytest.mark.parametrize(("內容", "預期指名", "來源"), _人寫的票案例)
def test_人寫的票指名超過三支就丟不進去而且沒落檔(
    內容: str, 預期指名: tuple[str, ...], 來源: str, tmp_path: Path
) -> None:
    """守人寫的票最多指名三支測試，超限退件且不把票寫進收件匣。"""
    from nova.載體.收件 import 指名的測試

    assert 指名的測試(內容) == 預期指名

    if len(預期指名) > 3:
        from nova.載體.收件 import 票太大

        assert issubclass(票太大, ValueError)
        with pytest.raises(票太大) as 抓到:
            丟一件(內容, 來源=來源, 目錄=tmp_path)
        assert 抓到.value.那幾支 == 預期指名
        assert all(一支 in str(抓到.value) for 一支 in 預期指名)
        assert "上限" in str(抓到.value)
        assert "3" in str(抓到.value)
        assert 待處理(tmp_path) == []
    else:
        落點 = 丟一件(內容, 來源=來源, 目錄=tmp_path)
        assert 待處理(tmp_path) == [落點]


@pytest.mark.parametrize("來源", [時鐘, 協定])
def test_自主來源的票不受上限管(來源: str, tmp_path: Path) -> None:
    """守自主來源能把判準輸出的多行 FAILED 證據送進收件匣。"""
    閘紅票 = """## 紅在哪
FAILED tests/單元/test_甲.py::test_甲
FAILED tests/單元/test_乙.py::test_乙
FAILED tests/整合/test_丙.py::test_丙
FAILED tests/驗收/test_丁.py::test_丁
FAILED tests/單元/test_戊.py::test_戊

證據中提到的測試詳細：
tests/單元/test_甲.py::test_甲
tests/單元/test_乙.py::test_乙
test/整合/test_丙.py::test_丙
tests/驗收/test_丁.py::test_丁

## 輸入

src/nova/載體/收件.py

## 輸出

把停止規則接上收件路徑

## 驗收

<!--nova:驗收 true-->

## 停止

規則不清楚就停下來問人
"""

    落點 = 丟一件(閘紅票, 來源=來源, 目錄=tmp_path)

    assert 待處理(tmp_path) == [落點]
