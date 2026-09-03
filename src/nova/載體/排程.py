"""排程到期＝時鐘事件。**產生 launchd 設定，但不安裝。**

時鐘不生工作，它只是去巡一趟——四種事件源收斂成同一個入口
（`nova 巡 --專案 <那棵樹>`），不是各自長一條路。
**要巡哪棵樹一定要明講**：排程站在 daemon 那份 checkout 裡，
靠 cwd 猜的話巡到的會是 daemon 自己那份。

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

**「這份 plist 合不合規」這條知識住在這裡**（`驗plist`），不住在宿主的 hook
腳本裡——住在那邊就測不到，而且換掉宿主就一起消失。
"""

import os
import plistlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nova.契約.觸發 import 喚醒來源
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


#: 排程用的啟動器名字。**ASCII kebab-case**：`pkill`、log 過濾、launchctl
#: 的字串比對都在讀它，中文會出問題（CLAUDE.md 的 ASCII 例外條款）。
#: 形式是命名規範的 `<APP>-<role>`，跟 `APP_ROLE=nova.patrol` 對得起來。
啟動器名 = "nova-patrol"

#: 排程這條線的角色。Label、執行檔名、`APP_ROLE`、log 檔名都用它，
#: 對得起來的時候 `launchctl list | grep patrol` 跟活動監視器說的是同一件事。
_角色 = "patrol"


def 確保啟動器在(直譯器: Path) -> Path:
    """把直譯器硬連結成一個看得出是誰的名字，回傳那個路徑。

    **程序名稱由 kernel 在 `exec` 當下依真正執行的那個二進位決定，事後改不了。**
    `.venv/bin/nova` 是 shebang 文字檔，kernel 執行的是直譯器，所以
    活動監視器顯示的是 `python3.13`——實測 2026-08-30，macOS 15。
    一台機器上跑幾個 python 工具就會出現一排分不出誰是誰的 `python3`。

    **硬連結不是複製**：同一份 inode，升級直譯器時不會留下一份舊的在跑。
    而且它必須留在 `.venv/bin/` 裡——Python 是從 `sys.executable` 的上一層
    找 `pyvenv.cfg`，搬出去就找不到 venv，`import nova` 當場炸。

    **每次都對一次 inode**：直譯器升級之後 `.venv/bin/python` 指到新的那份，
    舊的硬連結還在——於是排程拿舊直譯器配新套件跑，而錯誤只出現在
    launchd 的 log 裡，沒有人會看到。不一樣就換掉。
    """
    # **一定要自己 `resolve()`，不要靠 `os.link` 跟著符號連結走。**
    # `.venv/bin/python` 是符號連結，而「硬連結會不會跟著它走」**兩個平台不一樣**
    # ——macOS 上會，Linux 上不會（2026-08-30 CI 實測：把這行拿掉之後
    # `test_跟著符號連結走到真的那份` 在 macOS 全綠、在 Linux 當場紅）。
    # 不跟著走的話連出來的是「指向符號連結的硬連結」，直譯器一升級就整個斷掉。
    真身 = 直譯器.resolve()
    落點 = 直譯器.parent / 啟動器名
    if 落點.exists() and 落點.stat().st_ino == 真身.stat().st_ino:
        return 落點
    落點.unlink(missing_ok=True)
    落點.hardlink_to(真身)
    return 落點


#: 不鎖。做成模組層的單例是因為 `排程預算()` 不准寫在參數預設值裡（ruff B008）——
#: 它是 frozen 的所以其實安全，但那條規則沒有例外，而名字讀起來也更清楚。
不鎖 = 排程預算()

