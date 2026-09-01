"""`nova 排程` 產生的 launchd 設定。

**nova 產生，人安裝。** 自動 `launchctl load` 下去的話，BTM（背景項目管理）
會留紀錄，unload 也清不乾淨——那是使用者系統上的狀態，不是 nova 的。
所以這一格只印出來。

命名照 `~/.claude/skills/bg-process-naming`：
- Label `com.nova.<專案>`，全小寫 ASCII kebab
- `ProgramArguments[0]` **不准是直譯器或代跑工具**（`bash`、`python3`、`uv`…）
  ——「登入項目與延伸功能」只會顯示那個名字，完全看不出是誰的 job
- 帶 `APP_ROLE`，因為名字由 kernel 決定而環境變數不會

純字串，不碰硬碟，所以住單元層。
"""

import plistlib
from pathlib import Path

import pytest

from nova.載體.排程 import 不能當執行檔, 怎麼跑, 排程設定, 排程預算
from nova.載體.預算 import 上限 as 預算上限


def _設定(
    *,
    預算token: int | None = None,
    預算美金: float | None = None,
    預算幾小時: float | None = None,
    **改: object,
) -> str:
    """預算那三個攤平著給。

    測試裡讀起來才是「使用者會打的那三個旗標」。
    """
    參 = {
        "跑法": 怎麼跑(
            執行檔=Path("/Users/someone/nova/.venv/bin/nova-inbox"),
            路徑環境="/usr/bin:/bin",
        ),
        "專案": Path("/Users/someone/nova"),
        "狀態根": Path("/Users/someone/.local/state/nova"),
        "每幾分": 15,
        "預算": 排程預算(上限=預算上限(token=預算token, 美金=預算美金), 幾小時=預算幾小時),
    }
    參.update(改)
    return 排程設定(**參)  # type: ignore[arg-type]


def test_是合法的plist() -> None:
    讀回來 = plistlib.loads(_設定().encode("utf-8"))

    assert 讀回來["Label"].startswith("com.nova.")


def test_多久跑一次照給的分鐘數() -> None:
    讀回來 = plistlib.loads(_設定(每幾分=30).encode("utf-8"))

    assert 讀回來["StartInterval"] == 30 * 60


def test_跑的是nova不是直譯器() -> None:
    """**這一條是命名規範的核心。**

    寫成 `["/bin/bash", "跑.sh"]` 的話，「登入項目與延伸功能」與 macOS 的
    背景項目通知都只顯示 `bash`，完全看不出是誰的 job。
    """
    參數 = plistlib.loads(_設定().encode("utf-8"))["ProgramArguments"]

    # 名字是 `nova-inbox`（硬連結出來的專用直譯器）不是 `nova`——
    # console script 是 shebang 文字檔，kernel 執行的還是直譯器，
    # 活動監視器就會顯示 `python3`。見 `確保啟動器在`。
    assert Path(參數[0]).name.startswith("nova")
    assert not 不能當執行檔(Path(參數[0]))
    assert Path(參數[0]).is_absolute()


def test_跑的是從收件匣那條路() -> None:
    """排程不生工作，它只是把收件匣撈起來——**時鐘＝事件，收斂到同一個入口**。"""
    參數 = plistlib.loads(_設定().encode("utf-8"))["ProgramArguments"]

    assert "工作流" in 參數
    assert "--從收件匣" in 參數
    assert "--用" not in 參數, "排程不准用 --用 蓋掉依階段查派工表的路徑"


def test_帶著APP_ROLE() -> None:
    """名字由 kernel 在 exec 當下決定，環境變數不會——識別要靠它。"""
    環境 = plistlib.loads(_設定().encode("utf-8"))["EnvironmentVariables"]

    assert 環境["APP_ROLE"] == "nova.inbox"


def test_log落在狀態目錄不落在專案裡() -> None:
    """**log 也是會被餵回模型的東西**——落在工作目錄裡執行者就摸得到。"""
    讀回來 = plistlib.loads(_設定().encode("utf-8"))

    for 鍵 in ("StandardOutPath", "StandardErrorPath"):
        assert str(Path(讀回來[鍵]).parent) != "/Users/someone/nova"
        assert 讀回來[鍵].startswith("/Users/someone/.local/state/nova")


