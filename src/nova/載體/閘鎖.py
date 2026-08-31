"""跑閘的時候佔住這台機器。**資源是機器的，不是專案的。**

## 這個模組擋什麼

`規則表.py` 的「一次只跑一條」管的是**一個閘內部**的規則順序。
三個 nova 各自開一個閘，那三個 pytest 就同時吃滿 CPU，而誰也不知道誰在跑。

代價不是慢，是**假紅**：`tests/負控/登記.py` 每把刀的 `最多秒` 是 2.0，
執行器拿它當 `subprocess.timeout`。機器超載時刀跑不完就被殺，
判成「這把刀沒被殺掉」——一支好好的測試被報成壞的，
而且下一步通常是有人去把那支測試「修好」。

`規則表.py` 把平行測試設成吃 3/4 核心，所以兩條同時跑就超過機器容量，
三條是 2.25 倍。**這是算出來的、不是實測的**——寫這一行的時候
三條 nova 都還停在模型呼叫階段，還沒走到跑測試那一步。

## 為什麼是 flock 不是「檢查檔案存不存在」

`exists()` 再 `touch()` 中間有空隙，兩個程序會同時通過。而且程序被 `kill -9`
之後那個檔會留著，鎖就永遠拿不掉——**要人去手動刪的鎖，遲早被人拿掉**。
`flock` 兩件事都免費解決：取鎖是原子的，程序死掉核心自動放鎖。

## 為什麼鎖檔不能放在專案底下

每個 git worktree 被 nova 當成不同專案。鎖檔跟著專案走的話，
三個 worktree 各拿各的鎖——**三把鎖，零保護**，而且看起來完全正常。
"""

import fcntl
import time
from collections.abc import Iterator
from contextlib import contextmanager
from os import environ
from pathlib import Path
from typing import TextIO

from nova.載體.狀態 import 狀態根目錄

#: 拿不到鎖之前每隔多久再試一次。**不是效能參數**：太密會空轉吃 CPU，
#: 而正在等的那幾條本來就是為了不吃 CPU 才在等。
_每隔幾秒再試 = 0.2

#: 預設最多等多久。閘本身跑滿要 4 分鐘出頭，三條排隊約 15 分鐘，
#: 半小時的窗口讓正常排隊等得到，卡死的情況也不會等到天荒地老。
_預設最多等幾秒 = 1800.0

#: 蓋掉等待上限的環境變數。**那是設定不是邏輯**（跟 `本地.網址環境變數` 同一條）：
#: 一台 4 核的機器排隊會比 16 核久，而那不該要改程式碼。
等待上限環境變數 = "NOVA_鎖最多等幾秒"


def 預設最多等幾秒() -> float:
    """等待上限。環境變數蓋得掉，讀不動的值一律退回預設。

    **讀不動就退回預設，不是炸掉**：一個打錯的環境變數不該讓閘跑不起來。
    """
    值 = environ.get(等待上限環境變數)
    if 值 is None:
        return _預設最多等幾秒
    try:
        return float(值)
    except ValueError:
        return _預設最多等幾秒


class 佔不到(RuntimeError):
    """等到上限還是拿不到鎖。

    **這不是「閘紅」**——閘根本沒跑。呼叫端不准把它當成檢查失敗，
    那會讓「機器很忙」長得跟「程式壞了」一樣。
    """


def 鎖檔路徑(名稱: str, 鎖目錄: Path | None = None) -> Path:
    """鎖檔住哪。**路徑裡不准有專案識別。**"""
    底 = 鎖目錄 if 鎖目錄 is not None else 狀態根目錄() / "鎖"
    return 底 / f"{名稱}.lock"


@contextmanager
def 佔住(
    名稱: str = "閘",
    *,
    最多等幾秒: float | None = None,
    鎖目錄: Path | None = None,
) -> Iterator[None]:
    """佔住這台機器上叫做 `名稱` 的那份資源，離開就放掉。

    **放鎖走 `finally`**：閘紅是常態，那條路一定會拋例外——
    漏掉的話第一次紅就把整台機器卡死。
    """
    上限 = 預設最多等幾秒() if 最多等幾秒 is None else 最多等幾秒
    落點 = 鎖檔路徑(名稱, 鎖目錄)
    落點.parent.mkdir(parents=True, exist_ok=True)
    # **不用 `w`**：截斷會在還沒拿到鎖的時候就動到檔案內容。
    handle = 落點.open("a+")
    try:
        _等到拿得到(handle, 最多等幾秒=上限, 落點=落點)
        yield
    finally:
        # **關掉 fd 就是放鎖**，不必再 `LOCK_UN` 一次。
        # 顯式解鎖那一行看起來比較嚴謹，但它沒有任何測試殺得掉
        # （拿掉之後每一支都還是綠的）——沒有測試背書的程式碼是裝飾，
        # 而裝飾會讓人以為保證住在那裡。真正的保證在這個 `finally`：
        # 閘紅是常態，那條路一定會拋例外，漏掉就把整台機器卡死。
        handle.close()


def _等到拿得到(handle: TextIO, *, 最多等幾秒: float, 落點: Path) -> None:
    """輪詢到拿得到為止。等超過上限就 `佔不到`。

    **走 `LOCK_NB` 加輪詢，不走阻塞式的 `flock`**：阻塞版沒有上限，
    前面那個程序卡住的話這裡會等到天荒地老，而且看不出來在等什麼。
    """
    起 = time.monotonic()
    fd = handle.fileno()
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if time.monotonic() - 起 >= 最多等幾秒:
                訊息 = f"等了 {最多等幾秒} 秒還是佔不到 {落點}——閘沒有跑"
                raise 佔不到(訊息) from None
            time.sleep(_每隔幾秒再試)
        else:
            return