#: **跑排程的那支 nova 自己住的那份 checkout**——排程醒來就站這裡。
#: `<這份 checkout>/src/nova/載體/排程.py` 往上數三層就是它。
#:
#: 為什麼是這個而不是 `Path.cwd()` 或空的：排程站的地方由「daemon 那份
#: 安裝」決定，不由「印 plist 的人當下站在哪」決定。空的預設會序列化成
#: `"."`（＝launchd 自己的 cwd，誰都說不準是哪裡），而且剛好繞過
#: `_擋下裝不得的跑法` 那道守門——看起來合法，裝下去才發現不是。
daemon那份checkout = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class 怎麼跑:
    """時鐘要跑哪個執行檔、用什麼 `PATH`、站在哪裡跑。

    **綁在一起是有原因的**：少了任何一個，另一個就沒意義——
    指到對的執行檔但 `PATH` 不對，判準照樣跑不起來，而那個
    `FileNotFoundError` 會被當成「測試紅了」（實測 2026-08-30，
    一次醒來燒掉 997,031 token）。拆成幾個參數就一定有人只給一個。
    """

    執行檔: Path
    #: launchd 不跑登入 shell，不帶就是 `/usr/bin:/bin:/usr/sbin:/sbin`。
    路徑環境: str = ""
    #: 排程醒來站的地方。**要是 daemon 那份 checkout，不准是要被巡的那棵樹**
    #: ——主工作區正是最容易壞的地方，站在裡面就跟它一起壞。
    #: 預設是跑排程的那支 nova 自己住的那份 checkout（見 `daemon那份checkout`），
    #: 所以沒給也是一個真的、絕對的、存在的目錄，不是 `"."`。
    工作目錄: Path = daemon那份checkout


def _擋下裝不得的跑法(跑法: 怎麼跑, 專案: Path) -> None:
    """印出來以前就炸掉那兩種「裝下去才會發現」的壞法。

    **工作目錄不准等於 `專案`、也不准在它底下**：排程醒來就會站在
    要被巡的那棵樹裡，那棵樹壞掉（rebase 到一半、被 `git clean` 掃過）
    的那一天它跟著壞，而那正是最需要它還活著的時刻。

    **執行檔名要看得出是誰**：印一份裝下去看不出是誰的 plist，比不印更糟
    ——裝了之後使用者在「登入項目」看到一個叫 `uv` 的東西，而且不知道怎麼關掉。
    """
    if 跑法.工作目錄 == 專案 or 專案 in 跑法.工作目錄.parents:
        訊息 = (
            f"排程的工作目錄不准在 {專案} 底下（給的是 {跑法.工作目錄}）："
            "醒來就站在要被巡的那棵樹裡，那棵樹壞掉的時候排程跟著壞。"
            "要指到另一份 checkout（daemon 自己那份）"
        )
        raise ValueError(訊息)
    if 不能當執行檔(跑法.執行檔):
        訊息 = (
            f"{跑法.執行檔.name} 不能當排程的執行檔："
            "「登入項目與延伸功能」只顯示執行檔名，寫直譯器或代跑工具的話"
            "看不出是誰的 job。要指到 nova 自己那支"
        )
        raise ValueError(訊息)


