"""排程到期＝時鐘事件。**產生 launchd 設定，但不安裝。**

時鐘不生工作，它只是把收件匣撈起來——四種事件源收斂成同一個入口
（`nova 工作流 --從收件匣`），不是各自長一條路。

## 為什麼只印不裝

`launchctl load` 下去之後，macOS 的 BTM（背景項目管理）就會留紀錄，
`unload` 也清不乾淨。那是使用者系統上的狀態，不是 nova 的——
跟「不准自動改使用者的設定檔」同一條界線。

## 命名照 bg-process-naming

`ProgramArguments[0]` **不准是直譯器或代跑工具**。寫成 `["/bin/bash", "跑.sh"]`
或 `["uv", "run", "nova", …]` 的話，「登入項目與延伸功能」與 macOS 的背景項目
通知都只會顯示 `bash`／`uv`，完全看不出是誰的 job——而沒有可辨識名稱的
background item 一旦 load 下去就清不乾淨。

`APP_ROLE` 一定要帶：程序名由 kernel 在 exec 當下依執行檔路徑決定、事後改不了，
所以識別要靠環境變數不要靠名字。
"""

import plistlib
import re
from dataclasses import dataclass
from pathlib import Path

from nova.載體.預算 import 上限 as 預算上限

_一分鐘幾秒 = 60

#: 這些名字當 `ProgramArguments[0]` 一律不接受——顯示出來都不是你的名字。
#: 三類：直譯器、代跑工具、通用廢名。
_不准的執行檔名 = frozenset(
    {
        # 直譯器
        "sh",
        "bash",
        "zsh",
        "node",
        "bun",
        "deno",
        "python",
        "python3",
        "ruby",
        "perl",
        "php",
        "java",
        "swift",
        "osascript",
        # 代跑工具
        "npx",
        "bunx",
        "npm",
        "pnpm",
        "yarn",
        "uv",
        "uvx",
        "pipx",
        "cargo",
        "go",
        "make",
        "just",
        "docker",
        # 包裝器
        "nohup",
        "env",
        "sudo",
        "nice",
        "timeout",
        "caffeinate",
        "arch",
        "open",
        "script",
        "setsid",
        # 通用廢名
        "run",
        "start",
        "main",
        "app",
        "server",
        "daemon",
        "agent",
        "worker",
        "index",
        "cli",
    }
)

#: Label 只留這些字元。CJK 會讓 `launchctl`、`pkill`、log 過濾的字串比對出問題。
_標籤字元 = re.compile(r"[^a-z0-9-]+")


def 不能當執行檔(路徑: Path) -> bool:
    """這個執行檔名字撐不撐得起「看得出是誰」。"""
    名 = 路徑.name.lower()
    return 名 in _不准的執行檔名 or 名.startswith("python3.")


@dataclass(frozen=True, slots=True)
class 排程預算:
    """時鐘那條路徑要帶的跨執行預算。**上限跟窗口綁在一起**——

    光給窗口不給上限的話那個旗標一點作用都沒有，而帶著它會讓人以為有鎖。
    """

    上限: 預算上限 = 預算上限()
    幾小時: float | None = None

    def 旗標(self) -> list[str]:
        """攤成 `ProgramArguments` 的格子。沒設上限就是空的——**預設關閉**。"""
        旗: list[str] = []
        if self.上限.token is not None:
            旗 += ["--預算token", str(self.上限.token)]
        if self.上限.美金 is not None:
            旗 += ["--預算美金", str(self.上限.美金)]
        if 旗 and self.幾小時 is not None:
            旗 += ["--預算幾小時", str(self.幾小時)]
        return 旗


#: 不鎖。做成模組層的單例是因為 `排程預算()` 不准寫在參數預設值裡（ruff B008）——
#: 它是 frozen 的所以其實安全，但那條規則沒有例外，而名字讀起來也更清楚。
不鎖 = 排程預算()


def 排程設定(*, 執行檔: Path, 專案: Path, 狀態根: Path, 每幾分: int, 預算: 排程預算 = 不鎖) -> str:
    """產生一份 launchd plist。**執行檔名字不對就當場炸。**

    印出一份裝下去會看不出是誰的 plist，比不印更糟——裝了之後
    使用者在「登入項目」看到一個叫 `uv` 的東西，而且不知道怎麼關掉。
    """
    if 不能當執行檔(執行檔):
        訊息 = (
            f"{執行檔.name} 不能當排程的執行檔："
            "「登入項目與延伸功能」只顯示執行檔名，寫直譯器或代跑工具的話"
            "看不出是誰的 job。要指到 nova 自己那支"
        )
        raise ValueError(訊息)
    標籤 = 排程標籤(專案)
    log目錄 = 狀態根 / "log"
    設定 = {
        "Label": 標籤,
        # 時鐘不生工作，只是把收件匣撈起來。四種事件源收斂到同一個入口。
        # **預算旗標要進得了這裡**：預算鎖存在的理由就是時鐘自己跑的那幾百次。
        # 寫死的話，人在終端機打的每一次都擋得住，排程一次都擋不住。
        # 每一格是獨立的字串——`ProgramArguments` 不經過 shell，
        # `"--預算token 500000"` 塞成一格會變成一個沒人認得的旗標，
        # 而報錯是在 launchd 的 log 裡，沒有人會看到。
        "ProgramArguments": [str(執行檔), "工作流", "--從收件匣", *預算.旗標()],
        "WorkingDirectory": str(專案),
        "StartInterval": 每幾分 * _一分鐘幾秒,
        "RunAtLoad": False,
        # 名字由 kernel 決定、事後改不了，所以識別靠環境變數。
        "EnvironmentVariables": {"APP_ROLE": "nova.inbox"},
        # **log 落在狀態目錄不落在專案裡**：它也是會被餵回模型的東西，
        # 落在工作目錄裡執行者就摸得到。
        "StandardOutPath": str(log目錄 / f"{標籤}.out.log"),
        "StandardErrorPath": str(log目錄 / f"{標籤}.err.log"),
    }
    return plistlib.dumps(設定, sort_keys=True).decode("utf-8")


def 排程標籤(專案: Path) -> str:
    """這個專案的 launchd Label。**只准有這一份。**

    印出來的安裝指令自己說「檔名要跟 Label 一致」，所以呼叫端不准自己再算一次
    `專案.name.lower()`——專案名只要不是現成的小寫 ASCII（有空格、有大寫、有中文），
    兩份就會對不上，而使用者照著做會得到一個 `launchctl load` 不動的檔案。

    小寫 ASCII kebab，空的就退回 `project`。
    """
    名 = _標籤字元.sub("-", 專案.name.lower()).strip("-")
    return f"com.nova.{名 or 'project'}"
