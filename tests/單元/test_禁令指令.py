"""禁令的機械化版本：檢查是否違反禁令。

CLAUDE.md 寫了規則（不准 --no-verify、--admin，以及合併必須 --delete-branch），但寫著不等於擋得住。
"""

import pytest

from nova.載體.禁令 import 檢查指令

應拒絕 = [
    "git commit --no-verify -m 訊息",
    "git commit -n -m 訊息",
    "git commit -nm 訊息",
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

    改成：拆不開時依已解析出的命令段判斷。看得出真正命令就照硬禁令判斷，
    看不出來的部分不把內文或訊息文字當成命令參數。
    """
    通過, _ = 檢查指令('git commit -m "沒收尾的引號')
    assert 通過 is True, "沒有禁令關鍵詞，不該因為引號沒收尾就被擋"


def test_heredoc內文提到缺少刪除分支的合併指令仍然放行() -> None:
    """heredoc 只是輸出文件內容，內文的合併指令不會被 shell 執行。"""
    命令 = "cat <<'EOF'" + chr(10) + "gh pr merge 123 --squash" + chr(10) + "EOF"

    通過, 原因 = 檢查指令(命令)

    assert 通過 is True, f"heredoc 內文被誤當成要執行的指令：{原因}"


def test_引號內的heredoc樣式不應遮掉後續真正的合併指令() -> None:
    """引號裡的 heredoc 樣式只是文字，下一行的命令仍會被 shell 執行。"""
    命令 = 'echo "這不是 heredoc：<<EOF"' + chr(10) + "gh pr merge 123 --squash"

    通過, 原因 = 檢查指令(命令)

    assert 通過 is False, f"後續真正的合併指令被引號內文字遮掉：{原因}"


def test_echo提到刪除分支旗標仍然放行() -> None:
    """echo 的字串是輸出內容，不是 gh pr merge 的參數。"""
    通過, 原因 = 檢查指令('echo "記得帶 --delete-branch"')
    assert 通過 is True, f"echo 內容被誤當成合併指令：{原因}"


def test_文件說明不准跳過驗證的旗標仍然放行() -> None:
    """文件內文提到旗標，不代表 shell 會把旗標傳給 git。"""
    命令 = "cat <<'EOF'" + chr(10) + "git commit 不准使用 --no-verify" + chr(10) + "EOF"
    通過, 原因 = 檢查指令(命令)
    assert 通過 is True, f"文件內文被誤當成 git 參數：{原因}"


def test_git_commit訊息提到旗標仍然放行() -> None:
    """`-m` 的字串是 commit 訊息，不是傳給 git 的旗標。"""
    通過, 原因 = 檢查指令('git commit -m "--no-verify"')
    assert 通過 is True, f"commit 訊息被誤當成旗標：{原因}"


@pytest.mark.parametrize(
    "命令",
    [
        "git -C . commit --no-verify",
        "HUSKY=0 git commit --no-verify",
        "sudo git commit --no-verify",
        "(git commit --no-verify)",
    ],
)
def test_命令前綴包住真的git仍然要擋(命令: str) -> None:
    """前綴不會改變實際執行的 git commit 行為。"""
    通過, 原因 = 檢查指令(命令)
    assert 通過 is False, f"真的 git commit 被前綴繞過：{命令}；{原因}"


class Test拆不開的指令:
    """`shlex` 拆不開時不准硬擋——會把 heredoc 這種正常指令全部誤擋掉。

    實測擋過一次：一條寫測試用的 heredoc，裡面有巢狀引號，被擋在跟禁令毫無關係的地方。
    """

    def test_拆不開但沒有禁令要放行(self) -> None:
        沒收尾的引號 = "python3 - <<'PY'" + chr(10) + 'print("沒收尾' + chr(10) + "PY"
        通過, 原因 = 檢查指令(沒收尾的引號)
        assert 通過 is True, f"正常的 heredoc 被誤擋：{原因}"

    def test_拆不開但有禁令還是要擋(self) -> None:
        """拆不開時仍依已解析出的命令段擋下真正的禁令。"""
        通過, 原因 = 檢查指令('git commit --no-verify -m "沒收尾的引號')
        assert 通過 is False
        assert "--no-verify" in 原因

    def test_拆不開時的原因要說清楚(self) -> None:
        通過, 原因 = 檢查指令('gh pr merge --admin -t "沒收尾')
        assert 通過 is False
        assert "拆不開" in 原因, "要讓人知道判定是走退路來的"


class Test合併必須帶刪除分支:
    """PR 合併必須帶 `--delete-branch` 收尾，否則留下一堆遠端殘枝。"""

    def test_沒有帶刪除分支要被擋下(self) -> None:
        通過, 理由 = 檢查指令("gh pr merge 71 --squash")
        assert 通過 is False
        assert "--delete-branch" in 理由, "擋下理由必須提及缺少 --delete-branch"

    def test_有帶刪除分支放行(self) -> None:
        通過, _ = 檢查指令("gh pr merge 71 --squash --delete-branch")
        assert 通過 is True

    def test_git_merge_不准誤擋(self) -> None:
        通過, _ = 檢查指令("git merge main")
        assert 通過 is True

    @pytest.mark.parametrize("命令", ["gh pr list", "gh pr view 71"])
    def test_非合併指令不准誤擋(self, 命令: str) -> None:
        通過, _ = 檢查指令(命令)
        assert 通過 is True

    def test_管理員旗標又帶刪除分支仍然要被擋下(self) -> None:
        """帶 --admin 又帶 --delete-branch，仍要被管理員禁令擋下，不能因為有 delete-branch 放行。"""
        通過, 理由 = 檢查指令("gh pr merge 71 --squash --delete-branch --admin")
        assert 通過 is False
        assert "--admin" in 理由

    def test_拆不開的正確合併不准被退路擋掉(self) -> None:
        """拆不開時仍依已解析出的命令段判斷，不把完整指令誤當成禁令。"""
        通過, _ = 檢查指令('gh pr merge 71 --squash --delete-branch --body "沒收尾')
        assert 通過 is True, "帶了 --delete-branch 的合併，就算拆不開也不准擋"

    def test_gh的其他子命令帶merge這個詞不准誤擋(self) -> None:
        """判斷要三個詞同時在。少看 `pr` 的話，job 叫 merge 的指令會被誤擋。"""
        通過, _ = 檢查指令("gh run view --job merge")
        assert 通過 is True
