"""狀態檔：**現在怎麼樣，以及有什麼需要你。**

無人看管跑起來之後，最貴的不是失敗，是**看不出來失敗過**。今天有三種醒來
完全不留痕跡，而它們是排程醒來的絕大多數：

| 醒來的結果 | 事件帳本 | 成果帳 | 看得到嗎 |
|---|---|---|---|
| 做完一件 | 有 | 有 | 看得到 |
| 收件匣是空的 | 無 | 無 | **看不到** |
| 被預算鎖擋下 | 無 | 無 | **看不到** |
| 撞到單例鎖 | 無 | 無 | **看不到** |

所以「排程到底有沒有在跑」這個問題，今天只能去翻 launchd 的 log——
而那份 log 沒有人在看。更糟的是「排程壞掉了」跟「排程好好的但沒事做」
在那裡長得一模一樣。

## 它被覆寫，不是 append

**歷史已經有兩本了**（事件帳本、成果帳）。再開第三本 append-only 的東西
只會跟前兩本漂移，而漂移的那天沒有人會發現。狀態檔答的是**「現在怎麼樣」**：
上次醒來是什麼時候、結果是什麼、佇列上有幾件、幾件卡住了。

需要看歷史就去看那兩本；這裡只有一筆，而且永遠是最新的那筆。

跟 `額度/快取.json` 同一種東西——一個給人與狀態列讀的小 JSON，
所以欄位名走 ASCII（跨程序 schema，CLAUDE.md 的例外條款）。

## 住專案外面

跟進度檔、祕密檔同一條規則：它是下一輪的判斷依據之一，
放在工作目錄裡就等於讓執行者替未來的自己種話。
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from nova.載體.帳本 import 專案識別
from nova.載體.狀態 import 狀態根目錄

#: 檔名。給狀態列讀的，所以路徑可預期。
狀態檔名 = "狀態.json"

#: 醒來的結果。**ASCII：跨程序 semantic id**，狀態列與腳本會 grep 它。
#:
#: **跑起來的那些直接用 `結束代碼` 的值**（`done`／`guardrail`／`aborted`），
#: 不另立一套——成果帳的 `outcome` 就是那組字，兩套詞彙會讓人不知道哪個是真的。
#: 這裡多出來的四個是「根本沒跑起來」的那些，成果帳上一筆都不會有。
做完了, 沒事做, 被預算擋, 在忙, 出不了生, 壞了 = (
    "done",
    "idle",
    "budget",
    "busy",
    "blocked",
    "error",
)

_欄位對照: tuple[tuple[str, str], ...] = (
    ("上次醒來", "last_wake_at"),
    ("上次結果", "last_wake_outcome"),
    ("上次退出碼", "last_wake_exit"),
    ("上次理由", "last_wake_reason"),
    ("上次執行識別碼", "last_run_id"),
)


@dataclass(frozen=True, slots=True)
class 現況:
    """上一次醒來的事實。

    **佇列深度與卡住幾件不在這裡**：那是「現在」的事實，存進檔案就會過期
    （丟五個檔進去，狀態檔還說 0）。`nova 狀態` 當場去數目錄——
    存一份快照等於開第二個真相來源。
    """

    上次醒來: str
    上次結果: str
    上次退出碼: int
    上次理由: str = ""
    上次執行識別碼: str = ""


def 狀態檔(專案: Path) -> Path:
    """這個專案的狀態檔住哪。跟帳本、成果帳、收件匣是同一個專案目錄。"""
    return 狀態根目錄() / "專案" / 專案識別(專案) / 狀態檔名


def 寫下現況(一筆: 現況, *, 路徑: Path) -> None:
    """覆寫。**寫不下去不准把工作結果吃掉**——

    磁碟滿了、權限不對，都只是少一份狀態；把它變成非零退出碼會讓外圈
    以為工作失敗了。跟成果帳同一條。
    """
    try:
        路徑.parent.mkdir(parents=True, exist_ok=True)
        路徑.write_text(
            json.dumps(現況轉字典(一筆), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return


def 讀現況(路徑: Path) -> 現況 | None:
    """讀回來。**沒有、壞掉都回 None**——

    「還沒有狀態」是第一次跑的人的正常狀態，不是錯誤；
    炸掉的話狀態列會一直閃紅。
    """
    try:
        原始 = json.loads(路徑.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(原始, dict):
        return None
    有的 = {內: 原始[外] for 內, 外 in _欄位對照 if 外 in 原始}
    try:
        return 現況(**有的)
    except TypeError:
        return None


def 現況轉字典(一筆: 現況) -> dict[str, object]:
    """落盤用。鍵是 ASCII——讀的人是狀態列腳本，不一定是 python。"""
    return {外: getattr(一筆, 內) for 內, 外 in _欄位對照}


#: 給人看的說法。狀態列與 `nova 狀態` 共用這一份——
#: 兩邊各寫一份的話，同一個結果會有兩種說法，而使用者不知道哪個是真的。
_說法 = {
    做完了: "做完一件",
    "guardrail": "護欄生效（按設計停了，不是壞了）",
    "aborted": "中止（東西壞了）",
    沒事做: "收件匣是空的",
    被預算擋: "被預算鎖擋下",
    在忙: "上一輪還在跑，讓開了",
    出不了生: "開跑前就被擋下",
    壞了: "出錯了",
}


def 形容(結果: str) -> str:
    """結果代碼 → 人看得懂的一句話。不認得的原樣吐回去，不要炸。"""
    return _說法.get(結果, 結果)


def 現在幾點() -> str:
    """UTC ISO 字串。跟帳本的 `ts` 同一個格式，兩邊才對得起來。"""
    return datetime.now(UTC).isoformat()
