"""記帳腦：包住一顆腦，把每一次呼叫記進帳本。

**組合，不是繼承**（`軟體工程.md`）：它持有一顆腦，自己也是一顆腦，
所以可以塞進任何吃 `語言模型` 的位置——包括接力鏈裡面。

## 為什麼要包在接力鏈的裡面

```
包在外面（錯）                     包在裡面（對）
記帳腦( 接力腦(codex, agy) )       接力腦( 記帳腦(codex), 記帳腦(agy) )
   └ 一對事件                          └ 兩對事件，各帶 attempt
   「換過腦」這件事整段消失            看得出第一顆為什麼被換掉
```

換腦的原因（上一顆的失敗代碼）正是事後最想知道的事。包在外面等於
把它丟掉，而且丟得沒有痕跡。

## 不記全文

repo 是 public，遮罩機制還不存在。提示與回應都可能夾著路徑、
內部名詞甚至憑證。只記 `文字長度` 與雜湊前綴——回答得了
「這次跟上次一不一樣」，回答不了「它說了什麼」。要看內容就去看
模型自己的 session（那是各家 CLI 的事，不是帳本的）。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from time import monotonic

from nova.契約.帳本 import 事件, 事件種類
from nova.契約.模型回應 import 回應, 終局
from nova.契約.角色 import 呼叫選項, 語言模型, 預設選項
from nova.載體.帳本 import 帳本

#: 雜湊取前 16 個十六進位字元。用途是「跟上次一不一樣」，
#: 不是密碼學上的抗碰撞——完整的 64 字元只是讓每行更難讀。
_雜湊長度 = 16


def _指紋(文字: str) -> str:
    return sha256(文字.encode("utf-8")).hexdigest()[:_雜湊長度]


@dataclass(frozen=True, slots=True)
class 記帳腦:
    """一顆腦 ＋ 一本帳。名稱直接透出內層——包了一層不該換掉身分。"""

    內層: 語言模型
    帳: 帳本
    #: 接力鏈的第幾顆（從 1 起算）。單獨用的時候是 None。
    接力第幾顆: int | None = None

    @property
    def 名稱(self) -> str:
        """內層那顆腦叫什麼。包一層不換身分，否則接力鏈印出來的「試過誰」會變成包裝的名字。"""
        return self.內層.名稱

    def 詢問(self, 提示: str, *, 選項: 呼叫選項 = 預設選項) -> 回應:
        """問一次，前後各記一筆。

        **開始事件在呼叫之前就寫掉**：程序被逾時殺掉時結束事件永遠不會寫出來，
        那時候唯一能回答「誰正在跑」的就是開始事件。

        結束事件寫在 `finally`：腦丟例外也要留下痕跡，否則事後看起來
        像是卡在那裡沒回來。例外照樣往上丟——吞掉就是假的成功。
        """
        編號 = self.帳.新呼叫編號()
        self.帳.記一筆(
            事件(
                種類=事件種類.呼叫開始,
                呼叫編號=編號,
                供應商=self.名稱,
                模型=選項.模型,
                權限=選項.權限.value,
                接力第幾顆=self.接力第幾顆,
            )
        )
        起 = monotonic()
        答: 回應 | None = None
        try:
            答 = self.內層.詢問(提示, 選項=選項)
        finally:
            self.帳.記一筆(self._結束事件(編號, 答, round((monotonic() - 起) * 1000)))
        return 答

    def _結束事件(self, 編號: int, 答: 回應 | None, 耗時: int) -> 事件:
        """收尾那一筆。

        `答 is None` ＝ 內層丟了例外。那是**結果未知**不是確定失敗——
        例外可能發生在請求出門之後，副作用可能已經產生了。
        """
        return 事件(
            種類=事件種類.呼叫結束,
            呼叫編號=編號,
            供應商=self.名稱,
            接力第幾顆=self.接力第幾顆,
            終局=(答.終局 if 答 else 終局.結果未知).value,
            失敗代碼=答.失敗代碼.value if 答 else None,
            輸入token=答.用量.輸入token if 答 else None,
            輸出token=答.用量.輸出token if 答 else None,
            成本美金=答.用量.成本美金 if 答 else None,
            耗時毫秒=耗時,
            文字長度=len(答.文字) if 答 else None,
            文字雜湊=_指紋(答.文字) if 答 else None,
        )


def 記帳每一顆(腦們: Sequence[語言模型], 帳: 帳本) -> tuple[語言模型, ...]:
    """把一串腦各包一層，順便編好 `接力第幾顆`。

    存在的理由是**別讓呼叫端自己數**：手寫索引遲早會錯一格，
    而錯一格的帳本看起來完全正常。
    """
    return tuple(記帳腦(內層=腦, 帳=帳, 接力第幾顆=序) for 序, 腦 in enumerate(腦們, start=1))
