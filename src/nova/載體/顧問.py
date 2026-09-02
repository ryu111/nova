"""顧問：同一個護欄原因在窗口內反覆出現，就把證據打包成一份診斷素材。

跟 `閘紅成票`／`缺口成票`／`規劃成票` 同一家族：純函式讀帳、數、去重，
外加**一個**落檔動作。

## 它不修任何東西

顧問只出證據。**不准按 `原因` 的值分支**——今晚 `touched-tests` 撞了 17 次，
直覺會生出「修測試檔分類器」，而實證根因是路由（紅送錯角色），
修分類器一行都不會治到。模板對所有原因逐字一致，只有資料欄不同；
要判「根因在哪一層」的是拿到這份素材的那個**唯讀診斷**，不是這裡。

## 兩種去重，缺一種就會堆

* **原因＋票**：收件匣或處理中已經有蓋住這個原因的票就不觸發。
* **原因＋素材**：流 2 還沒回票之前，每輪醒來都不准再堆一份。
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nova.契約.退出碼 import 護欄碼
from nova.載體.已處理 import 列出所有專案成果, 跨專案的一筆
from nova.載體.帳本 import 專案識別
from nova.載體.收件 import 收件目錄, 根因診斷標題, 蓋住原因標記, 處理中目錄
from nova.載體.狀態 import 狀態根目錄

#: 素材檔名的時戳。ASCII、排得動，`護欄原因` 的值也是 ASCII，所以整個檔名進得了檔案系統。
_檔名時戳格式 = "%Y%m%dT%H%M%SZ"

#: 預設窗口與門檻。**這是停止規則，不是設定項**——比照 `收件.最多輪次`：
#: 要放寬是人的決定，不是撞到了就調高。呼叫端給得動，是為了測試給得定時間與門檻。
預設窗口 = timedelta(hours=24)
預設門檻 = 3


@dataclass(frozen=True, slots=True)
class 重覆現場:
    """同一個護欄原因在窗口內撞了幾次、是哪幾次。"""

    原因: str
    幾筆: tuple[跨專案的一筆, ...]
    起: datetime
    迄: datetime
    #: 窗口內退出碼 4、但帳上沒記原因的舊帳有幾筆。**安靜略過會讓人以為
    #: 那個窗口真的只有這幾筆**，所以它要跟著印出來。
    略過幾筆: int


def 顧問目錄(專案: Path | None = None) -> Path:
    """診斷素材住哪。跟收件、帳本、已處理同一條規則：專案外面、用專案當鍵。

    **不落在工作目錄**：素材是要被餵回模型的東西，執行者碰得到就等於
    讓它替未來的自己種話。
    """
    底 = 狀態根目錄()
    return 底 / "顧問" if 專案 is None else 底 / "專案" / 專案識別(專案) / "顧問"


def 重覆的原因(
    *,
    窗口: timedelta = 預設窗口,
    門檻: int = 預設門檻,
    當下: datetime | None = None,
) -> list[重覆現場]:
    """窗口內達門檻的護欄原因，撞最多次的排前面。"""
    現場們, _略過幾筆 = _數帳(窗口=窗口, 門檻=門檻, 當下=當下)
    return 現場們


def _數帳(
    *,
    窗口: timedelta,
    門檻: int,
    當下: datetime | None,
) -> tuple[list[重覆現場], int]:
    """數窗口內的護欄帳：達門檻的現場們，外加略過了幾筆沒記原因的舊帳。

    略過幾筆要**單獨**交出來：達門檻的現場一個都沒有時，那個數字仍然要講得出口。

    判準是**退出碼**加上「帳上記了原因」，不是 `收場` 字串：
    工作流自己撞護欄時 `收場` 寫 `guardrail`，而驗收紅那條 4 寫的是 `done`
    （`契約/成果.py`）。拿 `收場` 過濾會靜靜漏掉 `acceptance-failed`。
    """
    此刻 = 當下 or datetime.now(UTC)
    起 = 此刻 - 窗口
    分組: dict[str, list[跨專案的一筆]] = defaultdict(list)
    略過幾筆 = 0
    for 它 in 列出所有專案成果():
        一筆 = 它.一筆
        if 一筆.退出碼 != 護欄碼:
            continue
        那時 = _讀時間(一筆.迄)
        if 那時 is None or not (起 <= 那時 <= 此刻):
            continue
        if 一筆.護欄原因 is None:
            略過幾筆 += 1
            continue
        分組[一筆.護欄原因].append(它)
    現場們 = [
        重覆現場(原因=原因, 幾筆=tuple(幾筆), 起=起, 迄=此刻, 略過幾筆=略過幾筆)
        for 原因, 幾筆 in 分組.items()
        if len(幾筆) >= 門檻
    ]
    現場們.sort(key=lambda 它: (-len(它.幾筆), 它.原因))
    return 現場們, 略過幾筆


@dataclass(frozen=True, slots=True)
class 一輪的帳:
    """顧問跑一輪的產出：素材落在哪（沒有就是 `None`）、略過了幾筆沒記原因的舊帳。

    略過幾筆**不准只寫進素材**：不達門檻那條路根本不產素材，
    只寫進素材等於在最需要它的那條路上剛好沒有它——
    看到「沒有原因達門檻」的人會以為那個窗口真的只有那幾筆。
    """

    落點: Path | None
    略過幾筆: int


def 盤一輪(
    *,
    專案: Path,
    窗口: timedelta = 預設窗口,
    門檻: int = 預設門檻,
    當下: datetime | None = None,
    每筆幾行: int = 0,
) -> 一輪的帳:
    """數一輪帳：該產素材就產，並把略過了幾筆舊帳一起交出去。

    沒有東西達門檻、或達門檻的都已經有票或已經有素材，`落點` 就是 `None`——
    「今天沒有重覆」是正常結果，不是失敗。
    """
    此刻 = 當下 or datetime.now(UTC)
    收件 = 收件目錄(專案)
    落點目錄 = 顧問目錄(專案)
    現場們, 略過幾筆 = _數帳(窗口=窗口, 門檻=門檻, 當下=此刻)
    for 現場 in 現場們:
        if _已經有票(收件, 現場.原因):
            continue
        if _窗口內已經有素材(落點目錄, 現場):
            continue
        落點 = _落檔(落點目錄, 現場, 門檻=門檻, 每筆幾行=每筆幾行)
        return 一輪的帳(落點=落點, 略過幾筆=略過幾筆)
    return 一輪的帳(落點=None, 略過幾筆=略過幾筆)


def 落成診斷素材(
    *,
    專案: Path,
    窗口: timedelta = 預設窗口,
    門檻: int = 預設門檻,
    當下: datetime | None = None,
    每筆幾行: int = 0,
) -> Path | None:
    """把窗口內撞最多次、還沒有人在處理的那個原因打包成一份素材，回它的落點。"""
    return 盤一輪(
        專案=專案,
        窗口=窗口,
        門檻=門檻,
        當下=當下,
        每筆幾行=每筆幾行,
    ).落點


def _已經有票(收件: Path, 原因: str) -> bool:
    """收件匣或處理中已經有蓋住這個原因的票。

    兩個機器鍵：流 2 出的票第一行是 `# 根因診斷：<原因>`，人手寫的散文票
    帶一行 `<!--nova:蓋住原因 <原因>-->`。

    **讀不動的票算它有**（fail-closed）：寧可漏一輪，也不要在已經有票的
    情況下再堆一份素材。
    """
    票們 = _票們(收件)
    if 票們 is None:
        return True
    第一行 = f"{根因診斷標題}{原因}"
    標記 = 蓋住原因標記(原因)
    for 票 in 票們:
        try:
            內容 = 票.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return True
        if 內容.startswith(第一行) or 標記 in 內容:
            return True
    return False


def _票們(收件: Path) -> list[Path] | None:
    """收件匣與處理中的票；**列舉失敗回 `None`**（＝問不出來，不是問到沒有）。

    `閘紅成票._收集現有票` 做的是同一件事，但它把列舉失敗吞成空清單——
    那對閘紅票是「這輪先不落票」，對顧問卻會被讀成「這個原因還沒有人處理」
    而多堆一份素材。**兩邊的失敗語意不同，所以先各留一份**；
    第三個呼叫端出現時再抽到 `收件.py`，並帶著這個分別。

    目錄**不存在**是第一次跑的正常狀態，那算「查到沒有」。
    """
    收集: list[Path] = []
    for 目錄 in (收件, 處理中目錄(收件)):
        if not 目錄.is_dir():
            continue
        try:
            收集.extend(路 for 路 in 目錄.iterdir() if 路.is_file())
        except OSError:
            return None
    return 收集


def _窗口內已經有素材(落點目錄: Path, 現場: 重覆現場) -> bool:
    """同一個原因在同一個窗口內已經有素材檔。

    **檔名讀不出時戳的算它有**（fail-closed，同 `_已經有票`）。
    """
    if not 落點目錄.is_dir():
        return False
    try:
        既有 = list(落點目錄.glob(f"*-{現場.原因}.md"))
    except OSError:
        return True
    for 檔 in 既有:
        那時 = _讀檔名時戳(檔)
        if 那時 is None or 那時 >= 現場.起:
            return True
    return False


def _落檔(落點目錄: Path, 現場: 重覆現場, *, 門檻: int, 每筆幾行: int) -> Path:
    落點目錄.mkdir(parents=True, exist_ok=True)
    落點 = 落點目錄 / f"{現場.迄.strftime(_檔名時戳格式)}-{現場.原因}.md"
    落點.write_text(_素材內容(現場, 門檻=門檻, 每筆幾行=每筆幾行), encoding="utf-8")
    return 落點


def _素材內容(現場: 重覆現場, *, 門檻: int, 每筆幾行: int) -> str:
    """一致的模板，**不按原因分支**：只有資料欄不同，措辭逐字一樣。"""
    原因 = 現場.原因
    幾次 = len(現場.幾筆)
    小時 = f"{(現場.迄 - 現場.起).total_seconds() / 3600:g}"
    列們 = "\n".join(_一列(它, 每筆幾行=每筆幾行) for 它 in 現場.幾筆)
    return (
        f"# 根因診斷素材：{原因}\n\n"
        f"- 窗口：{現場.起.isoformat()} ~ {現場.迄.isoformat()}（{小時} 小時）\n"
        f"- 命中：{幾次} 次，門檻 {門檻}\n"
        f"- 略過沒記原因的舊帳：{現場.略過幾筆} 筆\n\n"
        f"## 這 {幾次} 筆\n\n"
        "| 執行識別碼 | 迄 | 專案識別 | 走了幾階 | 任務（已遮罩） | 事件帳本 |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        f"{列們}\n\n"
        "## 你要回答什麼\n\n"
        f"這 {幾次} 次都收在同一個護欄原因。請診斷根因**在哪一層**"
        "（載體／迴圈／圖），並出一張票。"
        "不要假設修法就是那個護欄名字所指的東西。\n"
    )


def _一列(它: 跨專案的一筆, *, 每筆幾行: int) -> str:
    """一筆一列，事件帳本**只給絕對路徑，不整份倒進來**。

    唯讀診斷有檔案權限，自己去讀全文；抄進來只會把素材淹掉。
    真的要節錄走 `每筆幾行`。
    """
    一筆 = 它.一筆
    節錄 = _節錄(它.事件帳本, 每筆幾行)
    return (
        f"| {一筆.執行識別碼} | {一筆.迄} | {它.專案識別} | {一筆.走了幾階} "
        f"| {一筆.任務} | {它.事件帳本}{節錄} |"
    )


def _節錄(事件帳本: Path, 幾行: int) -> str:
    """事件帳本的最後幾行，塞成同一格。讀不動就沒有節錄——素材照樣出得去。

    `幾行` 是 0（預設）就完全不節錄，只留路徑。
    """
    if 幾行 <= 0:
        return ""
    try:
        行們 = 事件帳本.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""
    return "".join(f"<br>`{行}`" for 行 in 行們[-幾行:])


def _讀時間(文字: str) -> datetime | None:
    """帳上的 ISO 時戳。**一律 tz-aware**：沒帶時區的當 UTC，不用 `utcnow()`。"""
    try:
        那時 = datetime.fromisoformat(文字)
    except ValueError:
        return None
    return 那時 if 那時.tzinfo else 那時.replace(tzinfo=UTC)


def _讀檔名時戳(檔: Path) -> datetime | None:
    """素材檔名前綴的落檔時間。認不得的檔名回 `None`，由呼叫端 fail-closed。"""
    try:
        return datetime.strptime(檔.name.split("-", 1)[0], _檔名時戳格式).replace(tzinfo=UTC)
    except ValueError:
        return None
