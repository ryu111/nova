"""帳本的落盤：一次執行一個檔，append-only 的 jsonl。

## 失敗模型（**先寫下來，再選作法**）

| 防不防 | 情境 | 怎麼防的 |
|---|---|---|
| ✅ 防 | 程序被殺（逾時、Ctrl-C、OOM、`kill`） | 長開 handle，每一筆寫完 `flush()` |
| ❌ 不防 | 機器斷電、核心崩潰 | **沒有 `fsync`**——要防那個得每筆同步一次磁碟 |
| ❌ 不防 | 磁碟滿寫到一半留下半行 | 讀取端要能跳過壞行，而讀取端還沒做 |
| ❌ 不防 | 兩個程序寫同一個檔 | 一次執行一個檔、一個 handle（見下方「從簡」） |

選這一格的理由：nova 最在意的是 at-most-once——「這一次呼叫到底出門了沒」。
那件事被「程序被殺」威脅（逾時是天天發生的事），不太被「斷電」威脅。
每筆 fsync 要付一次真的磁碟同步，換來的是我們現在不需要的保證。

從簡：單執行緒、一次執行一個檔一個 handle。要支援多程序共寫同一個檔，
升級路徑是每行一次 `O_APPEND` 的 `write()`（POSIX 保證 PIPE_BUF 以內原子），
或者各寫各的檔、讀取端再合併。**現在沒有第二個寫入者，所以不做。**

## 帳本自己寫失敗的時候，終局是什麼

分界線是**副作用發生了沒**：

```
開檔失敗   → 還沒叫過任何模型 → 當場炸（fail-closed）
           理由：現在停，什麼都還沒發生，代價只是重跑一次指令。

寫入失敗   → 模型已經跑過了   → 不准往上丟（fail-open），但要印到 stderr
           理由：丟例外會讓上游以為呼叫失敗而重跑，重跑會把可能做過的事
                 再做一次。帳本壞掉是可觀測性的損失，不是工作的損失。
```

而且 stderr 只吵一次（sticky）——磁碟滿的時候每一筆都會失敗，
每筆都印會把模型真正的輸出洗掉。
"""

import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from os import environ
from pathlib import Path
from secrets import token_hex
from typing import TextIO

from nova.契約.帳本 import 事件, 欄位對應, 記一筆


@dataclass(frozen=True, slots=True)
class 帳本:
    """兩個函式，不是一個物件的兩個方法。

    為什麼多一個 `新呼叫編號`：成對事件要配對，而編號必須在整次執行裡唯一——
    接力鏈上每顆腦各包一層記帳，各自數自己的話會撞號。發號的權責歸帳本，
    因為它是那一格唯一從頭活到尾的東西。
    """

    記一筆: 記一筆
    新呼叫編號: Callable[[], int]


def _現在() -> str:
    """ISO 8601、UTC、毫秒。本地時區會讓跨機器比對的人算時差。"""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def 建帳本(串流: TextIO, *, 執行識別碼: str, 現在: Callable[[], str] = _現在) -> 帳本:
    """把一個已經開好的串流包成帳本。

    收串流不收路徑（依賴反轉）：測試給 `StringIO` 就能驗完所有行為，
    不必碰磁碟；`開帳本` 才負責真的開檔。
    """
    狀態 = {"序號": 0, "呼叫": 0, "壞了": False}

    def 記(事: 事件) -> None:
        if 狀態["壞了"]:
            return
        狀態["序號"] = int(狀態["序號"]) + 1
        行 = {"run": 執行識別碼, "seq": 狀態["序號"], "ts": 現在(), **_攤平(事)}
        try:
            串流.write(json.dumps(行, ensure_ascii=False) + "\n")
            串流.flush()
        except OSError as 錯:
            狀態["壞了"] = True
            # 不往上丟：模型已經跑完了，這時候讓呼叫端以為失敗會導致重跑。
            sys.stderr.write(f"[nova] 帳本寫不進去，之後不再嘗試：{錯}\n")

    def 發號() -> int:
        狀態["呼叫"] = int(狀態["呼叫"]) + 1
        return int(狀態["呼叫"])

    return 帳本(記一筆=記, 新呼叫編號=發號)


def _攤平(事: 事件) -> dict[str, object]:
    """中文欄位 → ASCII 鍵，順便丟掉沒填的欄位。

    `欄位對應` 少一格，那個欄位就會靜默消失——所以那張表由
    `test_每個欄位都有對應` 窮舉背書。
    """
    出: dict[str, object] = {}
    for 欄 in fields(事):
        值 = getattr(事, 欄.name)
        if 值 is not None:
            出[欄位對應[欄.name]] = 值
    return 出


def 不記帳本() -> 帳本:
    """什麼都不寫，但形狀一樣——呼叫端才不必寫「有沒有帳本」的分支。"""
    狀態 = {"呼叫": 0}

    def 不記(事: 事件) -> None:
        del 事

    def 發號() -> int:
        狀態["呼叫"] += 1
        return 狀態["呼叫"]

    return 帳本(記一筆=不記, 新呼叫編號=發號)


def 預設帳本目錄() -> Path:
    """`$XDG_STATE_HOME/nova/帳本`，沒設就 `~/.local/state/nova/帳本`。

    **刻意不落在任何 repo 裡。** 落在工作目錄的話，被 nova 驅動的模型
    會順手把帳本 commit 進去——而帳本裡有提示長度、失敗代碼這些
    不該進版控的東西，何況 repo 是 public。
    """
    根 = environ.get("XDG_STATE_HOME")
    return (Path(根) if 根 else Path.home() / ".local" / "state") / "nova" / "帳本"


def 新執行識別碼() -> str:
    """時間開頭所以 `ls` 就是時序，尾巴補亂數避免同一秒撞檔名。"""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + token_hex(3)


@contextmanager
def 開帳本(目錄: Path | None = None, *, 執行識別碼: str | None = None) -> Iterator[帳本]:
    """開一個檔，用完關掉。檔名就是執行識別碼。

    開檔失敗**當場炸**：那時候還沒叫過任何模型，停下來的代價只是重跑指令。
    """
    在哪 = 目錄 or 預設帳本目錄()
    識別 = 執行識別碼 or 新執行識別碼()
    在哪.mkdir(parents=True, exist_ok=True)
    with (在哪 / f"{識別}.jsonl").open("a", encoding="utf-8") as 檔:
        yield 建帳本(檔, 執行識別碼=識別)
