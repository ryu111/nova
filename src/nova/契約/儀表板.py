"""派工儀表板的契約：**一份 frozen dataclass 就是儀表板的全部真相**。

模板只准渲染這裡有的格子。契約裡沒有的那一格在模板上喊「未接線」，
不准長出假數字——「還沒做」跟「壞了」長得一樣的話，人會照著假的那個數字做決定。

三值原則（票 09）在這裡是型別上的事：

* **未接線**：這個檔裡**沒有那一格**（例：今日合併、鬼影、閘鎖排隊）。
* **查不到**：有這一格、這次問不到，值是 `None`（例：`目前階段`）。
* **有值**：真的問到了。

`算不出成本的執行數` 是第二條的配套：跳過的執行要數得出來，
不然「三本帳沒回成本」會靜靜地變成「總共花了 0.5」——
**低報的成本比沒有成本更危險，因為它看起來像個數字**。

這一層純資料，不 import 載體（`架構閘.py:31-36`）。
"""

from dataclasses import dataclass, fields, is_dataclass
from typing import Any, get_args

from nova.契約.遮罩 import 已遮罩文字


@dataclass(frozen=True, slots=True)
class 退出碼分佈:
    """已收線的退出碼各幾條。碼義見 `契約.退出碼`；四個碼以外的進 `其他`。"""

    成功: int
    確定失敗: int
    未知: int
    護欄: int
    其他: int


@dataclass(frozen=True, slots=True)
class 收件匣:
    """收件匣的四格。**`讀不動` 不是出事才有的欄位**：它永遠拿得到。

    清單上兩件、實際上三件的差距，正是「看起來沒事」與「真的沒事」之間唯一的線索。
    """

    等著: int
    處理中: int
    已完成: int
    讀不動: int


@dataclass(frozen=True, slots=True)
class 一階:
    """七階時間軸上的一階：跑完了、什麼終局、判準綠不綠。"""

    階段: str
    終局: str
    判準綠: bool | None


@dataclass(frozen=True, slots=True)
class 一條線:
    """一條線在儀表板上的那一列。查不到的欄位留 `None`，不拿 0 或空字串頂替。"""

    名字: str
    路徑: str
    #: 這條線在做哪張票。**自由文字，落盤前一定過遮罩。**
    票標題: 已遮罩文字 | None
    目前階段: str | None
    在跑嗎: bool | None
    跑了幾秒: int | None
    啟動時間: str | None
    退出碼: int | None
    護欄原因: 已遮罩文字 | None
    未提交檔案數: int | None
    七階: tuple[一階, ...]


@dataclass(frozen=True, slots=True)
class 一家用量:
    """某一家跨執行的用量。`token` 只算輸入＋輸出，跟 `摘要.總token` 不是同一個數。"""

    供應商: str
    次數: int
    token: int
    佔比: float
    平均每次: int


@dataclass(frozen=True, slots=True)
class 帳本可見度:
    """帳本看得見多少。**「沒有帳」跟「沒有這個專案」是兩件事**，所以兩個數字分開。"""

    本專案token: int
    全部token: int
    專案鍵總數: int
    有內容的專案鍵: int
    跳過的檔: int


@dataclass(frozen=True, slots=True)
class 失敗碼:
    """一個失敗代碼跨執行出現幾次。"""

    代碼: str
    次數: int


@dataclass(frozen=True, slots=True)
class 負控覆蓋:
    """負控的覆蓋面。**是檔數不是刀數**——刀數要 import tests，src 不准，那格未接線。"""

    登記檔數: int
    紀錄檔數: int
    閘規則數: int
    階段數: int