def 排程設定(
    *,
    跑法: 怎麼跑,
    專案: Path,
    狀態根: Path,
    每幾分: int,
    預算: 排程預算 = 不鎖,
) -> str:
    """產生一份 launchd plist。**執行檔名字不對、工作目錄不對就當場炸。**

    為什麼要擋見 `_擋下裝不得的跑法`。
    """
    _擋下裝不得的跑法(跑法, 專案)
    標籤 = 排程標籤(專案)
    log目錄 = 狀態根 / "log"
    設定 = {
        "Label": 標籤,
        # 時鐘不生工作，只是去巡一趟。四種事件源收斂到同一個入口。
        # **要巡哪棵樹一定要明講**（`--專案`）：工作目錄在 daemon checkout，
        # 靠 cwd 猜的話巡的就是 daemon 自己那份。
        # **預算旗標要進得了這裡**：預算鎖存在的理由就是時鐘自己跑的那幾百次。
        # 寫死的話，人在終端機打的每一次都擋得住，排程一次都擋不住。
        # 每一格是獨立的字串——`ProgramArguments` 不經過 shell，
        # `"--預算token 500000"` 塞成一格會變成一個沒人認得的旗標，
        # 而報錯是在 launchd 的 log 裡，沒有人會看到。
        # **第一格是硬連結出來的專用直譯器**，不是 console script——
        # console script 是 shebang 文字檔，kernel 執行的是直譯器，
        # 活動監視器就會顯示 `python3.13`（見 `確保啟動器在`）。
        "ProgramArguments": [
            str(跑法.執行檔),
            "-m",
            "nova",
            "巡",
            "--專案",
            str(專案),
            "--喚醒來源",
            喚醒來源.排程到期.value,
            *預算.旗標(),
        ],
        # **不是 `專案`**：見 `_擋下裝不得的跑法` 那條 raise。
        "WorkingDirectory": str(跑法.工作目錄),
        "StartInterval": 每幾分 * _一分鐘幾秒,
        "RunAtLoad": False,
        # 名字由 kernel 決定、事後改不了，所以識別靠環境變數。
        #
        # **`PATH` 一定要帶。** launchd 不跑登入 shell，程序拿到的是
        # `/usr/bin:/bin:/usr/sbin:/sbin`——而 `uv` 住在 `~/.local/bin`。
        # 少了它，預設判準 `uv run pytest -q` 在排程底下根本跑不起來。
        # 實測 2026-08-30：那個 FileNotFoundError 被當成「測試紅了」，
        # 工作流回去再實作一次，一次醒來燒掉 997,031 token。
        # 由 `test_排程的環境跑得起預設判準` 背書（判準三：要驗可達性）。
        "EnvironmentVariables": {"APP_ROLE": f"nova.{_角色}", "PATH": 跑法.路徑環境},
        # **log 落在狀態目錄不落在專案裡**：它也是會被餵回模型的東西，
        # 落在工作目錄裡執行者就摸得到。
        "StandardOutPath": str(log目錄 / f"{標籤}.out.log"),
        "StandardErrorPath": str(log目錄 / f"{標籤}.err.log"),
    }
    return plistlib.dumps(設定, sort_keys=True).decode("utf-8")


def 排程標籤(專案: Path) -> str:
    """這個專案的 launchd Label。**只准有這一份。**

    形式是 `com.<APP>.<專案>.<role>`；專案就是 nova 的時候前綴末段跟 APP
    同名，那一段省掉，於是是 `com.nova.patrol`。

    印出來的安裝指令自己說「檔名要跟 Label 一致」，所以呼叫端不准自己再算一次
    `專案.name.lower()`——專案名只要不是現成的小寫 ASCII（有空格、有大寫、有中文），
    兩份就會對不上，而使用者照著做會得到一個 `launchctl load` 不動的檔案。

    小寫 ASCII kebab，空的就退回 `project`。
    """
    名 = _標籤字元.sub("-", 專案.name.lower()).strip("-") or "project"
    if 名 == "nova":
        return f"com.nova.{_角色}"
    return f"com.nova.{名}.{_角色}"


#: Label 的形狀：`com.nova.<段>[.<段>…]`，全小寫 ASCII kebab-case。
_合規的標籤 = re.compile(r"^com\.nova\.[a-z0-9-]+(\.[a-z0-9-]+)*$")


def 驗plist(
    設定文字: str,
    檔名: str,
    *,
    家目錄: Path,
    會消失的前綴: tuple[str, ...],
) -> tuple[str, ...]:
    """這份 plist 裝下去會不會出事。回空 tuple 代表沒問題。

    五段各守一種**裝下去才會發現**的壞法：執行檔名看不出是誰、不是絕對路徑、
    不存在或沒有 `+x`、放在開機後會消失的位置、Label 不合規或跟檔名對不上。
    每一條訊息都要照著做得完。

    **`家目錄` 與 `會消失的前綴` 是參數不是常數**：寫死的話這條規則只能在真的
    家目錄底下驗，於是永遠沒有測試看得到它——而它本來就是為了「從宿主的 hook
    搬進 nova」才存在的（宿主那支把 `/var/folders` 判成會消失，而 `tmp_path`
    就在那裡）。
    """
    要驗的 = _挖出標籤與執行檔(設定文字)
    if 要驗的 is None:
        return ()
    標籤, 執行檔 = 要驗的
    return (
        *_驗執行檔名(執行檔),
        *_驗執行檔落點(執行檔, 會消失的前綴=會消失的前綴),
        *_驗標籤(標籤, 檔名, 執行檔=執行檔, 家目錄=家目錄),
    )


