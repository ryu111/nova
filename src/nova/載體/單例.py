"""一次只准跑一個。**排程一定會踩到的那個坑。**

排程每 15 分鐘叫一次 nova，而一輪工作流可能跑 40 分鐘。沒有這一層的話，
第 15 分鐘會開第二個、第 30 分鐘第三個——三個一起燒預算、一起改同一份原始碼，
而且**看起來完全正常**：每一個都在跑，每一個都有帳本。

`收件/處理中/` 擋得住「兩個程序拿到同一件」，擋不住「兩個程序各拿一件同時跑」。
那是兩個不同的問題，各要一個機制。

## 為什麼是 flock 不是 PID 檔

PID 檔要處理「寫檔的程序被 kill -9 了怎麼辦」——那要去問那個 PID 還在不在，
而 PID 會重用。`flock` 由 kernel 綁在檔案描述符上：**程序不管怎麼死，
描述符一定會關，鎖一定會放掉**。不需要清理邏輯，也就沒有清理邏輯的 bug。

## 拿不到鎖不是錯誤

排程本來就會在忙的時候醒來。那時候該做的是安靜地讓開——
把它印成錯誤的話，排程的 log 會被永遠不會有人修的錯誤塞滿，
然後真的錯誤就被淹掉了。呼叫端請回 0 不要回非零。
"""

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class 拿不到鎖(Exception):
    """已經有一個在跑了。**這是正常狀態，不是壞掉。**"""


@contextmanager
def 只准一個(鎖檔: Path) -> Iterator[None]:
    """拿到鎖就往下跑，拿不到就丟 `拿不到鎖`。

    鎖檔的內容沒有意義（也不寫 PID——PID 會重用，而 `flock` 不需要它）。
    有意義的只有「這個檔案描述符上有沒有鎖」。
    """
    鎖檔.parent.mkdir(parents=True, exist_ok=True)
    with 鎖檔.open("a+", encoding="utf-8") as 檔:
        try:
            fcntl.flock(檔.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as 錯:
            訊息 = f"已經有一個在跑了（{鎖檔}）"
            raise 拿不到鎖(訊息) from 錯
        yield
        # **不必明確解鎖。** `with` 離開時一定會 close，而 close 就會放掉
        # 這個描述符上的 flock——包含裡面丟例外的那條路。
        #
        # 原本這裡寫了一行 `LOCK_UN` 加一段「不然會自己擋住自己」的理由。
        # 跑負控的時候拿掉它——**沒有任何測試變紅**，因為那個情境在
        # `with open` 之下不可能發生（close 是確定性的，不等 GC）。
        # 沒有測試背書的程式碼就是沒有保證，所以刪掉而不是留著。
