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
from dataclasses import dataclass
from pathlib import Path

from nova.載體.帳本 import 專案識別
from nova.載體.狀態 import 狀態根目錄

_處理中 = "處理中"


@dataclass(frozen=True, slots=True)
class 收件單:
    """收下來的一件工作。

    `名稱` 是原始檔名（去掉副檔名），拿來當這次工作的人看得懂的標籤；
    `處理中路徑` 是它現在的位置——完成的時候要從那裡搬走。
    """

    名稱: str
    任務: str
    處理中路徑: Path


def 收件目錄(專案: Path | None = None) -> Path:
    """收件匣住哪。跟帳本、已處理是同一個專案資料夾底下的三個目錄。"""
    底 = 狀態根目錄()
    return 底 / "收件" if 專案 is None else 底 / "專案" / 專案識別(專案) / "收件"


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
    落點.write_text(單.任務, encoding="utf-8")
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
    return 收件單(名稱=候選.stem, 任務=內容.strip(), 處理中路徑=目標)


def _讀得到嗎(路徑: Path) -> str | None:
    """讀不動的不算一件，但**也不移走**——移走等於把使用者丟進來的東西弄丟。"""
    try:
        return 路徑.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
