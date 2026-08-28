"""可抽換的兩個形狀：腦（語言模型）與角色。

用 `Protocol`（結構型）不用基底類別：只要形狀對就能替換，被替換的那方
不必知道我們存在。這是 `軟體工程.md` 的多型條目，也是 mypy strict 唯一
能機械檢查「里氏替換」與「介面隔離」的方式。
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path as 路徑
from typing import Protocol, runtime_checkable

from nova.契約.模型回應 import 回應


class 權限(StrEnum):
    """執行者能動到什麼。

    **刻意漏出到呼叫端**，不由介面決定：藏起來就是幫使用者做風險決策。
    預設一律 `唯讀`——最嚴的那一邊當預設，忘了設不會變成放行。
    """

    唯讀 = "read-only"
    可編輯 = "write"


#: 預設逾時 30 分鐘。**刻意設得很寬**，理由是不對稱：
#:
#: 逾時 → `結果未知` → 可編輯模式下接力當場停、不准換腦（可能已經改了檔案）。
#: 也就是說**砍太早不只是慢，是把可回復的工作變成不可回復的歧義**。
#: 反過來，等太久的代價只是等——而且高階模型與高推理強度本來就慢。
#:
#: 要短就在呼叫端明講，不要靠改這個預設。
預設逾時秒 = 1800.0


@dataclass(frozen=True, slots=True)
class 呼叫選項:
    """一次呼叫的旋鈕。

    收成一個物件不是為了好看——參數超過五個時 ruff `PLR0913` 會紅，
    而那條規則說的是對的：一長串具名參數會讓呼叫端很難看出漏了哪個。
    """

    模型: str | None = None
    工作目錄: 路徑 | None = None
    逾時秒: float = 預設逾時秒
    #: 預設最嚴的那一邊——忘了設不會變成放行。
    權限: 權限 = 權限.唯讀
    #: 要不要把使用者家目錄的設定擋在外面。
    #:
    #: 預設 True，因為 nova 的行為該由 nova 決定——讀了 `~/.claude/CLAUDE.md`，
    #: nova[claude] 就會跟 nova[codex] 行為不同，「換腦但行為一樣」當場破功。
    #:
    #: **代價（實測）**：claude 的 `--bare` 連 keychain 與 OAuth 都不讀，
    #: 訂閱登入會變成「Not logged in」。要嘛設 `ANTHROPIC_API_KEY`，
    #: 要嘛把這個關掉（改用 `--restricted`：設定檔照樣隔離，但 CLAUDE.md 仍會被讀）。
    隔離設定: bool = True


#: 全部走預設的那一組。凍結的資料類別當預設值是安全的（不可變，不會被共用改壞）。
預設選項 = 呼叫選項()


@runtime_checkable
class 語言模型(Protocol):
    """一顆腦。提示進去、結構化證據出來。

    這是 nova 對「llm」的全部要求——刻意做到最小，因為介面的基準形狀是
    本地模型（只有腦），不是自帶一整套載體的 claude／codex／agy。
    """

    @property
    def 名稱(self) -> str:
        """哪一家。用唯讀屬性宣告，凍結的資料類別才裝得進來（里氏替換：唯讀是較弱的要求）。"""
        ...

    def 詢問(self, 提示: str, *, 選項: 呼叫選項 = ...) -> 回應:
        """問一次，回結構化證據。"""
        ...


@runtime_checkable
class 角色(Protocol):
    """一個固定身分的執行者：固定的系統提示 ＋ 一顆可換的腦。

    「角色」是身分不是腦——換腦不換角色，這就是宿主反轉在這一層的樣子。
    """

    @property
    def 名稱(self) -> str:
        """這個角色叫什麼。唯讀，理由同 `語言模型.名稱`。"""
        ...

    def 做(self, 提示: str, *, 工作目錄: 路徑 | None = ...) -> 回應:
        """以這個角色的身分做一件事。"""
        ...