@dataclass(frozen=True, slots=True)
class 儀表板:
    """一份派工現況。**每個數字只有一個來源**：nova 自己的公開讀取器。"""

    產生時間: str
    工作目錄: str
    目前commit: str | None
    總token: int
    總成本美金: float | None
    #: 成本算不出來的那幾次執行。**跳過了就要數出來**，不准當 0 加進總額。
    算不出成本的執行數: int
    呼叫次數: int
    繞過次數: int
    在跑的線: int
    退出碼: 退出碼分佈
    收件匣: 收件匣
    工作樹數: int
    線們: tuple[一條線, ...]
    各家: tuple[一家用量, ...]
    可見度: 帳本可見度
    失敗碼們: tuple[失敗碼, ...]
    負控: 負控覆蓋


#: （繁中屬性名, 落盤的 ASCII 鍵）。**單一來源**：`--json` 是給別的程式讀的，
#: 中文鍵在 shell 裡很難打，屬於 CLAUDE.md 的「event／schema 欄位名」ASCII 例外。
#: 這一張表就是「儀表板有哪幾格」的窮舉——少一格代表模板上會安靜地少一個數字。
_欄位對照: tuple[tuple[str, str], ...] = (
    ("產生時間", "generated_at"),
    ("工作目錄", "workdir"),
    ("目前commit", "head"),
    ("總token", "tokens"),
    ("總成本美金", "cost_usd"),
    ("算不出成本的執行數", "runs_without_cost"),
    ("呼叫次數", "calls"),
    ("繞過次數", "bypasses"),
    ("在跑的線", "lanes_running"),
    ("退出碼", "exit_codes"),
    ("收件匣", "inbox"),
    ("工作樹數", "worktrees"),
    ("線們", "lanes"),
    ("各家", "families"),
    ("可見度", "visibility"),
    ("失敗碼們", "failure_codes"),
    ("負控", "mutation"),
)

#: 巢狀那幾層各自的對照表，跟 `_欄位對照` 同一條規則：鍵是 ASCII、少一格就少一個數字。
_子對照: dict[type, tuple[tuple[str, str], ...]] = {
    退出碼分佈: (
        ("成功", "ok"),
        ("確定失敗", "failed"),
        ("未知", "unknown"),
        ("護欄", "guardrail"),
        ("其他", "other"),
    ),
    收件匣: (
        ("等著", "waiting"),
        ("處理中", "in_progress"),
        ("已完成", "done"),
        ("讀不動", "unreadable"),
    ),
    一階: (("階段", "stage"), ("終局", "outcome"), ("判準綠", "gate_green")),
    一條線: (
        ("名字", "name"),
        ("路徑", "path"),
        ("票標題", "ticket"),
        ("目前階段", "stage"),
        ("在跑嗎", "running"),
        ("跑了幾秒", "elapsed_s"),
        ("啟動時間", "started_at"),
        ("退出碼", "exit_code"),
        ("護欄原因", "guardrail_reason"),
        ("未提交檔案數", "dirty_files"),
        ("七階", "stages"),
    ),
    一家用量: (
        ("供應商", "family"),
        ("次數", "calls"),
        ("token", "tokens"),
        ("佔比", "share"),
        ("平均每次", "avg_tokens"),
    ),
    帳本可見度: (
        ("本專案token", "project_tokens"),
        ("全部token", "all_tokens"),
        ("專案鍵總數", "project_keys"),
        ("有內容的專案鍵", "project_keys_with_ledger"),
        ("跳過的檔", "skipped_files"),
    ),
    失敗碼: (("代碼", "code"), ("次數", "count")),
    負控覆蓋: (
        ("登記檔數", "registry_files"),
        ("紀錄檔數", "record_files"),
        ("閘規則數", "gate_rules"),
        ("階段數", "stages"),
    ),
}


def _蓋滿了嗎(型: type, 對照: tuple[tuple[str, str], ...]) -> None:
    """對照表要**照順序蓋滿** `dataclasses.fields()`，蓋不滿就當場炸。

    契約長出一欄而對照表忘了加，`--json` 會**靜默少一格**：下游拿到的是一份
    看起來完整的 JSON，沒有例外、沒有警告，只是那個數字從此不見了，
    而沒有人記得它本來在那裡。**少一格要炸在寫的人臉上，不是讀的人臉上。**
    """
    欄們 = tuple(一欄.name for 一欄 in fields(型))
    這張表 = tuple(內 for 內, _外 in 對照)
    if 欄們 != 這張表:
        話 = f"{型.__name__} 的欄位是 {欄們}，落盤對照表卻是 {這張表}"
        raise ValueError(話)


