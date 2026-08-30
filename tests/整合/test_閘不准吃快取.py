"""ruff 與 mypy 的快取都會給假綠，閘不准吃它們。

**這支是被一次真實失誤逼出來的。** 在一個 worktree 裡，同一份工作區：

    uv run ruff check .              → All checks passed!
    uv run ruff check --no-cache .   → Found 1 error（I001）

`nova 閘 ci` 全綠、推上去 CI 當場紅。這種綠比紅更糟——它是**假的安全感**，
讀的人會以為不用自己檢查。

機制（本檔的第一支測試就是它的最小重現）：**ruff 的快取鍵是
（路徑、檔案大小、mtime 奈秒），不含內容**。三者中的前兩項一樣、內容不一樣，
就會拿到上一次的結論。任何保留 mtime 的動作都踩得到——`cp -p`、`rsync -t`、
tar 解開、部分 git 操作。

代價幾乎是零：本專案 95 個檔，有快取 26 毫秒、沒快取 27 毫秒。
**快取買到 1 毫秒，賣掉的是「閘綠等於 CI 綠」這個保證。**

## mypy 是同一個坑的第二個實例，而且更容易踩

mypy 的快取鍵是（路徑、大小、**整數秒** mtime）。它只在 mtime 對不上時
才去比內容雜湊，所以「同一秒內改兩次、長度剛好一樣」會直接吃到上一次的結論
——**連保留 mtime 的動作都不需要**。

那個「剛好一樣」不是巧合：2026-08-30 跑遮罩型別化的負控時，
把兩處 `已遮罩文字` 各改回 `str`，兩次破壞的檔案長度完全相同（6685 bytes）。
結果第二條負控紅的是**第一條那一格**。差一點就把它當成「測試寫錯了」。

代價：146 個檔 0.07 秒 → 1.09 秒。
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from nova.載體.規則表 import 建規則表

專案根目錄 = Path(__file__).resolve().parents[2]
_ruff = Path(sys.executable).parent / "ruff"
_mypy = Path(sys.executable).parent / "mypy"

_排好的 = b"import os\nimport sys\n\nprint(os, sys)\n"
#: 跟上面**一模一樣的長度**，只有 import 順序反過來（會被 I001 抓到）。
_排錯的 = b"import sys\nimport os\n\nprint(os, sys)\n"

_設定 = """\
[project]
name = "假專案"
version = "0"

[tool.ruff.lint]
select = ["I"]
"""


def _做出會騙人的快取(工地: Path) -> None:
    """先讓 ruff 記住「這個檔是乾淨的」，再把內容換掉但不動大小與 mtime。"""
    (工地 / "pyproject.toml").write_text(_設定, encoding="utf-8")
    檔 = 工地 / "某檔.py"
    檔.write_bytes(_排好的)
    subprocess.run([str(_ruff), "check", "."], cwd=工地, capture_output=True, check=False)

    先前 = 檔.stat()
    檔.write_bytes(_排錯的)
    os.utime(檔, ns=(先前.st_atime_ns, 先前.st_mtime_ns))
    現在 = 檔.stat()
    assert 現在.st_size == 先前.st_size, "重現前提：大小要一樣"
    assert 現在.st_mtime_ns == 先前.st_mtime_ns, "重現前提：mtime 奈秒要一樣"


@pytest.mark.skipif(not _ruff.exists(), reason="這個 venv 裡沒有 ruff")
def test_ruff的快取真的會給假綠(tmp_path: Path) -> None:
    """先證明那個坑是真的。證不出坑，下面那支就只是在拜拜。"""
    _做出會騙人的快取(tmp_path)

    吃快取 = subprocess.run(
        [str(_ruff), "check", "."], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    不吃快取 = subprocess.run(
        [str(_ruff), "check", "--no-cache", "."],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert 吃快取.returncode == 0, f"這個坑不存在了？{吃快取.stdout}"
    assert 不吃快取.returncode != 0, "沒快取也抓不到，那重現寫錯了"


@pytest.mark.skipif(not _ruff.exists(), reason="這個 venv 裡沒有 ruff")
def test_閘的ruff規則不會被假快取騙過去(tmp_path: Path) -> None:
    """同一個坑，換成走 `建規則表` 那條路——閘必須照樣紅。

    這支跟上面那支的差別就是「有沒有人叫 `--no-cache`」。
    把規則表裡的那個旗標拿掉，這支會紅、上面那支照樣綠。
    """
    _做出會騙人的快取(tmp_path)

    規則們 = {規則.代碼: 規則 for 規則 in 建規則表(tmp_path)}
    綠, 輸出 = 規則們["ruff-check"].檢查()

    assert not 綠, f"閘被假快取騙過去了：{輸出}"


@pytest.mark.skipif(not _ruff.exists(), reason="這個 venv 裡沒有 ruff")
def test_本repo沒快取也是綠的(tmp_path: Path) -> None:
    """把 repo 自己的 ruff 用全新的快取目錄跑一次。

    平常的 `uv run ruff check .` 用的是 `.ruff_cache`，那份可能已經在騙人。
    """
    環境 = {**os.environ, "RUFF_CACHE_DIR": str(tmp_path / "全新快取")}
    結果 = subprocess.run(
        [str(_ruff), "check", "--no-cache", "."],
        cwd=專案根目錄,
        capture_output=True,
        text=True,
        check=False,
        env=環境,
    )
    assert 結果.returncode == 0, 結果.stdout + 結果.stderr


#: 型別對的版本。mypy 乾淨。
_型別對的 = b"def f(x: int) -> int:\n    return x\n"
#: **跟上面一模一樣的長度**，但回傳型別錯了。
_型別錯的 = b"def f(x: int) -> str:\n    return x\n"

_mypy設定 = """\
[project]
name = "假專案"
version = "0"

