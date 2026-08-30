"""自己動手之前要先說得出理由。

## 這條規則管得了什麼、管不了什麼

「這件事該不該交給 nova 做」**不是機械判得出來的**——它要看題目大小、
要不要跨多輪、nova 現在缺哪一格。所以把關的對象不是那個判斷，
是**「這個 session 有沒有記下一個決定」**。

那個記錄本身才是產出：它累積成一份**「nova 現在還做不了什麼」**的清單，
而那是使用者真正想知道的東西。

## 管轄範圍要窄

窄到不會擋住「修 nova 自己」那條路：

| 路徑 | 管嗎 | 為什麼 |
|---|---|---|
| `src/`、`tests/`、`docs/` 裡的檔案 | **管** | 這正是該走 nova 的那種工作 |
| 開頭是 `.` 的（`.remember/`、`.claude/`、`.git/`） | 不管 | 工具自己的地盤 |
| repo 外面 | 不管 | 這條規則只在這個 repo 裡成立 |

## 記號住專案外面

跟進度檔、祕密檔、狀態檔同一條：**歸屬是索引問題，不是存放位置問題**。
放在工作目錄裡等於讓執行者自己發自己的通行證。
"""

import re
from datetime import UTC, datetime
from pathlib import Path

from nova.載體.帳本 import 專案識別
from nova.載體.狀態 import 狀態根目錄

#: 記號放哪。跟帳本、收件匣、狀態檔同一個專案資料夾底下。
_資料夾 = "繞過"

#: session id 會拿來當檔名，所以只准這些字。
#: **外面來的字串不准直接當路徑**——`../` 就跑出去了。
_安全的會話 = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def 在管轄範圍嗎(路徑: Path, *, 根目錄: Path) -> bool:
    """這個檔案歸這條規則管嗎。**純函式，所以測得動。**

    路徑要先解析成絕對的：`docs/../.remember/x.md` 比字串的話看起來像
    `docs/` 底下，那等於沒擋到點開頭的地盤。
    """
    try:
        絕對路徑 = 路徑 if 路徑.is_absolute() else (根目錄 / 路徑)
        相對 = 絕對路徑.resolve().relative_to(根目錄.resolve())
    except ValueError:
        return False
    if not 相對.parts:
        return False
    return not any(段.startswith(".") or 段 == "scratchpad" for 段 in 相對.parts)


def 繞過目錄(專案: Path) -> Path:
    """這個專案的繞過記號住哪。"""
    return 狀態根目錄() / "專案" / 專案識別(專案) / _資料夾


def 記下繞過(會話: str, 因為: str, *, 專案: Path) -> Path:
    """記下「這次為什麼自己動手」，回傳記號的位置。

    **空理由等於沒理由**，收下去的話這條規則一秒就被繞乾淨。
    """
    理由 = 因為.strip()
    if not 理由:
        訊息 = "理由是空的——說不出 nova 做不了哪一格，就走 nova"
        raise ValueError(訊息)
    if not _安全的會話.match(會話):
        訊息 = f"看不懂的會話識別碼 {會話!r}——只准英數字與 . _ -"
        raise ValueError(訊息)
    目錄 = 繞過目錄(專案)
    目錄.mkdir(parents=True, exist_ok=True)
    落點 = 目錄 / f"{會話}.md"
    落點.write_text(f"{datetime.now(UTC).isoformat()}\n{理由}\n", encoding="utf-8")
    return 落點


def 說得出理由了嗎(會話: str, *, 專案: Path) -> bool:
    """這個 session 記過了嗎。**按 session 分**——

    理由是「這次為什麼 nova 做不了」，那是每次工作各自成立的事，
    不是一次講完就永久有效。
    """
    if not _安全的會話.match(會話):
        return False
    return (繞過目錄(專案) / f"{會話}.md").is_file()


def 擋的話要說什麼(會話: str) -> str:
    """擋下來要**能照做**，不然它只是個路障。兩條路都給，session id 填好。"""
    return (
        '預設把工作丟給 nova：`nova 跑 "<題目>"`——'
        "帳、遮罩、預算鎖、狀態檔那一整條線只有走 nova 才會接上。\n"
        "真的有 nova 做不到的那一格，說出來就放行："
        f'`nova 繞過 --會話 {會話} --因為 "<nova 做不了的那一格>"`'
    )