def _攤平(值: object) -> object:
    """一格 → 可以 json 的東西。認不得的型別原樣放行（那是純量）。"""
    if isinstance(值, tuple):
        return [_攤平(一個) for 一個 in 值]
    對照 = _子對照.get(type(值))
    if 對照 is None:
        return 值
    _蓋滿了嗎(type(值), 對照)
    return {外: _攤平(getattr(值, 內)) for 內, 外 in 對照}


def _這一格底下是誰(型: object) -> type | None:
    """剝掉 `| None` 與 `tuple[X, ...]` 之後，這一格是不是巢狀的那幾個之一。

    純量回 `None`（底下沒有東西）；序列給的是**元素**的型別——
    落盤的形狀跟這次有幾筆資料無關。
    """
    if isinstance(型, type) and 型 in _子對照:
        return 型
    for 內 in get_args(型):
        找到 = _這一格底下是誰(內)
        if 找到 is not None:
            return 找到
    return None


def _每一張對照表都蓋滿了嗎() -> None:
    """頂層與巢狀那幾層的對照表全部驗過一遍，**跟這次有沒有那筆資料無關**。

    線們／各家／失敗碼們空的那天走不到元素的型別，漏的那一格就沒人在對，
    等到有資料的那天它會安靜地不落盤——而那份偏偏是「今天真的出事了」的 JSON。
    """
    _蓋滿了嗎(儀表板, _欄位對照)
    應有的型別 = {
        值
        for 值 in globals().values()
        if isinstance(值, type) and is_dataclass(值) and 值 is not 儀表板
    }
    if set(_子對照) != 應有的型別:
        訊息 = "巢狀 dataclass 缺少落盤對照表"
        raise ValueError(訊息)
    for 型, 對照 in _子對照.items():
        _蓋滿了嗎(型, 對照)


def _一層鍵樹(型: type, 對照: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    """這一層的 ASCII 鍵 → 底下那一層的鍵樹；純量底下是 `{}`。"""
    _蓋滿了嗎(型, 對照)
    欄型 = {一欄.name: 一欄.type for 一欄 in fields(型)}
    出: dict[str, Any] = {}
    for 內, 外 in 對照:
        底下 = _這一格底下是誰(欄型[內])
        出[外] = _一層鍵樹(底下, _子對照[底下]) if 底下 is not None else {}
    return 出


def 落盤鍵樹() -> dict[str, Any]:
    """契約自己說得出落盤長什麼形狀：ASCII 鍵 → 那一格底下的鍵樹（純量是 `{}`）。

    **不帶參數**：形狀是契約的事，不是某一份儀表板的事。今天沒有線在跑、
    帳本還沒有失敗碼的時候，`lanes`／`failure_codes` 底下有哪幾格照樣說得出來。

    有了這個，「儀表板有哪幾格」就只說一次：測試與模板都問這裡，
    不必各自手抄一份 ASCII 鍵名單——**三份手抄本一起漏一格，三邊照樣相等**，
    而那一格會從 `--json` 上安靜地消失。
    """
    return _一層鍵樹(儀表板, _欄位對照)


def 儀表板轉字典(一份: 儀表板) -> dict[str, Any]:
    """落盤／`--json` 用的形狀。**`None` 的格子照樣落盤**。

    跟 `成果轉字典` 不同：那邊 `None` 整格不落，這裡不行——
    頂層鍵集合就是「儀表板有哪幾格」，少一格代表模板上安靜地不見一個數字。
    """
    _每一張對照表都蓋滿了嗎()
    return {外: _攤平(getattr(一份, 內)) for 內, 外 in _欄位對照}
