"""跑閘的時候跟這台機器要 CPU 額度。**資源是機器的，不是專案的。**

## 這個模組擋什麼

`規則表.py` 的「一次只跑一條」管的是**一個閘內部**的規則順序。
三個 nova 各自開一個閘，那三個 pytest 就同時吃滿 CPU，而誰也不知道誰在跑。

代價不是慢，是**假紅**：`tests/負控/登記.py` 每把刀的 `最多秒` 是 2.0，
執行器拿它當 `subprocess.timeout`——那是**牆鐘**，不是 CPU 時間。
機器超載時刀跑不完就被殺，判成「這把刀沒被殺掉」——一支好好的測試被報成壞的，
而且下一步通常是有人去把那支測試「修好」。
**負控刀要整台機器的理由就是這個牆鐘**：牆鐘不管機器上還有誰，
所以只有它得抽乾池子；別的規則超載只是慢，不會假紅。

## 為什麼是 token 池不是一把互斥鎖

擋的是 **CPU 額度**，不是「一次一條閘」。做成互斥鎖的話，一條只吃 1 個核心的
序列 pytest 也要獨佔 16 核的機器——實測 `閘.排隊` 底下排了 12 個，
一次 `nova 閘 提交` 含排隊 318 秒。

所以粒度改成 make jobserver 那種**跨程序的計數信號量**：池子有
N ＝ `int(核心 × 平行成數)` 個 token 檔，每個檔自己 `flock`；
每條指令按**自己實際會開的 worker 數**取用——序列 pytest／ruff／mypy 取 1，
`pytest-parallel` 取 `平行度()`，只有負控刀抽乾整池。

## 為什麼是 flock 不是「檢查檔案存不存在」

`exists()` 再 `touch()` 中間有空隙，兩個程序會同時通過。而且程序被 `kill -9`
之後那個檔會留著，鎖就永遠拿不掉——**要人去手動刪的鎖，遲早被人拿掉**。
`flock` 兩件事都免費解決：取鎖是原子的，程序死掉核心自動放鎖。

## 為什麼鎖檔不能放在專案底下

每個 git worktree 被 nova 當成不同專案。鎖檔跟著專案走的話，
三個 worktree 各拿各的鎖——**三把鎖，零保護**，而且看起來完全正常。
"""

import fcntl
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from os import environ
from pathlib import Path
from typing import TextIO

from nova.載體.機器額度 import 平行成數
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
    """等到上限還是要不到額度。

    **這不是「閘紅」**——閘根本沒跑。呼叫端不准把它當成檢查失敗，
    那會讓「機器很忙」長得跟「程式壞了」一樣。
    """


class 抽乾池子時不准握著token(RuntimeError):
    """握著 token 的人又要抽乾整池——**等的人就是還的人，這是死鎖。**

    跟 `佔不到` 分開是因為下一步相反：「機器很忙」要等，「自己鎖死自己」要修。
    混成一個的話，一個程式錯誤會偽裝成一次三十分鐘的排隊。
    """


@dataclass(frozen=True, slots=True)
class 佔用:
    """拿到額度的收據：**排了多久才輪到**。

    這個數字是改完之後唯一證明得了「排隊消失了」的東西。沒有它，
    「閘很慢」就分不出是檢查本身重（要拆規則）還是機器上排了十二條（要調額度），
    而那兩者的下一步完全相反。
    """

    等待毫秒: int


def 等鎖說明(等待毫秒: int) -> str:
    """把「排了幾毫秒」講成人話。**沒等就不出聲**（回空字串）。

    格式化只寫在這一份：帳本、判準證據、CLI 三個出口印出來的秒數必須一模一樣，
    各自 `f"{x/1000:.1f}"` 的話，哪天有人只改了其中一處就多出第二個來源。
    """
    if 等待毫秒 <= 0:
        return ""
    return f"等鎖 {等待毫秒 / 1000:.1f} 秒"


