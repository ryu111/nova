"""收件檔出現＝一次派工。**檔案就是事件。**

路線圖觸發層那四格裡，只有這一格的副標寫著「唯一的橋」——因為檔案是唯一一種
**不綁任何一家 LLM、不綁任何一個宿主、`ls` 就看得到佇列**的事件形式。
排程到期與 MCP 派票最後都該收斂成「往收件匣丟一個檔」，不是各自長一條路。

## 為什麼收件匣不能住在工作目錄裡

理由跟進度檔同一條，但更嚴重。進度檔放錯只是讓模型替未來的自己種話；
**收件匣放錯是讓執行者自己派工給自己**——一個能寫工作目錄的模型
可以無限次觸發自己，而且每一次看起來都像是使用者丟的。

所以它跟帳本、已處理住在一起：`$XDG_STATE_HOME/nova/專案/<識別>/收件`。
歸屬是索引問題，不是存放位置問題。

## 三個狀態，三個目錄

```
收件/            還沒有人動的
收件/處理中/     收下了，還沒收尾  ← 程序被殺掉的話會留在這裡，那是誠實
已處理/          做完了，旁邊就是那次的成果 JSON
```

**收下＝把檔案移走**，靠 `rename` 的原子性宣告所有權：同一個檔只有一個
`rename` 會成功，另一個拿到 `FileNotFoundError` 然後去看下一件。
少了這一步，兩個程序會把同一件工作做兩次，而且看起來完全正常。
"""

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex

from nova.載體.帳本 import 專案識別
from nova.載體.狀態 import 狀態根目錄
from nova.載體.遮罩 import 遮罩

_處理中 = "處理中"

#: 誰造了這個收件檔。**ASCII：跨程序 semantic id**，會流進成果帳的 `source` 欄位被 grep。
#: 對應路線圖觸發層那四格；現在只有前兩個生得出來。
你敲, 檔案, 時鐘, 協定 = "typed", "file", "schedule", "mcp"
_認得的來源 = frozenset({你敲, 檔案, 時鐘, 協定})

#: 檔名開頭的時戳。**跟帳本的執行識別碼同一個格式**——「`ls` 就是時序」
#: 靠的是它，兩邊走散的話先進先出會靜默壞掉。
_檔名時戳 = "%Y%m%dT%H%M%SZ"

#: 檔名裡放不進去的字。題目可能有斜線、換行、引號。
_檔名不要的 = re.compile(r"[^\w]+", re.UNICODE)

#: 題目擷取幾個字當標籤。太長的檔名在 `ls` 裡會換行，反而看不出佇列。
_標籤幾個字 = 24

#: 檔名至少要有「時戳-來源」兩段才判得出來源。
_最少幾段 = 2


@dataclass(frozen=True, slots=True)
class 收件單:
    """收下來的一件工作。

    `名稱` 是原始檔名（去掉副檔名），拿來當這次工作的人看得懂的標籤；
    `處理中路徑` 是它現在的位置——完成的時候要從那裡搬走。
    """

    名稱: str
    任務: str
    處理中路徑: Path
    #: 誰造了這個收件檔（`typed`／`file`／…）。**不是「誰醒來把它撈起來」**——
    #: 排程把一個手丟的檔案做掉，那一件的來源仍然是檔案。
    來源: str = 檔案


def 收件目錄(專案: Path | None = None) -> Path:
    """收件匣住哪。跟帳本、已處理是同一個專案資料夾底下的三個目錄。"""
    底 = 狀態根目錄()
    return 底 / "收件" if 專案 is None else 底 / "專案" / 專案識別(專案) / "收件"


