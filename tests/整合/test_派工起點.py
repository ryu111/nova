"""`nova 派工 --起點` 的接續護欄：拿不到前幾階產出就不准靜靜跑下去。

`派工` 的形狀是「落票 → 搶票 → **開一棵全新工作樹** → 背景跑 工作流」。
新樹是從 base commit 切出來的，**前一階留在原樹上的未提交產出（那支紅測試）
一定不在新樹上**。所以 `--起點` 只有 `test` 有意義；其他起點等於叫實作員
「拿著不存在的紅測試去實作」——比不接續更糟，而且現在它不報錯。

這裡選甲：開新樹之前當場擋下（退出碼 2），錯誤訊息要寫出**正解那一行指令**，
而且那一行要**可以直接照抄執行**（帶得出提示來源、工作目錄、原起點），
不是一句「不支援」也不是一行照抄後會卡在 stdin 的殘缺指令。

`nova 工作流 --起點` 不開新樹，是對的那條路，不准被一起改壞。
"""

import os
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

import pytest

from nova.契約.工作流 import 階段代碼
from nova.契約.退出碼 import 阻擋
from nova.載體.剖析器 import 建剖析器

nova執行檔 = Path(sys.executable).parent / "nova"
做假CLI型 = Callable[..., tuple[Path, Path]]

#: 由 enum 自動列出，避免有人加了新階段卻漏測（`verify-refactor` 上次就漏了）。
非測試起點們 = [代碼.value for 代碼 in 階段代碼 if 代碼 is not 階段代碼.測試]

前一階的紅測試 = '''"""verify-red 留在樹上、還沒提交的那支紅測試。"""


def test_還沒實作的行為() -> None:
    from nova.尚未存在 import 還沒做的東西

    assert 還沒做的東西() == "會紅"
'''

票內容 = """# 接續測試任務

## 輸入

`src/nova/載體/命令列.py`

## 輸出

接續執行

## 驗收

<!--nova:驗收 true-->

## 停止

做不出來就停下來問人
"""


class _記名處理表(dict[str, Any]):
    """任何子命令名都回傳它自己，讓 `參數.執行` 直接說出「這行指令是誰」。"""

    def __missing__(self, 鍵: str) -> str:
        return 鍵


def _跑(*參數: str, 狀態: Path, 在: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=在,
        env={**os.environ, "XDG_STATE_HOME": str(狀態)},
        capture_output=True,
        text=True,
        check=False,
    )