def 池大小(核心數: int | None = None) -> int:
    """池子裡有幾個 token。**跟平行測試同一個成數**——量的是同一台機器的核心。"""
    核心 = 核心數 or os.cpu_count() or 1
    return max(1, int(核心 * 平行成數))


def 鎖檔路徑(名稱: str, 鎖目錄: Path | None = None) -> Path:
    """鎖檔住哪。**路徑裡不准有專案識別。**"""
    底 = 鎖目錄 if 鎖目錄 is not None else 狀態根目錄() / "鎖"
    return 底 / f"{名稱}.lock"


def _同一層的(落點: Path, 尾巴: str) -> Path:
    """鎖檔旁邊、同名不同尾巴的那個檔或目錄。

    token 池、號碼牌、發號鎖、序號都跟鎖檔同一層，名字跟著資源的名稱走——
    一個名稱底下的東西看得出來是一組的。
    """
    return 落點.parent / f"{落點.stem}.{尾巴}"


def _池目錄(落點: Path) -> Path:
    """token 檔放哪。"""
    return _同一層的(落點, "slots")


def _token檔路徑(池: Path, 編號: int) -> Path:
    """回傳池中指定編號的 token 檔。"""
    return 池 / f"{編號:03d}"


#: **這一條執行緒**手上每一次 `佔住` 各拿走幾個 token，按池子分開記。
#: 只給死鎖判斷用（見 `抽乾池子時不准握著token`）：跨程序的真相在檔案系統上。
#:
#: **為什麼是 thread-local 不是整個程序一份**：死鎖的定義是「等的人就是還的人」。
#: 同一個程序裡的**另一條執行緒**握著 token，那條線跑完自己會還——那是「機器很忙」，
#: 該等。工作流就長這樣：判準跑在別的執行緒上（`tests/整合/test_判準也要進鎖.py`），
#: 記成整個程序一份的話，一條線在跑判準就會讓另一條線的抽乾**當場拋**，
#: 把「等一下就好」報成「程式壞了」。
_每條線握著的token = threading.local()


def _我握著的每一筆token(池: Path) -> list[int]:
    """這條執行緒在 `池` 這個池子裡握著的每一筆。沒握過就開一份空的。"""
    每個池: dict[Path, list[int]] | None = getattr(_每條線握著的token, "每個池", None)
    if 每個池 is None:
        每個池 = {}
        _每條線握著的token.每個池 = 每個池
    return 每個池.setdefault(池, [])


def _換算要幾個token(要幾個token: int | None, 全部: int) -> int:
    """換算成實際要抓幾個 token。

    `None` ＝ 呼叫端沒算過自己吃多少，那就保守假設它要整台機器。
    比池子還大的要求夾到池子大小：不然它**永遠**等不到，
    而那不是「機器很忙」，是掛死。
    """
    if 要幾個token is None:
        return 全部
    return max(1, min(要幾個token, 全部))


def _擋下自己鎖死自己(池: Path, 名稱: str, *, 要幾個: int, 全部: int) -> None:
    """**這條線**握著 token 又要抽乾**同一個池子**就當場拋——等的人就是還的人。

    **有上限也照拋**：自鎖不會因為等得短就變成不是自鎖。差別不在等多久，
    在**下一步**——`佔不到` 的下一步是重試（機器很忙，等一下就好），
    自鎖的下一步是修程式（多等一百倍也還是等不到，因為要還的人正在等）。

    別條執行緒握著的不算（見 `_我握著的每一筆token`）：那些 token 有人會還。
    """
    我握著 = sum(_我握著的每一筆token(池))
    if 要幾個 < 全部 or 我握著 == 0:
        return
    訊息 = (
        f"握著 {我握著} 個 token 還要抽乾 {名稱} 的整池"
        f"（{全部} 個）——剩下的永遠等不到，先把自己手上的還掉再來"
    )
    raise 抽乾池子時不准握著token(訊息)


