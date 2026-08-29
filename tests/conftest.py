"""所有測試共用的定位點與假 CLI。

假 CLI 放這裡不放 `tests/整合/conftest.py`：測試目錄沒有 `__init__.py`
（專案骨架規定），兩個同名的 `conftest` 會讓 mypy 當場紅
（Duplicate module named "conftest"）。**只留一個 conftest** 就沒這問題。

fixture 由 pytest 自己發現，測試檔不必也不該 import 它們——
跨檔 import 會讓同一個檔被算成 `conftest` 與 `tests.conftest` 兩個模組。
"""

import stat
import sys
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def 帳本不准寫到家目錄(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把 `預設帳本目錄()` 整個導到暫存區。**autouse，沒有例外。**

    這是被一次真實污染逼出來的：跑負控（讓門面永遠開帳本）時，測試套件在
    `~/.local/state/nova/帳本/` 留下 73 個檔案，而當時的測試看的是 `tmp_path`
    ——**看錯地方，所以那支負控沒有變紅**。

    測試不准在使用者家目錄留東西；而且沒有這個 fixture，
    「不給目錄就不記帳」那條保證根本驗不了（真的寫了也不在 tmp_path 裡）。
    """
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


@pytest.fixture(scope="session")
def 專案根() -> Path:
    """回傳 repo 根目錄（本檔案的上一層）。"""
    return Path(__file__).resolve().parent.parent


實錄目錄 = Path(__file__).resolve().parent / "整合" / "實錄"
#: 每家的 envelope 形狀不同，假 CLI 要吐對應那份——吐錯的話解析器會 fail-closed
#: 回「結果未知」，工作流當場停（那是對的行為，只是不該在這裡發生）。
成功實錄 = {
    "claude": "claude_ok.json",
    "codex": "codex_ok2.jsonl",
    "agy": "agy_ok.json",
}


#: 假 CLI 的內容。**行為靠環境變數切，不靠「每支測試重寫一份檔」**——
#: 實測（macOS、n=15 取中位數）新寫一份檔再第一次執行要 122 毫秒，
#: 同一支重複執行只要 14 毫秒。那 100 毫秒是 macOS 對「剛寫出來的新執行檔」
#: 的第一次執行檢查，每支測試白付一次。13 支就是 1.3 秒。
#:
#: shebang 走 `sys.executable` 不走 `/usr/bin/env python3`：後者在這台機器上
#: 指到系統的 3.9.6，不是專案釘的 3.13。
#:
#: 環境變數名走 ASCII（跨程序，CLAUDE.md 的例外條款），用執行檔自己的名字當
#: key——同一份內容擺三個檔名，才有辦法在同一支測試裡同時當 codex 與 agy。
假CLI內容 = f"""#!{sys.executable}
import json, os, pathlib, sys
名 = pathlib.Path(sys.argv[0]).name.replace("fake-", "").upper()
紀錄 = os.environ.get(f"NOVA_FAKE_{{名}}_RECORD")
if 紀錄:
    pathlib.Path(紀錄).write_text(
        json.dumps({{"argv": sys.argv[1:], "who": sys.argv[0]}}), encoding="utf-8")
sys.stdout.write(
    pathlib.Path(os.environ[f"NOVA_FAKE_{{名}}_TRANSCRIPT"]).read_text(encoding="utf-8"))
"""


@pytest.fixture(scope="session")
def 假CLI群(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """三家各一支，整個 session 共用。內容一樣，靠檔名分辨自己是誰。"""
    目錄 = tmp_path_factory.mktemp("假cli群")
    群: dict[str, Path] = {}
    for 家 in 成功實錄:
        路徑 = 目錄 / f"fake-{家}"
        路徑.write_text(假CLI內容, encoding="utf-8")
        路徑.chmod(路徑.stat().st_mode | stat.S_IEXEC)
        群[家] = 路徑
    return 群


#: 這個 fixture 的形狀。conftest 自己用一份，測試檔各自寫一份——
#: 跨檔 import 會讓 mypy 把 conftest 算成兩個模組（測試目錄沒有 `__init__.py`）。
_做假CLI型 = Callable[..., tuple[Path, Path]]


@pytest.fixture
def 做假CLI(
    假CLI群: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> _做假CLI型:
    """回傳 (執行檔, 紀錄檔)。紀錄檔每支測試獨立，執行檔整個 session 共用。"""

    def 做(家: str = "claude", 實錄檔: str | None = None) -> tuple[Path, Path]:
        紀錄 = tmp_path / f"{家}.json"
        鍵 = 家.upper()
        monkeypatch.setenv(f"NOVA_FAKE_{鍵}_TRANSCRIPT", str(實錄目錄 / (實錄檔 or 成功實錄[家])))
        monkeypatch.setenv(f"NOVA_FAKE_{鍵}_RECORD", str(紀錄))
        return 假CLI群[家], 紀錄

    return 做


@pytest.fixture
def 翻牌判準(tmp_path: Path) -> Path:
    """第一次紅、之後綠的判準。讓 驗證紅 與 驗證綠 都能走到。

    做成 fixture 不做成函式：測試目錄沒有 `__init__.py`，跨檔 import
    會讓 mypy 把同一個檔算成兩個模組（`conftest` 與 `tests.conftest`）當場紅。
    **fixture 是 pytest 自己發現的，不必 import**，所以沒有這個問題。
    """
    旗標 = tmp_path / "跑過了"
    腳本 = tmp_path / "判準.sh"
    腳本.write_text(f'#!/bin/sh\nif [ -f "{旗標}" ]; then exit 0; fi\ntouch "{旗標}"\nexit 1\n')
    腳本.chmod(腳本.stat().st_mode | stat.S_IEXEC)
    return 腳本
