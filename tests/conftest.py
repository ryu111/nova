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
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:  # pragma: no cover - 只給型別檢查看
    from nova.載體.閘 import 規則

    #: `挖pytest命令列` 這支 fixture 的形狀。
    _挖命令列型 = Callable[[規則], tuple[str, ...]]

# `nova` 只准在 TYPE_CHECKING 底下 import：conftest 一 import 就等於每個 pytest
# 行程都載入了半個 `nova`，`tests/負控/` 那把刀量覆蓋率時會把那些 import 時執行的
# 行算成「該紅的測試有走到」，WRONG_TEST 就變成 SURVIVED，負控整個失效。


@pytest.fixture
def 挖pytest命令列() -> "_挖命令列型":
    """把 `_外部指令` 包出來的閉包裡那條 pytest 命令列挖出來。

    做成 fixture 不做成可以 import 的函式：跨檔 import 會讓同一個檔被算成
    `conftest` 與 `tests.conftest` 兩個模組（見本檔開頭）。

    只寫這一份：`test_規則表.py` 與 `test_負控只跑一次.py` 都要讀命令列，
    各寫一份的話 `_外部指令` 的內部形狀一改就得有人記得兩處都改。
    """

    def 挖(條: "規則") -> tuple[str, ...]:
        閉包 = getattr(條.檢查, "__closure__", None)
        assert 閉包 is not None, f"{條.代碼} 不是包出來的外部指令，這支 fixture 要改寫"
        命令 = next(
            (
                格.cell_contents
                for 格 in 閉包
                if isinstance(格.cell_contents, tuple)
                and 格.cell_contents
                and 格.cell_contents[0] == "pytest"
            ),
            None,
        )
        assert isinstance(命令, tuple), f"{條.代碼} 找不到 pytest 命令列"
        return tuple(str(項) for 項 in 命令)

    return 挖


@pytest.fixture(autouse=True)
def 不准摸到真的CLI(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """沒標 `真cli` 的測試不准解析到真的執行檔。**autouse，沒有例外。**

    這是被一個真缺陷逼出來的：`--工作` 的互斥檢查一旦失效，
    測試就會往下走到真的建腦——`reasoning` 那條會真的叫 sol。
    實測拿掉那個檢查跑兩支測試要 22.5 秒，而且出了網路、燒了 token。
    **測試在防護退化時的行為也是行為**，不能只看它平常綠不綠。

    擋的是 `找執行檔`（找不到就往 PATH 撈的那條路），不是 `--執行檔`——
    測試本來就該自己注入假 CLI；忘了注入才會掉到這裡。
    """
    if request.node.get_closest_marker("真cli"):
        return

    def 擋(家: str, **_: object) -> Path:
        訊息 = f"測試不准去找真的 {家}：要嘛自己給執行檔，要嘛標 @pytest.mark.真cli"
        raise FileNotFoundError(訊息)

    monkeypatch.setattr("nova.載體.模型.轉接.找執行檔", 擋)


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
#:
#: **`env` 也記下來**：載體交給子程序什麼環境是行為的一部分（載入秘密、`APP_ROLE`、
#: 把各家自帶的載體關到最小），而那些只有從子程序這一側看得到。
假CLI內容 = f"""#!{sys.executable}
import json, os, pathlib, sys
名 = pathlib.Path(sys.argv[0]).name.replace("fake-", "").upper()
紀錄 = os.environ.get(f"NOVA_FAKE_{{名}}_RECORD")
if 紀錄:
    pathlib.Path(紀錄).write_text(
        json.dumps({{"argv": sys.argv[1:], "who": sys.argv[0], "env": dict(os.environ)}}),
        encoding="utf-8")
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


def pytest_addoption(parser: pytest.Parser) -> None:
    """`--登記檔 <相對路徑>`（可重複）：只跑這幾個登記模組登記的負控刀。

    **只能寫在這一份 conftest**：`addoption` 只認 initial conftest，
    寫在 `tests/負控/conftest.py` 的話在別的呼叫路徑上會靜靜失效。

    走 pytest 選項不走 nodeid、也不走 `-k`：pytest 會把非 ASCII 的參數 id
    轉義成十六進位，點名等於要載體自己複製一份 pytest 的轉義規則。
    """
    parser.addoption(
        "--登記檔",
        action="append",
        default=[],
        metavar="路徑",
        help="只跑這個登記模組（tests/負控/登記們/<主題>.py）登記的負控刀；可重複",
    )


def _這一項掛的刀(項: pytest.Item) -> object | None:
    """這個 test item 是不是一把登記負控刀？是的話回那一筆 `變異`。

    用參數上的屬性認，不 import `tests.負控.登記`：那個模組一載入就會把
    `登記們/` 底下每個模組跟著載進來，而 conftest 是每個 pytest 行程都會執行的。
    """
    參數們 = getattr(getattr(項, "callspec", None), "params", {})
    一筆 = 參數們.get("一筆")
    return 一筆 if hasattr(一筆, "識別") and hasattr(一筆, "來源") else None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """下了 `--登記檔` 時，只留下那幾個登記模組來的刀。

    沒下選項就整個不作用——負控 runner 跑基線與該紅測試時不會下這個選項，
    所以下面那行 `nova` 的 import 在刀的行程裡走不到（conftest 一 import 就載入
    半個 nova 會毀掉覆蓋率判定，見本檔開頭）。
    """
    指名 = tuple(config.getoption("登記檔") or ())
    if not 指名:
        return

    from nova.載體.本線負控 import 判定選到的刀, 挑出本線動過的刀

    帶刀的 = [(項, 刀) for 項 in items if (刀 := _這一項掛的刀(項)) is not None]
    選到 = 挑出本線動過的刀([刀 for _, 刀 in 帶刀的], 指名)
    留下的 = {id(刀) for 刀 in 選到}
    丟掉 = [項 for 項, 刀 in 帶刀的 if id(刀) not in 留下的]
    if 丟掉:
        config.hook.pytest_deselected(items=丟掉)
        items[:] = [項 for 項 in items if 項 not in 丟掉]

    通過, 摘要 = 判定選到的刀(指名, 選到)
    報告器 = config.pluginmanager.get_plugin("terminalreporter")
    if 報告器 is not None:
        報告器.write_line(摘要)
    if not 通過:
        # 指名了檔卻一把都選不到＝fail-closed 的紅，不是「沒事做」的綠。
        raise pytest.UsageError(摘要)


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
