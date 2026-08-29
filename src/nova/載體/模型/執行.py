"""跑外部 CLI 的共用出口。

**執行檔路徑是參數，不信 PATH。** 本機實測：`which claude codex` 指到 cmux 的
shim，走 shim 跑 `codex exec --json` 會多吐兩條垃圾事件，直接跑真二進位就沒有。
理由和 `規則表._外部指令` 同源——PATH 會讓不同機器跑到不同東西。
"""

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from nova.契約.角色 import 預設逾時秒
from nova.載體.程序 import 收割整棵


class 執行逾時(Exception):
    """子程序超過時限被殺掉。**帶著它死之前吐出來的東西。**

    原本這個例外只有一句訊息，部分輸出跟著 `TimeoutExpired` 一起被丟掉——
    而那裡面有 sid。實測 codex 被殺當下的部分 stdout 有 20,865 字元，
    第一行就是 `{"type":"thread.started","thread_id":…}`。
    丟掉它等於把「接續思考」這條路自己封死。
    """

    def __init__(self, 訊息: str, *, 部分標準輸出: str = "", 部分標準錯誤: str = "") -> None:
        """`部分*` 預設空字串不是 None——呼叫端不必先判空再用。"""
        super().__init__(訊息)
        self.部分標準輸出 = 部分標準輸出
        self.部分標準錯誤 = 部分標準錯誤


@dataclass(frozen=True, slots=True)
class 執行結果:
    """一次子程序執行的原始結果。"""

    標準輸出: str
    標準錯誤: str
    結束碼: int


def 跑cli(
    執行檔: Path,
    參數: Sequence[str],
    *,
    工作目錄: Path | None = None,
    逾時秒: float = 預設逾時秒,
    環境: Mapping[str, str] | None = None,
) -> 執行結果:
    """跑一次外部 CLI，回結構化結果。逾時會殺掉整棵子程序樹並丟 `執行逾時`。

    `環境` 是整份取代，不是疊加——呼叫端要什麼就明講什麼，
    避免「本機有某個環境變數所以會過、CI 沒有所以會紅」這種不可重現的失敗。
    """
    if not 執行檔.exists():
        訊息 = f"找不到執行檔：{執行檔}"
        raise FileNotFoundError(訊息)
    程序 = subprocess.Popen(  # noqa: S603 —— 執行檔與參數由轉接器組出，不吃使用者自由字串
        [str(執行檔), *參數],
        cwd=工作目錄,
        env=dict(環境) if 環境 is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # **一定要把 stdin 關掉。** 不給的話子程序繼承父程序的 stdin，
        # 而 codex 看到 stdin 是開著的就會等：實測 stderr 印出
        # 「Reading additional input from stdin...」然後一直坐著，
        # 一個 token 都不花，最後被 nova 當成逾時殺掉。
        #
        # **「卡在等輸入」跟「想太久」長得一模一樣**——都是逾時、都是 0 token。
        # sol 那兩次「大題目想不完」的誤診就是這麼來的。
        stdin=subprocess.DEVNULL,
        text=True,
        # 用不了 `subprocess.run`，因為它逾時只 `kill()` 直接子程序，
        # 拿不到 Popen 物件就沒辦法改成打整組。見 `載體.程序`。
        start_new_session=True,
    )
    try:
        標準輸出, 標準錯誤 = 程序.communicate(timeout=逾時秒)
    except subprocess.TimeoutExpired as 錯:
        收割整棵(程序)
        # **不要在這裡再 communicate() 一次。** POSIX 的 `_communicate` 逾時當下
        # 就把讀到的東西塞進例外了，再讀一次只會多冒「孫程序抓著寫入端、
        # 收不到 EOF」的險。由 test_孫程序抓著管線不准讓收屍卡住 背書。
        訊息 = f"{執行檔.name} 超過 {逾時秒} 秒沒回應"
        raise 執行逾時(
            訊息,
            部分標準輸出=_轉字串(錯.stdout),
            部分標準錯誤=_轉字串(錯.stderr),
        ) from 錯
    return 執行結果(標準輸出=標準輸出, 標準錯誤=標準錯誤, 結束碼=程序.returncode)


def _轉字串(原始: str | bytes | None) -> str:
    """`TimeoutExpired.stdout` 的型別看 `text=` 而定，而且可能是 None。

    截斷的位元組一定會有半個字元，所以 `errors="replace"`——
    為了一個問號把整份證據丟掉不划算。
    """
    if 原始 is None:
        return ""
    if isinstance(原始, bytes):
        return 原始.decode("utf-8", errors="replace")
    return 原始