@contextmanager
def 佔住(
    名稱: str = "閘",
    *,
    要幾個token: int | None = None,
    最多等幾秒: float | None = None,
    鎖目錄: Path | None = None,
    核心數: int | None = None,
) -> Iterator[佔用]:
    """跟這台機器上叫做 `名稱` 的那個池子要 `要幾個token` 個額度，離開就還。

    yield 出去的 `佔用` 是**收據**：等了多久才拿到。呼叫端不看也沒關係
    （`with 佔住(...):` 的舊寫法照樣成立），但看得到才講得出排隊有多長。

    `要幾個token` ＝ 這條指令實際會開的 worker 數。不給就是**抽乾整池**：
    沒說要幾個的呼叫端等於沒算過自己吃多少，那時保守假設它要整台機器。

    **放 token 走 `finally`**：閘紅是常態，那條路一定會拋例外——
    漏掉的話第一次紅就把整台機器卡死。
    """
    全部 = 池大小(核心數)
    要幾個 = _換算要幾個token(要幾個token, 全部)
    落點 = 鎖檔路徑(名稱, 鎖目錄)
    池 = _池目錄(落點)
    _擋下自己鎖死自己(池, 名稱, 要幾個=要幾個, 全部=全部)

    上限 = 預設最多等幾秒() if 最多等幾秒 is None else 最多等幾秒
    落點.parent.mkdir(parents=True, exist_ok=True)
    池.mkdir(parents=True, exist_ok=True)

    我的token們, 等待毫秒 = _等到拿得到(落點, 要幾個=要幾個, 全部=全部, 最多等幾秒=上限)
    _我握著的每一筆token(池).append(要幾個)
    try:
        yield 佔用(等待毫秒=等待毫秒)
    finally:
        # **關掉 fd 就是放鎖**，不必再 `LOCK_UN` 一次。
        # 顯式解鎖那一行看起來比較嚴謹，但它沒有任何測試殺得掉
        # （拿掉之後每一支都還是綠的）——沒有測試背書的程式碼是裝飾，
        # 而裝飾會讓人以為保證住在那裡。真正的保證在這個 `finally`：
        # 閘紅是常態，那條路一定會拋例外，漏掉就把整台機器卡死。
        # **pop 最後一筆**，不是按值刪：巢狀的 `佔住` 是後進先出，
        # 而按值刪會挑到別人那一筆（數字一樣就分不出是誰的）。
        _我握著的每一筆token(池).pop()
        for token in 我的token們:
            token.close()


def _排隊目錄(落點: Path) -> Path:
    """號碼牌放哪。"""
    return _同一層的(落點, "排隊")


@contextmanager
def _圈住發號(落點: Path) -> Iterator[None]:
    """把「抽號碼牌」與「看前面還有誰」圈成不可分割的一段。

    這裡用**阻塞式** `flock` 沒關係：圈住的只有幾個 syscall，
    不像閘那樣圈著一整條 pytest。而且發號的人被 `kill -9`，核心照樣放鎖。
    """
    發號檔 = _同一層的(落點, "發號")
    handle = 發號檔.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        handle.close()