[tool.mypy]
files = ["某檔.py"]
strict = true
"""


def _做出會騙人的mypy快取(工地: Path) -> None:
    """先讓 mypy 記住「這個檔沒問題」，再把內容換掉但不動大小與**整數秒** mtime。

    **不必保留奈秒**——mypy 存的是 `int(st_mtime)`，所以同一秒內改兩次就夠。
    這裡仍然明寫 `os.utime`，是為了讓重現不依賴「這兩行跑得夠快」。

    **兩次都走設定檔不帶旗標**：mypy 的快取鍵含 options 指紋，
    一次帶 `--strict` 一次讀設定的話快取根本不會命中，那重現就不成立了。
    """
    (工地 / "pyproject.toml").write_text(_mypy設定, encoding="utf-8")
    檔 = 工地 / "某檔.py"
    檔.write_bytes(_型別對的)
    subprocess.run([str(_mypy)], cwd=工地, capture_output=True, check=False)

    先前 = 檔.stat()
    檔.write_bytes(_型別錯的)
    os.utime(檔, ns=(先前.st_atime_ns, 先前.st_mtime_ns))
    現在 = 檔.stat()
    assert 現在.st_size == 先前.st_size, "重現前提：大小要一樣"
    assert int(現在.st_mtime) == int(先前.st_mtime), "重現前提：整數秒 mtime 要一樣"


@pytest.mark.skipif(not _mypy.exists(), reason="這個 venv 裡沒有 mypy")
def test_mypy的快取真的會給假綠(tmp_path: Path) -> None:
    """先證明那個坑是真的。證不出坑，下面那支就只是在拜拜。"""
    _做出會騙人的mypy快取(tmp_path)

    吃快取 = subprocess.run([str(_mypy)], cwd=tmp_path, capture_output=True, text=True, check=False)
    不吃快取 = subprocess.run(
        [str(_mypy), "--no-incremental"], cwd=tmp_path, capture_output=True, text=True, check=False
    )

    assert 吃快取.returncode == 0, f"這個坑不存在了？{吃快取.stdout}"
    assert 不吃快取.returncode != 0, "沒快取也抓不到，那重現寫錯了"


@pytest.mark.skipif(not _mypy.exists(), reason="這個 venv 裡沒有 mypy")
def test_閘的mypy規則不會被假快取騙過去(tmp_path: Path) -> None:
    """同一個坑，換成走 `建規則表` 那條路——閘必須照樣紅。

    這支跟上面那支的差別就是「有沒有人叫 `--no-incremental`」。
    把規則表裡的那個旗標拿掉，這支會紅、上面那支照樣綠。
    """
    _做出會騙人的mypy快取(tmp_path)

    規則們 = {規則.代碼: 規則 for 規則 in 建規則表(tmp_path)}
    綠, 輸出 = 規則們["mypy"].檢查()

    assert not 綠, f"閘被假快取騙過去了：{輸出}"
