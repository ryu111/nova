"""驗收指令怎麼跑。**回 0 才算做完，不是模型說做完了。**

硬規則第 2 條不准拿「模型說完成了」當停止條件。收件匣迴圈原本的 0 只代表
「工作流沒摔」，不代表「事情做對了」——這個模組是把判準換掉的那一步。

跟 `判準` 的差別：那邊是 TDD 內圈自己的紅綠燈（有預設指令、會分「跑不起來」），
這邊是**票上宣告的驗收**，指令從收件檔讀進來，所以多了兩條防線：
一律不走 shell，而且任何一條炸掉都不准把整個迴圈弄倒。
"""

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

_證據上限 = 4000
"""一條驗收留多少字的證據（留尾巴）。

整份 pytest 輸出動輒上萬行，全留著沒人看得完，還會把成果帳撐爆。
失敗訊息通常在最後，所以截頭不截尾。
"""

_逾時退出碼 = 124
"""借 GNU timeout 的慣例。**逾時沒有真正的退出碼**，但它必須是非 0——
「不知道有沒有過」在驗收這裡一律當紅（fail-closed）。
"""

_跑不起來退出碼 = 127
"""借 shell 的 command not found。執行檔不存在、沒有執行權限都算這格。"""


@dataclass(frozen=True, slots=True)
class 一條的結果:
    """一條驗收指令跑完長什麼樣。"""

    指令: str
    退出碼: int
    證據: str


@dataclass(frozen=True, slots=True)
class 驗收結果:
    """整串驗收的結果。

    **`綠` 為真而 `每一條` 是空的，意思是「沒有驗收」，不是「驗收過了」。**
    兩者分得開只靠 `每一條` 那一格，所以呼叫端不准只看 `綠`——
    只看 `綠` 的話，一張沒宣告驗收的票會長得跟驗收通過一模一樣。
    """

    綠: bool
    每一條: tuple[一條的結果, ...]


def 跑驗收(指令們: tuple[str, ...], *, 工作目錄: Path, 每條上限秒: float = 900) -> 驗收結果:
    """依序跑驗收指令，全部回 0 才算綠。

    **第一條紅就停**，後面的不跑——跟閘同一條規矩：已經紅了就沒必要再燒時間，
    而且後面那些指令常常預設前面那條已經成立。

    指令列表是空的時候回綠、`每一條` 是空 tuple。那個綠代表**沒有驗收**，
    不代表驗收過了；見 `驗收結果` 的說明。
    """
    每一條: list[一條的結果] = []
    for 指令 in 指令們:
        這條 = _跑一條(指令, 工作目錄=工作目錄, 上限秒=每條上限秒)
        每一條.append(這條)
        if 這條.退出碼 != 0:
            return 驗收結果(綠=False, 每一條=tuple(每一條))
    return 驗收結果(綠=True, 每一條=tuple(每一條))


def _跑一條(指令: str, *, 工作目錄: Path, 上限秒: float) -> 一條的結果:
    """跑一條，**絕不往外拋例外**——打錯字的驗收指令不准把整個迴圈弄倒。

    炸掉的話那一輪連成果帳都寫不出來，而「驗收指令打錯」跟「工作真的沒做完」
    在外面看起來會一模一樣。所以每一種摔法都翻譯成一個非 0 的退出碼。
    """
    argv = shlex.split(指令)
    if not argv:
        return 一條的結果(指令=指令, 退出碼=_跑不起來退出碼, 證據="空的驗收指令")
    try:
        # **不走 shell 是安全邊界，不是風格。** 驗收指令是從收件檔讀的，
        # 走 shell 的話 `;`、`&&`、反引號都會被展開，一條驗收就等於任意命令執行。
        結果 = subprocess.run(  # noqa: S603 —— 刻意 shell=False，argv 由 shlex 拆好
            argv,
            cwd=工作目錄,
            capture_output=True,
            text=True,
            timeout=上限秒,
            check=False,
        )
    except subprocess.TimeoutExpired as 錯:
        說明 = f"逾時：超過 {上限秒} 秒還沒跑完（逾時一律算紅）"
        殺掉前的輸出 = _併成證據(錯.stdout, 錯.stderr)
        return 一條的結果(指令=指令, 退出碼=_逾時退出碼, 證據=_截斷(f"{說明}\n{殺掉前的輸出}"))
    except OSError as 錯:
        return 一條的結果(指令=指令, 退出碼=_跑不起來退出碼, 證據=_截斷(f"跑不起來：{錯}"))
    return 一條的結果(
        指令=指令,
        退出碼=結果.returncode,
        證據=_截斷(_併成證據(結果.stdout, 結果.stderr)),
    )


def _截斷(文字: str) -> str:
    """只留尾巴。失敗訊息幾乎都在最後，所以截頭不截尾。"""
    return 文字.strip()[-_證據上限:]


def _併成證據(標準輸出: str | bytes | None, 錯誤輸出: str | bytes | None) -> str:
    """把子程序的 stdout 與 stderr 併成一段證據，兩邊都要留。

    只看 stdout 的話，測試框架把失敗訊息寫到 stderr 時會留下一份空證據。
    """
    return _轉成字串(標準輸出) + _轉成字串(錯誤輸出)


def _轉成字串(值: str | bytes | None) -> str:
    """逾時時拿到的部分輸出可能是 bytes、str 或 None，統一成字串。

    `TimeoutExpired` 帶的部分輸出不保證解得開，所以壞掉的位元組換成替代字元，
    **不准讓解碼失敗把整條驗收變成例外**——那等於逾時反過來弄倒迴圈。
    """
    if isinstance(值, bytes):
        return 值.decode("utf-8", errors="replace")
    if isinstance(值, str):
        return 值
    return ""