def _抽號碼牌(落點: Path) -> tuple[int, TextIO]:
    """拿一個號碼，並把號碼牌檔 `flock` 住。**牌的 fd 就是「我還在排隊」**。

    號碼與建牌都在發號鎖裡面，所以號碼的大小順序就是**進場順序**；
    輪詢的相位再怎麼錯開也改不了它。
    """
    排隊 = _排隊目錄(落點)
    排隊.mkdir(parents=True, exist_ok=True)
    序號檔 = _同一層的(落點, "序號")
    with _圈住發號(落點):
        try:
            上一號 = int(序號檔.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            上一號 = 0
        序號 = 上一號 + 1
        序號檔.write_text(str(序號), encoding="utf-8")
        牌 = (排隊 / f"{序號:020d}").open("a+")
        fcntl.flock(牌.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    return 序號, 牌


def _牌的主人死了(牌檔: Path) -> bool:
    """牌還在但沒有人 `flock` 著，代表主人被 `kill -9` 了。

    沒有這一段，一個被殺掉的等待者會把整條隊伍卡死——
    那正是當初不選「檔案存不存在」而選 `flock` 要避開的東西。
    """
    try:
        handle = 牌檔.open("a+")
    except OSError:
        return False
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    finally:
        handle.close()
    return True


def _輪到我了(落點: Path, 序號: int) -> bool:
    """排在我前面的號碼牌全不在了，才輪到我去搶鎖。

    掃描一樣在發號鎖裡面：不然會看到一張「已經建好、還沒 `flock`」的牌，
    把它誤判成死人的牌而回收掉，那條就被插隊了。
    """
    with _圈住發號(落點):
        for 牌檔 in sorted(_排隊目錄(落點).iterdir()):
            try:
                編號 = int(牌檔.name)
            except ValueError:
                continue
            if 編號 >= 序號:
                break
            if _牌的主人死了(牌檔):
                牌檔.unlink(missing_ok=True)
            else:
                return False
    return True


def _抓幾個token(落點: Path, *, 要幾個: int, 全部: int) -> list[TextIO] | None:
    """試著一次抓齊 `要幾個` 個 token，抓不齊就**全部還回去**回 `None`。

    **不准抓多少算多少**：握著三個等第四個的人也在擋別人，
    而擋著別人的等待就是死鎖的另一個名字。
    """
    池 = _池目錄(落點)
    for 第幾個 in range(全部):
        _token檔路徑(池, 第幾個).touch(exist_ok=True)
    抓到: list[TextIO] = []
    for 第幾個 in range(全部):
        # **不用 `w`**：截斷會在還沒拿到鎖的時候就動到檔案內容。
        token檔 = _token檔路徑(池, 第幾個).open("a+")
        try:
            fcntl.flock(token檔.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            token檔.close()
            continue
        抓到.append(token檔)
        if len(抓到) == 要幾個:
            return 抓到
    for 還回去 in 抓到:
        還回去.close()
    return None


def _等到拿得到(
    落點: Path, *, 要幾個: int, 全部: int, 最多等幾秒: float
) -> tuple[list[TextIO], int]:
    """排隊等到抓得齊為止（**先到先得**），回傳 token 們與**被擋住幾毫秒**。

    等超過上限就 `佔不到`。

    **只累計 `time.sleep` 那幾段**：抽號碼牌、`mkdir`、掃隊伍那些毫秒是本來就要付的，
    算進去的話「等了多久」就變成「這個函式跑了多久」，而後者跟隊伍長短無關——
    一台沒人跟你搶的機器也會量到幾毫秒，那個欄位就開始說謊。

    **走 `LOCK_NB` 加輪詢，不走阻塞式的 `flock`**：阻塞版沒有上限，
    前面那個程序卡住的話這裡會等到天荒地老，而且看不出來在等什麼。

    但輪詢自己沒有順序：鎖一放開誰先醒誰先拿，跟等了多久無關。
    有實際等待上限的呼叫先抽一張號碼牌，**輪到自己才去搶**——等最久的那條不會再
    一輪一輪輸掉。`最多等幾秒=0` 是即時快照，只試一次，不因前面的號碼牌停住。
    """
    起 = time.monotonic()
    被擋住秒 = 0.0
    序號, 牌 = _抽號碼牌(落點)
    try:
        while True:
            # 零秒是快照，不該因為前一條剛拿到號碼牌就看不到池裡仍可用的 token。
            if 最多等幾秒 == 0 or _輪到我了(落點, 序號):
                抓到 = _抓幾個token(落點, 要幾個=要幾個, 全部=全部)
                if 抓到 is not None:
                    return 抓到, round(被擋住秒 * 1000)
            if time.monotonic() - 起 >= 最多等幾秒:
                訊息 = f"等了 {最多等幾秒} 秒還是要不到 {落點} 的 {要幾個}/{全部} 個token——閘沒有跑"
                raise 佔不到(訊息) from None
            睡前 = time.monotonic()
            time.sleep(_每隔幾秒再試)
            被擋住秒 += time.monotonic() - 睡前
    finally:
        # 拿到 token（或放棄）就把牌交回去，下一號才進得來。
        牌.close()
