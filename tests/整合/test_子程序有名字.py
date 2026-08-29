"""nova 開出來的子程序在活動監視器上要看得出是誰。

活動監視器讀的是 kernel 的 `p_comm`（等同 `ps -o ucomm`），而 **kernel 在
exec 當下依執行檔路徑決定那個名字，事後改不了**——`exec -a` 與 setproctitle
只改得動 `ps` 的 args 欄，活動監視器完全不看。

所以 shebang 腳本一律顯示直譯器的名字：`.venv/bin/pytest` 的第一行是
`#!/Users/sbu/nova/.venv/bin/python`，於是它在活動監視器上叫 `python3.13`，
跟其他每一支 python 程序長得一模一樣。唯一的辦法是**拿一個名字對的真執行檔
去 exec**，所以 nova 在 venv 裡準備 python 的硬連結 `nova-<角色>`，
用它去跑那支腳本。

會 fork，所以住整合層不住單元層。
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from nova.載體.模型.執行 import 執行逾時, 跑cli
from nova.載體.程序 import 具名啟動

_回報自己名字的腳本 = """
import os, subprocess, sys
名字 = subprocess.run(
    ["ps", "-o", "ucomm=", "-p", str(os.getpid())],
    capture_output=True, text=True, check=False,
).stdout.strip()
sys.stdout.write("ucomm=%s\\n" % 名字)
sys.stdout.write("APP_ROLE=%s\\n" % os.environ.get("APP_ROLE", "沒有"))
sys.stdout.write("prefix=%s\\n" % sys.prefix)
"""


def _讀一行(輸出: str, 鍵: str) -> str:
    for 行 in 輸出.splitlines():
        if 行.startswith(f"{鍵}="):
            return 行.split("=", 1)[1]
    msg = f"輸出裡找不到 {鍵}：{輸出!r}"
    raise AssertionError(msg)


@pytest.fixture
def 假python工具(tmp_path: Path) -> Path:
    """做一支跟 pytest／mypy 同形的 console script：python shebang ＋ 沒有副檔名。"""
    工具 = tmp_path / "fake-tool"
    工具.write_text(f"#!{sys.executable}\n{_回報自己名字的腳本}", encoding="utf-8")
    工具.chmod(0o755)
    return 工具


def test_python腳本開出來的子程序在ps上叫得出名字(假python工具: Path) -> None:
    """直接跑 shebang 腳本會顯示成 python3.13；要顯示成 nova-<角色>。"""
    結果 = 跑cli(假python工具, [], 逾時秒=30.0)

    assert _讀一行(結果.標準輸出, "ucomm") == "nova-fake-tool"


def test_改名之後venv還是原來那個(假python工具: Path) -> None:
    """硬連結必須放在直譯器旁邊，否則找不到 `pyvenv.cfg` 就會掉回系統 python。

    掉回系統 python 的話 import nova 會整個爆掉——這一條比名字重要得多。
    """
    結果 = 跑cli(假python工具, [], 逾時秒=30.0)

    assert _讀一行(結果.標準輸出, "prefix") == sys.prefix


def test_子程序一律帶著APP_ROLE(假python工具: Path) -> None:
    """名字會被 kernel 決定，環境變數不會——所以識別要靠它，不要靠名字。

    macOS 15 起 `ps -E` 讀不到別人的環境變數，所以這是給**程序自己**用的
    （寫進自己的 log 或 PID 檔），不是給外面掃描用的。
    """
    結果 = 跑cli(假python工具, [], 逾時秒=30.0)

    assert _讀一行(結果.標準輸出, "APP_ROLE") == "nova.fake-tool"


def test_真二進位不准被改名() -> None:
    """`ruff`、`agy` 這種本來就有自己名字的執行檔，不准被包一層改成 nova-*。

    包一層只會把真正的名字藏起來，比不改更糟。
    """
    結果 = 跑cli(Path("/bin/echo"), ["嗨"], 逾時秒=30.0)

    assert 結果.標準輸出.strip() == "嗨"
    assert not (Path(sys.executable).parent / "nova-echo").exists()


def test_收割整棵仍然殺得掉被改名的子程序(tmp_path: Path) -> None:
    """改名是多包一層 exec，不准把上一個 PR 的收割保證弄丟。

    改名不是包一層 wrapper：`nova-fake-mute` 就是那支 python 本人，
    只是換個名字 exec。這支測試守的是「換名字之後 killpg 照樣打得到」，
    而且順便證明改名沒有偷偷多插一層讓孤兒有地方藏。
    """
    工具 = tmp_path / "fake-mute"
    工具.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(300)\n", encoding="utf-8")
    工具.chmod(0o755)

    with pytest.raises(執行逾時):
        跑cli(工具, [], 逾時秒=1.5)

    活著 = subprocess.run(
        ["pgrep", "-f", str(工具)], capture_output=True, text=True, check=False
    ).stdout.strip()
    for pid in 活著.splitlines():
        os.kill(int(pid), 9)
    assert not 活著, f"改名之後還是留了孤兒：{活著}"


def test_具名直譯器不准搬離直譯器所在的目錄(假python工具: Path) -> None:
    """`sys.executable` 搬家會打斷所有 `Path(sys.executable).parent` 的假設。

    試過把具名連結放到 `<venv>/程序名/`：`pyvenv.cfg` 照 PEP 405 往上找得到，
    `sys.prefix` 也對，但 `規則表._外部指令` 靠 `Path(sys.executable).parent`
    找 ruff／mypy／pytest，工具當場找不到，退回 PATH，Popen 直接
    FileNotFoundError——而且每次紅的測試都不一樣。
    """
    啟動列, _ = 具名啟動(假python工具, [])

    assert len(啟動列) == 2, f"python 腳本應該被包成 [具名直譯器, 腳本]，實際是 {啟動列}"
    具名 = Path(啟動列[0])
    assert 具名.parent == Path(sys.executable).parent
