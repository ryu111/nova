"""帳本真的寫到磁碟上會怎樣。碰檔案、會 fork，所以住整合層。

形狀的部分在 `tests/單元/test_帳本寫入.py`（用 StringIO）。這裡只驗
**只有真的用檔案才驗得出來**的三件事：flush 的耐久性、開檔失敗的終局、
預設路徑落在哪。
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from nova.契約.帳本 import 事件, 事件種類
from nova.載體.帳本 import 開帳本, 預設帳本目錄


def test_檔名就是執行識別碼(tmp_path: Path) -> None:
    """一次執行一個檔。共用一個檔的話，兩次執行的事件會交錯在一起。"""
    with 開帳本(tmp_path, 執行識別碼="abc123") as 帳:
        帳.記一筆(事件(種類=事件種類.呼叫開始))
    assert (tmp_path / "abc123.jsonl").exists()


def test_目錄不存在會自己建(tmp_path: Path) -> None:
    深 = tmp_path / "a" / "b" / "c"
    with 開帳本(深, 執行識別碼="r") as 帳:
        帳.記一筆(事件(種類=事件種類.呼叫開始))
    assert (深 / "r.jsonl").exists()


def test_同一個識別碼開第二次要當場炸(tmp_path: Path) -> None:
    """**撞號不准靜默合併。**

    這支本來叫 `test_同一個識別碼是接在後面不是蓋掉`，守的是「用 `a` 開，
    續接同一次執行不會洗掉前面的證據」。**那個需求沒有呼叫端**——
    `開帳本` 的三個呼叫端沒有任何一個會對同一個號開第二次檔。

    所以 `a` 實際擋住的不是「洗掉」，是把**兩次不同執行**的事件交錯合併進
    同一本帳，而合併之後沒有人分得出哪一行是哪一次跑的。

    而且撞號不只是機率問題：`NOVA_RUN_ID` 只驗格式不驗歸屬
    （`帳本.py` 的 `新執行識別碼`），一個殘留在環境裡的值就會讓每一次執行
    都用同一個檔名——那是必然路徑，不是碰運氣。
    """
    with 開帳本(tmp_path, 執行識別碼="r") as 帳:
        帳.記一筆(事件(種類=事件種類.呼叫開始))

    with pytest.raises(FileExistsError, match="r.jsonl"), 開帳本(tmp_path, 執行識別碼="r"):
        pass

    # 第一份的證據原封不動——連「開了又關」都不准動到它。
    assert len((tmp_path / "r.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_開檔失敗要當場炸(tmp_path: Path) -> None:
    """開檔的時候還沒叫過任何模型——這時候停，代價只是重跑一次指令。

    副作用發生**之後**才是 fail-open（見 `test_帳本寫入.py` 的 `Test帳本壞掉`）。
    """
    擋路的 = tmp_path / "擋路的"
    擋路的.write_text("我是檔案不是目錄", encoding="utf-8")
    with pytest.raises(OSError, match="."), 開帳本(擋路的 / "下面", 執行識別碼="r"):
        pass


def test_預設路徑不落在repo裡() -> None:
    """落在工作目錄的話，被 nova 驅動的模型會順手把帳本 commit 進去。

    repo 是 public，而帳本裡有失敗代碼、token 數這些不該進版控的東西。
    """
    目錄 = 預設帳本目錄()
    專案根 = Path(__file__).resolve().parents[2]
    assert 專案根 not in 目錄.parents
    assert 目錄.is_absolute()


#: 寫一筆就自殺。**不能用 `with` 的正常出口**——那會關檔，
#: 關檔本來就會 flush，測不出「每筆都 flush」這件事。
_自殺腳本 = """
import os, signal
from pathlib import Path
from nova.契約.帳本 import 事件, 事件種類
from nova.載體.帳本 import 開帳本
帳管 = 開帳本(Path({目錄!r}), 執行識別碼="被殺")
帳 = 帳管.__enter__()
帳.記一筆(事件(種類=事件種類.呼叫開始, 供應商="codex"))
os.kill(os.getpid(), signal.SIGKILL)
"""


def test_程序被殺掉之前寫的那筆還在(tmp_path: Path) -> None:
    """這支是失敗模型的直接背書：防的是「程序被殺」，靠的是每筆 `flush()`。

    負控：把 `建帳本` 裡的 `串流.flush()` 拿掉，這支會紅——
    SIGKILL 不給程序機會清緩衝區。
    """
    跑 = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _自殺腳本.format(目錄=str(tmp_path))],
        capture_output=True,
        check=False,
    )
    assert 跑.returncode == -9, 跑.stderr.decode()
    行們 = (tmp_path / "被殺.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(行們[0])["family"] == "codex"