def _挖出標籤與執行檔(設定文字: str) -> tuple[str, str] | None:
    """從 plist 文字挖出五段要看的那兩個欄位。**不是 launchd job 就回 `None`。**

    讀不成 plist、或讀成了但沒有 `Label`，那就不是我們要管的東西——
    不管比亂報一條做不到的訊息好。
    """
    try:
        設定: Any = plistlib.loads(設定文字.encode("utf-8"))
    except Exception:  # noqa: BLE001 —— 讀不成 plist 就不是 launchd job，不管
        return None
    if not isinstance(設定, dict) or "Label" not in 設定:
        return None
    參數 = 設定.get("ProgramArguments") or []
    執行檔 = str(設定.get("Program") or (參數[0] if 參數 else ""))
    return str(設定.get("Label", "")), 執行檔


def _驗執行檔名(執行檔: str) -> list[str]:
    """一：執行檔名看得出是誰嗎——「登入項目與延伸功能」只顯示這個名字。"""
    if not 執行檔:
        return ["沒有 Program 也沒有 ProgramArguments，launchd 不知道要跑什麼"]
    路徑 = Path(執行檔)
    if 不能當執行檔(路徑):
        訊息 = (
            f"執行檔名 {路徑.name} 看不出是誰的 job："
            "「登入項目與延伸功能」與活動監視器只顯示執行檔名。"
            "改成直接指向 <app>-<role>（例：nova-patrol）那支可執行檔"
        )
        return [訊息]
    return []


def _會消失(路徑: Path, 會消失的前綴: tuple[str, ...]) -> bool:
    """執行檔是不是就在某個「會消失的目錄」裡。

    比對切在**路徑分段**上：前綴給的是一個目錄，所以只有「就是它、或在它底下」
    才算；`/tmpfs-checkout` 這種名字同開頭的鄰居是另一個地方，抓了就是叫人白搬
    一支好好的執行檔。前綴補不補結尾斜線由這裡吸收，呼叫端只要給目錄。
    """
    for 前綴 in 會消失的前綴:
        目錄 = Path(前綴.rstrip("/") or "/")
        if 路徑 == 目錄 or 目錄 in 路徑.parents:
            return True
    return False


def _驗執行檔落點(執行檔: str, *, 會消失的前綴: tuple[str, ...]) -> list[str]:
    """二、三、四：絕對路徑、在且可執行、不會消失。"""
    if not 執行檔:
        return []
    if not 執行檔.startswith("/"):
        return ["Program／ProgramArguments[0] 必須是絕對路徑（launchd 沒有你的 PATH）"]
    毛病: list[str] = []
    路徑 = Path(執行檔)
    if not 路徑.exists():
        毛病.append(f"執行檔不存在：{執行檔}（job 會靜默失敗，但 BTM 已經留下項目）")
    elif not os.access(路徑, os.X_OK):
        毛病.append(f"執行檔沒有執行權限：chmod +x {執行檔}")
    if _會消失(路徑, 會消失的前綴):
        毛病.append(
            f"執行檔放在開機後會消失的位置（{路徑.parent}）："
            "重開機後 job 永久壞掉，而背景項目還在。放到不會被清掉的地方"
        )
    return 毛病


def _驗標籤(標籤: str, 檔名: str, *, 執行檔: str, 家目錄: Path) -> list[str]:
    """五：Label 合不合規、跟檔名對不對得起來。

    `com.nova.` 前綴只對自己寫的 job 強制——執行檔在家目錄底下的才算，
    套件管理器裝的沿用它自己的 Label，不干涉。
    """
    毛病: list[str] = []
    自己的 = 執行檔.startswith(f"{家目錄}/") if 執行檔 else True
    if 自己的 and not _合規的標籤.match(標籤):
        毛病.append(f"Label {標籤} 不合規：要是 com.nova.<段>[.<段>]，全小寫 ASCII kebab-case")
    if 檔名.endswith(".plist") and 檔名.removesuffix(".plist") != 標籤:
        毛病.append(f"Label {標籤} 跟檔名 {檔名} 對不上，事後找不到是哪一支。檔名應為 {標籤}.plist")
    return 毛病
