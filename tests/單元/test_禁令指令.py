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


def test_語法壞掉但沒禁令的指令放行() -> None:
    """需求變了，這支跟著改。

    原本是「拆不開一律擋（fail-closed）」。實測發現那條會把 heredoc、
    巢狀引號這種完全正常的指令誤擋掉——而且擋在跟禁令毫無關係的地方，
    使用者只看得到「指令拆不開」，完全不知道為什麼不能跑。

    改成：拆不開就退回關鍵詞掃描。這不會變寬鬆——`--no-verify` 與 `--admin`
    出現在原文裡就算，比拆詞更容易命中（會多擋不會少擋）。
    擋不住的只有刻意混淆，而這裡的對象不是對手，是會手滑的執行者。
    """
    通過, _ = 檢查指令('git commit -m "沒收尾的引號')
    assert 通過 is True, "沒有禁令關鍵詞，不該因為引號沒收尾就被擋"


class Test拆不開的指令:
    """`shlex` 拆不開時不准硬擋——會把 heredoc 這種正常指令全部誤擋掉。

    實測擋過一次：一條寫測試用的 heredoc，裡面有巢狀引號，被擋在跟禁令毫無關係的地方。
    """

    def test_拆不開但沒有禁令要放行(self) -> None:
        沒收尾的引號 = "python3 - <<'PY'" + chr(10) + 'print("沒收尾' + chr(10) + "PY"
        通過, 原因 = 檢查指令(沒收尾的引號)
        assert 通過 is True, f"正常的 heredoc 被誤擋：{原因}"

    def test_拆不開但有禁令還是要擋(self) -> None:
        """退成關鍵詞掃描不會變寬鬆——原文出現就算。"""
        通過, 原因 = 檢查指令('git commit --no-verify -m "沒收尾的引號')
        assert 通過 is False
        assert "--no-verify" in 原因

    def test_拆不開時的原因要說清楚(self) -> None:
        通過, 原因 = 檢查指令('gh pr merge --admin -t "沒收尾')
        assert 通過 is False
        assert "拆不開" in 原因, "要讓人知道判定是走退路來的"