def _造被殺掉那棵樹(根: Path) -> tuple[Path, Path]:
    """重現現場：一棵有 commit 的樹，樹上留著 verify-red 產出的**未提交**紅測試。

    回傳（票檔, 那支未提交的紅測試）。
    """

    def git(*指令: str) -> int:
        return subprocess.run(["git", *指令], cwd=根, check=False).returncode

    for 指令 in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "測試@例子"),
        ("config", "user.name", "測試"),
    ):
        assert git(*指令) == 0
    (根 / "讀我.md").write_text("第一版\n", encoding="utf-8")
    assert git("add", "-A") == 0
    assert git("commit", "-q", "-m", "第一版") == 0

    紅測試 = 根 / "tests" / "test_前一階的紅測試.py"
    紅測試.parent.mkdir(parents=True, exist_ok=True)
    紅測試.write_text(前一階的紅測試, encoding="utf-8")
    票檔 = 根 / "票.md"
    票檔.write_text(票內容, encoding="utf-8")
    # 這兩個檔就是「前幾階的產出」：故意不 commit，這正是派工開新樹會弄丟的東西。
    髒的 = subprocess.run(
        ["git", "status", "--porcelain", "-uall", "--", str(紅測試)],
        cwd=根,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert 髒的.strip(), "現場沒佈置成功：那支紅測試竟然不是未提交狀態"
    return 票檔, 紅測試


def _抄得下來的接續指令(錯誤訊息: str) -> list[str]:
    """從錯誤訊息裡挖出那一行 `nova 工作流 ...`，切成 argv。"""
    for 行 in 錯誤訊息.splitlines():
        if "nova 工作流" in 行:
            片段 = 行[行.index("nova 工作流") :]
            return shlex.split(片段.split("`")[0])
    pytest.fail(f"錯誤訊息裡找不到 `nova 工作流 ...` 的正解指令：{錯誤訊息!r}")


@pytest.fixture
def 被殺掉的樹(tmp_path: Path) -> tuple[Path, Path, Path]:
    """回傳（狀態目錄, 那棵樹, 票檔）。"""
    狀態 = tmp_path / "state"
    樹 = tmp_path / "nova-wt-被殺掉的線"
    樹.mkdir()
    票檔, _ = _造被殺掉那棵樹(樹)
    return 狀態, 樹, 票檔


@pytest.fixture
def 開樹與發射都當場炸(monkeypatch: pytest.MonkeyPatch) -> None:
    """護欄該擋在「開新樹」之前，所以這兩件事在這幾支測試裡一律當場炸。

    這同時是**負控的安全帶**：把護欄拿掉時，測試會炸在這裡而不是
    真的切一棵工作樹、真的在背景叫一顆模型起來。
    """
    import nova.載體.命令列 as 命令列

    def 不准開樹(*_: object, **__: object) -> Path:
        pytest.fail("護欄沒擋住：派工已經動手開新工作樹了")

    def 不准發射(*_: object, **__: object) -> Path:
        pytest.fail("護欄沒擋住：派工已經在背景發射一條線了")

    monkeypatch.setattr(命令列, "開一個工作樹", 不准開樹)
    monkeypatch.setattr(命令列, "_發射背景程序", 不准發射)


class Test派工起點護欄:
    @pytest.mark.usefixtures("開樹與發射都當場炸")
    @pytest.mark.parametrize("起點", 非測試起點們)
    def test_派工在有未提交紅測試的樹上收到非測試起點時當場擋下(
        self,
        被殺掉的樹: tuple[Path, Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        起點: str,
    ) -> None:
        """`test` 以外的每一個起點都要被擋，而且要在開新樹之前擋。"""
        from nova.載體.命令列 import 主程式

        _, 樹, 票檔 = 被殺掉的樹
        monkeypatch.setattr(sys, "argv", ["nova", "派工", str(票檔), "--起點", 起點])

        碼 = 主程式(["派工", str(票檔), "--起點", 起點, "--工作目錄", str(樹), "--判準", "true"])

        輸出 = capsys.readouterr()
        assert 碼 == 阻擋, (
            f"派工收到 --起點 {起點} 應以退出碼 {阻擋} 擋下，實際 {碼}。\n"
            f"stdout: {輸出.out}\nstderr: {輸出.err}"
        )

    @pytest.mark.usefixtures("開樹與發射都當場炸")
    @pytest.mark.parametrize("起點", 非測試起點們)
    def test_擋下時給的是照抄就能跑的接續指令(
        self,
        被殺掉的樹: tuple[Path, Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        起點: str,
    ) -> None:
        """訊息裡那一行要真的能接續這張票：有提示來源、有那棵樹、有原起點。

        只說「不支援」不算；只寫 `nova 工作流 --工作目錄 <樹> --起點 impl`
        也不算——照抄執行會因為沒題目而卡在 stdin。
        """
        from nova.載體.命令列 import 主程式

        _, 樹, 票檔 = 被殺掉的樹
        monkeypatch.setattr(sys, "argv", ["nova", "派工", str(票檔), "--起點", 起點])
        主程式(["派工", str(票檔), "--起點", 起點, "--工作目錄", str(樹), "--判準", "true"])

        指令 = _抄得下來的接續指令(capsys.readouterr().err)
        assert 指令[0] == "nova"
        參數 = 建剖析器(cast(Mapping[str, Any], _記名處理表())).parse_args(指令[1:])

        assert 參數.執行 == "工作流", f"正解那條路是 nova 工作流，實際：{指令}"
        assert 參數.提示檔 == str(票檔), f"接續指令要帶得出這張票（否則照抄後會等 stdin）：{指令}"
        assert 參數.工作目錄 == str(樹), f"接續指令要指回原本那棵樹：{指令}"
        assert 參數.起點 == 起點, f"接續指令要保留原本的起點 {起點}：{指令}"

    def test_被擋下時不准開新樹也不准動到樹上的紅測試(
        self, 被殺掉的樹: tuple[Path, Path, Path], 做假CLI: 做假CLI型
    ) -> None:
        """走真的命令列：擋下之後，旁邊不准長出 `nova-wt-*`，紅測試要原封不動。"""
        狀態, 樹, 票檔 = 被殺掉的樹
        執行檔, _ = 做假CLI("claude")
        既有的樹們 = set(樹.parent.glob("nova-wt-*"))

        結果 = _跑(
            "派工",
            str(票檔),
            "--起點",
            階段代碼.實作.value,
            "--工作目錄",
            str(樹),
            "--用",
            "claude",
            "--審查用",
            "codex",
            "--執行檔",
            str(執行檔),
            "--最多步數",
            "0",
            "--判準",
            "true",
            狀態=狀態,
            在=樹,
        )

        assert 結果.returncode == 阻擋, (
            f"實際 {結果.returncode}\nstdout: {結果.stdout}\nstderr: {結果.stderr}"
        )
        新長的 = set(樹.parent.glob("nova-wt-*")) - 既有的樹們
        assert not 新長的, f"被擋下的派工不准開新工作樹：{新長的}"
        紅測試 = 樹 / "tests" / "test_前一階的紅測試.py"
        assert 紅測試.read_text(encoding="utf-8") == 前一階的紅測試, (
            "被擋下的派工不准動到原樹上前一階的產出"
        )

    def test_派工起點為測試時不被護欄擋下(
        self, 被殺掉的樹: tuple[Path, Path, Path], 做假CLI: 做假CLI型
    ) -> None:
        """護欄只針對非 test 起點；`--起點 test` 是派工本來就在做的事。"""
        狀態, 樹, 票檔 = 被殺掉的樹
        執行檔, _ = 做假CLI("claude")

        結果 = _跑(
            "派工",
            str(票檔),
            "--起點",
            階段代碼.測試.value,
            "--用",
            "claude",
            "--審查用",
            "codex",
            "--執行檔",
            str(執行檔),
            "--最多步數",
            "0",
            "--判準",
            "true",
            狀態=狀態,
            在=樹,
        )

        assert 結果.returncode != 阻擋, (
            f"起點 test 不該被護欄擋下：\nstdout: {結果.stdout}\nstderr: {結果.stderr}"
        )

    @pytest.mark.parametrize("起點", 非測試起點們)
    def test_工作流依然吃得下非測試起點(
        self, 被殺掉的樹: tuple[Path, Path, Path], 做假CLI: 做假CLI型, 起點: str
    ) -> None:
        """`nova 工作流` 原地跑、不開新樹，接續是它的事，不准被一起改壞。"""
        狀態, 樹, 票檔 = 被殺掉的樹
        執行檔, _ = 做假CLI("claude")

        結果 = _跑(
            "工作流",
            "--提示檔",
            str(票檔),
            "--起點",
            起點,
            "--工作目錄",
            str(樹),
            "--用",
            "claude",
            "--審查用",
            "codex",
            "--執行檔",
            str(執行檔),
            "--最多步數",
            "0",
            "--判準",
            "true",
            狀態=狀態,
            在=樹,
        )

        assert 結果.returncode != 阻擋, f"工作流 --起點 {起點} 不該被起點護欄擋下：{結果.stderr}"
