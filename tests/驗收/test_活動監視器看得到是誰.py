"""使用者說的那句話：**「在活動監視器的名稱也要叫 nova。」**

## 為什麼 shebang 腳本不夠

程序名稱由 kernel 在 `exec` 當下**依真正執行的那個二進位**決定，事後改不了。
`.venv/bin/nova` 是一個文字檔，開頭 `#!` 指到直譯器——所以 kernel 執行的是
**直譯器**，活動監視器顯示的也是它：

```
ps -o ucomm  →  python3.13          ← 活動監視器讀的就是這個
ps -o args   →  .../python3 .../nova 工作流 --從收件匣
```

實測（2026-08-30，macOS 15）：`nova 額度` 的 `ucomm` 是 `python3.13`。
一台機器上跑幾個 python 工具就會出現一排分不出誰是誰的 `python3`。

## 解法：把直譯器硬連結成專門的名字

`.venv/bin/nova-inbox` 硬連結到同一份直譯器二進位，`ProgramArguments[0]`
指它。kernel 就依這個名字命名，而 venv 照樣找得到
（Python 是從 `sys.executable` 的上一層找 `pyvenv.cfg`，硬連結還在 `.venv/bin/` 裡）。

名字走 ASCII kebab-case：**`pkill`、log 過濾、launchctl 的字串比對都在讀它**，
中文會出問題。這是 CLAUDE.md 的 ASCII 例外條款。
"""

import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

nova執行檔 = Path(sys.executable).parent / "nova"

#: 這些名字出現在活動監視器上等於沒有名字。
_不准的名字 = {"python", "python3", "python3.13", "sh", "bash", "zsh", "uv", "env", "node"}


def _跑(*參數: str, 狀態: Path, 在: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=在,
        env={**os.environ, "XDG_STATE_HOME": str(狀態)},
        capture_output=True,
        text=True,
        check=False,
    )


def _plist的指令(狀態: Path, 專案: Path) -> list[str]:
    印出來 = _跑("排程", 狀態=狀態, 在=專案).stdout
    設定 = plistlib.loads(印出來.split("</plist>")[0].encode("utf-8") + b"</plist>")
    參數: list[str] = 設定["ProgramArguments"]
    return 參數


@pytest.fixture
def 佈景(tmp_path: Path) -> tuple[Path, Path]:
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    專案.mkdir()
    return 狀態, 專案


def _kernel叫它什麼(指令: list[str]) -> str:
    """真的生一個程序出來，問 kernel 它叫什麼。**不能用推的。**"""
    程序 = subprocess.Popen(指令, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            看到 = subprocess.run(
                ["ps", "-p", str(程序.pid), "-o", "ucomm="],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            if 看到:
                return 看到
        return ""
    finally:
        程序.kill()
        程序.wait()


class Test活動監視器看得到是誰:
    def test_啟動器自己的kernel名字是nova開頭(self, 佈景: tuple[Path, Path]) -> None:
        """**這一支是這個檔案的重點。** 其他都是形狀，這一支是可達性。"""
        狀態, 專案 = 佈景
        指令 = _plist的指令(狀態, 專案)

        叫什麼 = _kernel叫它什麼([指令[0], "-c", "import time; time.sleep(5)"])

        assert 叫什麼.startswith("nova"), f"活動監視器會顯示 {叫什麼!r}"
        assert 叫什麼 not in _不准的名字

    def test_plist第一格不是共用直譯器(self, 佈景: tuple[Path, Path]) -> None:
        """第一格是共用直譯器的話，「登入項目與延伸功能」只會顯示 `python3`。"""
        狀態, 專案 = 佈景

        指令 = _plist的指令(狀態, 專案)

        assert Path(指令[0]).name not in _不准的名字, 指令[0]
        assert Path(指令[0]).name.startswith("nova"), 指令[0]

    def test_啟動器真的在而且跑得動(self, 佈景: tuple[Path, Path]) -> None:
        """**印出來的路徑必須存在且可執行。**

        不然 launchd 的 job 永久壞掉，而背景項目還在那裡。
        """
        狀態, 專案 = 佈景

        啟動器 = Path(_plist的指令(狀態, 專案)[0])

        assert 啟動器.is_file(), 啟動器
        assert os.access(啟動器, os.X_OK), 啟動器

    def test_啟動器跑得動而且匯得到nova(self, 佈景: tuple[Path, Path]) -> None:
        """硬連結出來的直譯器**還要找得到 venv**——找不到的話 `import nova` 會炸。"""
        狀態, 專案 = 佈景
        啟動器 = _plist的指令(狀態, 專案)[0]

        跑完 = subprocess.run(
            [啟動器, "-c", "import nova; print(nova.__file__)"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert 跑完.returncode == 0, 跑完.stderr
        assert "nova" in 跑完.stdout


def test_那行指令整條真的跑得起來(佈景: tuple[Path, Path], tmp_path: Path) -> None:
    """**判準三：墊片證明的是轉遞形狀，不是可達性。**

    第一格換成硬連結的直譯器之後，後面那幾格也得跟著對
    （`-m nova` 要有 `__main__.py`）。整條拿出來跑一次才知道。

    跑的地方是 **daemon 那份 checkout**，不是 `專案`：排程醒來站的就是那裡。
    """
    狀態, 專案 = 佈景
    指令 = _plist的指令(狀態, 專案)
    站的地方 = tmp_path / "daemon那份"
    站的地方.mkdir()
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q"], cwd=站的地方, check=True)
    subprocess.run([*git, "commit", "-qm", "起點", "--allow-empty"], cwd=站的地方, check=True)

    跑完 = subprocess.run(
        指令,
        cwd=站的地方,
        env={**os.environ, "XDG_STATE_HOME": str(狀態)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert 跑完.returncode == 0, 跑完.stdout + 跑完.stderr
    assert "巡自己的 HEAD" in 跑完.stdout, f"跑起來的不是巡：{跑完.stdout}"
