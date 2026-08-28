"""兩條禁令的機械化版本：不准繞過閘門。

CLAUDE.md 寫了「不准 --no-verify、不准 --admin」，但寫著不等於擋得住。
"""

import pytest

from nova.載體.禁令 import 檢查指令

應拒絕 = [
    "git commit --no-verify -m 訊息",
    "git commit -n -m 訊息",
    "git push --no-verify",
    "gh pr merge 3 --squash --admin",
    "gh pr merge --admin --squash 3",
]

應放行 = [
    "git commit -m 訊息",
    "git push origin main",
    "gh pr merge 3 --squash --delete-branch",
    "grep -n 閘 src/nova/載體/閘.py",
    "uv run pytest -q",
]


@pytest.mark.parametrize("命令", 應拒絕)
def test_禁令要被擋下(命令: str) -> None:
    通過, 證據 = 檢查指令(命令)
    assert 通過 is False
    assert 證據, "擋下來卻不說為什麼，等於不可行動"


@pytest.mark.parametrize("命令", 應放行)
def test_正常指令不擋(命令: str) -> None:
    通過, _ = 檢查指令(命令)
    assert 通過 is True


def test_grep_的_n_不是_git_的_n() -> None:
    """`-n` 只有在 git commit 情境才是禁令。誤判會逼人去關掉整個閘。"""
    assert 檢查指令("grep -n test tests/")[0] is True
    assert 檢查指令("git commit -n")[0] is False


def test_語法壞掉的指令算紅() -> None:
    """fail-closed：拆不開的指令不准放行。"""
    通過, 證據 = 檢查指令('git commit -m "沒收尾的引號')
    assert 通過 is False
    assert 證據