def 丟一件(題目: str, *, 來源: str, 目錄: Path | None = None) -> Path:
    """把一句話落成一個收件檔，回傳它的位置。**這是「你敲」變成事件的那一步。**

    檔名長成 `<時戳>-<來源>-<標籤>-<亂碼>.md`：時戳讓 `ls` 就是時序（先進先出
    靠的是它），來源讓成果帳分得出是誰觸發的，亂碼讓同一秒敲兩次不會互相蓋掉。
    """
    if 來源 not in _認得的來源:
        訊息 = f"不認得的來源 {來源!r}——只准 {sorted(_認得的來源)}"
        raise ValueError(訊息)
    內容 = 題目.strip()
    if not 內容:
        訊息 = "題目是空的，派不出工"
        raise ValueError(訊息)
    在哪 = 目錄 or 收件目錄()
    在哪.mkdir(parents=True, exist_ok=True)
    當下 = datetime.now(UTC).strftime(_檔名時戳)
    標籤 = _檔名不要的.sub("-", 內容)[:_標籤幾個字].strip("-") or "工作"
    落點 = 在哪 / f"{當下}-{來源}-{標籤}-{token_hex(3)}.md"
    落點.write_text(內容 + "\n", encoding="utf-8")
    return 落點


def 誰造的(檔名: str) -> str:
    """從檔名讀出來源。讀不出來就是**檔案**——那是手丟進去的，而那也是一種來源。

    判準要夠緊：第一段是時戳、第二段是認得的來源。鬆的話一個剛好叫
    `2026-typed-x.md` 的手丟檔會被標成你敲。
    """
    段 = 檔名.split("-")
    if len(段) < _最少幾段 or 段[1] not in _認得的來源:
        return 檔案
    try:
        datetime.strptime(段[0], _檔名時戳).replace(tzinfo=UTC)
    except ValueError:
        return 檔案
    return 段[1]


def 待處理(目錄: Path | None = None) -> list[Path]:
    """還沒有人動的那些，**先丟的排前面**。

    目錄不存在就是空的——第一次跑的時候本來就還沒有。
    只看檔案不看子目錄：`處理中/` 就住在旁邊，掃到它會變成無限迴圈。
    """
    在哪 = 目錄 or 收件目錄()
    if not 在哪.is_dir():
        return []
    return sorted((路 for 路 in 在哪.iterdir() if 路.is_file()), key=lambda 路: 路.name)


def 收下一件(目錄: Path | None = None) -> 收件單 | None:
    """拿走最前面那一件。沒有東西可拿就回 None。

    **收下＝移走。** 不移走的話，下一輪會再拿到同一件，而副作用會做第二次。
    空白內容的檔案跳過但**不移走**——它派不出工，而移走會讓使用者以為做過了。
    """
    在哪 = 目錄 or 收件目錄()
    for 候選 in 待處理(在哪):
        單 = _搶下來(候選, 在哪)
        if 單 is not None:
            return 單
    return None


def 完成一件(單: 收件單, *, 執行識別碼: str, 已處理: Path) -> Path:
    """把原始請求搬到成果旁邊，回傳它的新位置。

    **成果要對得回請求**：成果帳本說「這件收在護欄」，你要看得到當初丟進來的
    是什麼。兩邊靠執行識別碼配對，跟事件帳本同一條規則。
    """
    已處理.mkdir(parents=True, exist_ok=True)
    落點 = 已處理 / f"{執行識別碼}.收件"
    # **原文也要過遮罩。** 「原文」的意思是「當初丟進來的是什麼」，
    # 不是「連憑證一起留一份」——而 `已處理/` 是躺在磁碟上直到有人刪掉的東西。
    落點.write_text(遮罩(單.任務).文字, encoding="utf-8")
    單.處理中路徑.unlink(missing_ok=True)
    return 落點


def _搶下來(候選: Path, 收件: Path) -> 收件單 | None:
    """用 `rename` 宣告所有權。搶不到（別人先拿走）就回 None。"""
    內容 = _讀得到嗎(候選)
    if 內容 is None or not 內容.strip():
        return None
    處理中 = 收件 / _處理中
    處理中.mkdir(parents=True, exist_ok=True)
    目標 = 處理中 / f"{os.getpid()}-{候選.name}"
    try:
        候選.rename(目標)
    except OSError:
        return None  # 別人先搶到了，或檔案剛好被拿走
    return 收件單(
        名稱=候選.stem,
        任務=內容.strip(),
        處理中路徑=目標,
        來源=誰造的(候選.name),
    )


def _讀得到嗎(路徑: Path) -> str | None:
    """讀不動的不算一件，但**也不移走**——移走等於把使用者丟進來的東西弄丟。"""
    try:
        return 路徑.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
