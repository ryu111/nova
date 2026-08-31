"""程式碼裡的診斷表，必須跟規格 §7 的九列逐字對得上。

規格（`docs/AGENT_ARCHITECTURE.md` §7「按症狀診斷表」）是外部文件，
硬規則一說它一個字都不准改——但它**會**被上游更新。
所以這支測試不抄規格，而是當場去讀它、parse 那張 markdown 表，
再跟 `nova.契約.診斷表` 的資料逐列比對。

手抄一份字串進測試就沒有保證可言：那只是把同一份抄寫變成三份，
規格哪天多一列或改了修復方向，抄寫版永遠自洽、永遠綠。
**這支測試是「表跟規格綁著」這件事唯一的機械保證。**
"""

import re
from pathlib import Path

import pytest

from nova.契約.診斷表 import 診斷表

#: 從規格 parse 出來的一列：(症狀, 負責層, 修復方向)。
#: 刻意用純 tuple 而不是 `診斷列`——比對的兩邊要是不同的東西，
#: 拿受測型別去裝規格會讓「型別自己改了」這種漂移比不出來。
規格列 = tuple[str, tuple[str, ...], str]

#: §7 的標題行。用編號不用標題文字：標題文字改字比改編號常見。
_章節標題 = re.compile(r"^## 7\.")
_下一章 = re.compile(r"^## \d")
#: markdown 表格的分隔列（`|---|---|---|`）。
_分隔列 = re.compile(r"^\|[\s:|-]+\|$")


def _規格原文(專案根: Path) -> str:
    文件 = 專案根 / "docs" / "AGENT_ARCHITECTURE.md"
    assert 文件.is_file(), "docs/AGENT_ARCHITECTURE.md 不存在，診斷表沒有可對齊的來源"
    return 文件.read_text(encoding="utf-8")


def _第七節(原文: str) -> list[str]:
    """切出 §7 那一段（含標題，到下一個 `## ` 為止）。"""
    行 = 原文.splitlines()
    起 = next((i for i, 一行 in enumerate(行) if _章節標題.match(一行)), None)
    assert 起 is not None, "規格裡找不到 `## 7.` 這一節，parse 失敗不算通過"
    止 = next((i for i in range(起 + 1, len(行)) if _下一章.match(行[i])), len(行))
    return 行[起:止]


def _切格(行: str) -> tuple[str, ...]:
    return tuple(格.strip() for 格 in 行.strip().strip("|").split("|"))


def _拆負責層(格: str) -> tuple[str, ...]:
    """`Graph + Harness` → `("Graph", "Harness")`；`(簡化)` → `("簡化",)`。"""
    return tuple(部分.strip().strip("()") for 部分 in 格.split("+"))


def _規格的列(專案根: Path) -> list[規格列]:
    """把 §7 的表 parse 成 (症狀, 負責層, 修復方向) 的列。"""
    表格行 = [行 for 行 in _第七節(_規格原文(專案根)) if 行.startswith("|")]
    assert 表格行, "§7 裡沒有 markdown 表格，parse 失敗不算通過"

    標頭 = _切格(表格行[0])
    assert 標頭 == ("症狀", "負責層", "修復方向"), f"§7 的表頭變了：{標頭}"

    列: list[規格列] = []
    for 行 in 表格行[1:]:
        if _分隔列.match(行.strip()):
            continue
        格 = _切格(行)
        assert len(格) == 3, f"§7 的表有一列不是三欄：{行}"
        列.append((格[0], _拆負責層(格[1]), 格[2]))
    return 列


@pytest.fixture
def 規格的九列(專案根: Path) -> list[規格列]:
    """規格 §7 現在寫著的那幾列。每支測試都從這裡取，不各自 parse 一次。"""
    return _規格的列(專案根)


def test_診斷表逐列對得上規格第七節(規格的九列: list[規格列]) -> None:
    """規格 §7 每一列的症狀、負責層、修復方向，程式碼裡都要有一列一字不差。

    順序也比：表是「查症狀」用的，列的次序是規格排的優先順序，不是集合。
    """
    assert len(規格的九列) >= 9, f"§7 只 parse 出 {len(規格的九列)} 列，少於規格寫的九列"

    程式碼列 = [(列.症狀, tuple(列.負責層), 列.修復方向) for 列 in 診斷表]
    assert 程式碼列 == 規格的九列, "程式碼裡的診斷表跟規格 §7 不一致"


def test_每一列的負責層都指名規格用的層名(規格的九列: list[規格列]) -> None:
    """負責層只能是 §5 的三層或「簡化」——避免有人填「模型」之類沒人擁有的層。

    合法值一樣從規格取：把 §7 那一欄出現過的字當成詞彙表，不是我在這裡發明的。
    """
    合法 = {層 for _, 負責層, _ in 規格的九列 for 層 in 負責層}
    assert {"Harness", "Loop", "Graph"} <= 合法, f"規格 §7 的負責層欄長得不對：{合法}"

    for 列 in 診斷表:
        assert 列.負責層, f"「{列.症狀}」沒有指名負責層"
        for 層 in 列.負責層:
            assert 層 in 合法, f"「{列.症狀}」的負責層 {層} 不在規格用的層名裡"


def test_症狀不重複() -> None:
    """症狀是查表的鍵，重複就代表同一個症狀有兩個互相矛盾的修復方向。"""
    症狀 = [列.症狀 for 列 in 診斷表]
    assert len(set(症狀)) == len(症狀), f"診斷表有重複的症狀：{症狀}"
