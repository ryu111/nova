"""閘紅的時候，**印出來的東西要看得出為什麼紅**。

## 這一格擋什麼

`#182` 讓「落成收件票」那條路的證據砍尾巴不砍開頭。但那是**兩條路裡的一條**：
另一條是 `_印結果` 印給人（與 CI 日誌）看的，它只印證據的**前 20 行**。

pytest 的輸出前 20 行是 `bringing up nodes` 與進度點——
**FAILURES 段永遠印不出來**。

實測 2026-08-31：PR #184 的 CI 紅了，日誌裡只看得到進度點停在 73%，
一個失敗的測試名都沒有；本地跑閘也一樣（整份輸出 3923 字元，全是進度點）。
於是「CI 為什麼紅」查不出來，只能重跑碰運氣。

## 為什麼不是印全部

`_截斷證據` 已經把證據壓在 20000 字元（約 250 行）以內。全部印出來在終端機上
會洗掉前面幾條規則的結果，而閘紅時最需要看的是「哪一條紅」加「為什麼」。

所以留頭也留尾：**頭幾行是規則自己的開場**（哪個工具、跑了什麼），
**尾巴是失敗細節與摘要**，中間那一大段進度點才是可以丟的。
"""

import re

import pytest

from nova.契約.檢查結果 import 檢查結果
from nova.載體.命令列 import _印結果

_假進度 = "\n".join(f"{'.' * 72} [{i:3}%]" for i in range(1, 61))
_假證據 = (
    "bringing up nodes...\nbringing up nodes...\n\n"
    + _假進度
    + "\n=================================== FAILURES ===================================\n"
    + "____________________ test_某某 ____________________\n"
    + "E   AssertionError: assert 41 == 42\n"
    + "=========================== short test summary info ============================\n"
    + "FAILED tests/單元/test_某某.py::test_某某 - AssertionError: assert 41 == 42\n"
    + "1 failed, 1679 passed in 324.38s\n"
)


def _印一次(證據: str, capsys: pytest.CaptureFixture[str]) -> str:
    """把 `_印結果` 的輸出抓回來。

    **直接呼叫，不走 subprocess**：走子程序的話 coverage 追不到那幾行，
    變異閘會判 WRONG_TEST（那是這個 repo 記過的坑，這裡是第二次踩）。
    """
    _印結果([檢查結果(代碼="x", 名稱="n", 通過=False, 負責層="載體", 證據=證據)])
    抓到 = capsys.readouterr()
    return 抓到.out + 抓到.err


def test_印得出FAILURES段與assert的實際值(capsys: pytest.CaptureFixture[str]) -> None:
    """**這一支是這個檔存在的理由。**

    只印前 20 行的話，這裡每一條斷言都會紅——而那正是 2026-08-31 的實況。
    """
    印出來 = _印一次(_假證據, capsys)
    assert "FAILURES" in 印出來, f"印不出 FAILURES 段：\n{印出來}"
    assert "assert 41 == 42" in 印出來, f"印不出 assert 的實際值：\n{印出來}"
    assert "1 failed" in 印出來, f"印不出摘要：\n{印出來}"


def test_開頭那幾行也要留(capsys: pytest.CaptureFixture[str]) -> None:
    """規則自己的開場（哪個工具、跑了什麼）在最前面，砍掉就不知道是誰紅的。"""
    assert "bringing up nodes" in _印一次(_假證據, capsys)


def test_中間省略要明講省了幾行(capsys: pytest.CaptureFixture[str]) -> None:
    """**靜默省略等於騙人**：看起來像完整輸出，其實中間缺了一段。"""
    印出來 = _印一次(_假證據, capsys)
    assert re.search(r"省略[^\n]*\d+", 印出來), f"要說出省了幾行：\n{印出來}"


def test_短證據一個字都不省(capsys: pytest.CaptureFixture[str]) -> None:
    """行數在上限內就原樣印完。省略只該發生在真的太長的時候。"""
    短 = "第一行\n第二行\n第三行"
    印出來 = _印一次(短, capsys)
    assert "第一行" in 印出來 and "第三行" in 印出來
    assert "省略" not in 印出來, f"短證據不該有省略：\n{印出來}"


@pytest.mark.parametrize("行數", [1, 20, 45])
def test_各種長度都不准把最後一行吃掉(行數: int, capsys: pytest.CaptureFixture[str]) -> None:
    """最後一行常常是摘要（`N failed in ...`），吃掉它就不知道紅了幾支。"""
    證據 = "\n".join(f"第{i}行" for i in range(1, 行數 + 1))
    assert f"第{行數}行" in _印一次(證據, capsys)