def test_Label是ASCII() -> None:
    """CJK 會讓 `launchctl`、`pkill`、log 過濾的字串比對出問題。"""
    標籤 = plistlib.loads(_設定(專案=Path("/Users/someone/我的專案")).encode("utf-8"))["Label"]

    assert 標籤.isascii(), 標籤
    assert 標籤.startswith("com.nova.")


@pytest.mark.parametrize(
    "名",
    ["bash", "sh", "zsh", "python3", "node", "uv", "uvx", "npx", "env", "nohup", "run"],
)
def test_擋得住拿直譯器或代跑工具當執行檔(名: str) -> None:
    """**這支是把關器不是說明。**

    `uv run nova` 很順手，但 plist 裡寫 `uv` 的話背景項目只會顯示 uv。
    通用廢名（`run`、`start`、`main`）同理——顯示出來都不是你的名字。
    """
    assert 不能當執行檔(Path(f"/somewhere/{名}"))


def test_nova自己可以當執行檔() -> None:
    """**這支防的是擋過頭。** 擋掉全部就沒有東西可以排程了。"""
    assert not 不能當執行檔(Path("/Users/someone/nova/.venv/bin/nova"))


def test_執行檔名字不對就當場炸() -> None:
    """印出一份裝下去會看不出是誰的 plist，比不印更糟。"""
    with pytest.raises(ValueError, match="uv"):
        _設定(跑法=怎麼跑(執行檔=Path("/opt/homebrew/bin/uv")))


class Test預算旗標要進得了排程:
    """**預算鎖存在的理由就是排程。**

    `nova 問` 一次只發一個請求，單看那次永遠沒超支——一天兩百次是另一回事，
    而那正是時鐘自己跑之後會發生的事。

    `ProgramArguments` 寫死的話，鎖剛好在它存在的理由上不存在：
    人在終端機打的每一次都擋得住，時鐘自己跑的那幾百次一次都擋不住。
    """

    def test_不給預算時不長出旗標(self) -> None:
        """**預設關閉**：「我主要是要看帳，但不要讓帳去把流程關閉。」"""
        參數 = plistlib.loads(_設定().encode("utf-8"))["ProgramArguments"]

        assert not [旗 for 旗 in 參數 if 旗.startswith("--預算")]

    def test_token上限會進到指令裡(self) -> None:
        參數 = plistlib.loads(_設定(預算token=500_000).encode("utf-8"))["ProgramArguments"]

        assert "--預算token" in 參數
        assert 參數[參數.index("--預算token") + 1] == "500000"

    def test_成本上限會進到指令裡(self) -> None:
        參數 = plistlib.loads(_設定(預算美金=5.0).encode("utf-8"))["ProgramArguments"]

        assert "--預算美金" in 參數
        assert float(參數[參數.index("--預算美金") + 1]) == 5.0

    def test_有給上限才帶窗口(self) -> None:
        """光給窗口不給上限的話，那個旗標一點作用都沒有。

        **帶著它會讓人以為有鎖。**
        """
        沒鎖 = plistlib.loads(_設定(預算幾小時=6.0).encode("utf-8"))["ProgramArguments"]
        有鎖 = plistlib.loads(_設定(預算token=100, 預算幾小時=6.0).encode("utf-8"))[
            "ProgramArguments"
        ]

        assert "--預算幾小時" not in 沒鎖
        assert 有鎖[有鎖.index("--預算幾小時") + 1] == "6.0"

    def test_每一格都是獨立的字串(self) -> None:
        """**`ProgramArguments` 不經過 shell。**

        `"--預算token 500000"` 塞成一格的話，argparse 會拿到一個叫
        「--預算token 500000」的旗標然後當場報用法錯誤——而那是在 launchd 的
        log 裡，沒有人會看到。
        """
        參數 = plistlib.loads(_設定(預算token=500_000).encode("utf-8"))["ProgramArguments"]

        assert all(" " not in 格 for 格 in 參數), 參數
