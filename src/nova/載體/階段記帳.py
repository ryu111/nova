"""記帳執行器：把工作流每一個階段記進帳本。

跟 `載體/模型/記帳.py` 的 `記帳腦` 是同一組保證的兩半：

| 這一層記 | 回答的問題 |
|---|---|
| `記帳腦`（一次模型呼叫） | 叫了誰、花多少、怎麼收場 |
| `記帳執行器`（一個階段） | 走到哪、紅還是綠、審查給了什麼判定 |

兩層都要：一個階段可能包含好幾次模型呼叫（接力），只記階段看不出換過腦；
只記呼叫看不出「這是驗證紅還是審查」。

**住載體不住迴圈**：迴圈在載體裡面，內層不該相依外層。`迴圈/` 目前只 import
`契約/`，這一層包住它，所以 import 方向是對的。
"""

from collections.abc import Callable
from hashlib import sha256
from time import monotonic

from nova.契約.工作流 import (
    任務,
    執行器,
    步驟結果,
    階段代碼,
    階段定義,
    預設單次最多token,
)
from nova.契約.帳本 import 事件, 事件種類
from nova.契約.模型回應 import 終局
from nova.載體.帳本 import 帳本

_雜湊長度 = 16


def 記帳執行器(
    內層: 執行器,
    帳: 帳本,
    *,
    單次最多token: int = 預設單次最多token,
) -> 執行器:
    """包住一個執行器，前後各記一筆。**不改結果**——改了狀態機就走錯路。

    開始事件寫在跑之前：階段跑到一半被殺掉時，結束事件永遠不會寫出來，
    那時候唯一能回答「卡在哪一步」的就是開始事件。
    """

    def 執行一步(定義: 階段定義, 任: 任務, 軌跡: tuple[步驟結果, ...]) -> 步驟結果:
        編號 = 帳.新呼叫編號()
        帳.記一筆(事件(種類=事件種類.階段開始, 呼叫編號=編號, 階段=定義.代碼.value))
        起 = monotonic()
        結果: 步驟結果 | None = None
        try:
            結果 = 內層(定義, 任, 軌跡)
        finally:
            帳.記一筆(
                _結束事件(
                    編號,
                    定義,
                    結果,
                    round((monotonic() - 起) * 1000),
                    單次最多token=單次最多token,
                )
            )
        return 結果

    setattr(執行一步, "__wrapped__", 內層)  # noqa: B010 —— 保留內層執行器供解包
    return 執行一步


def 建記跳過(帳: 帳本) -> Callable[[階段代碼], None]:
    """做一支「這一階這一次跳過了」的記帳函式，交給 `跑工作流` 的 `記跳過`。

    迴圈不准 import 載體，所以帳那一筆由這一層做好再注入進去（高層宣告形狀、低層符合）。

    **不帶 `呼叫編號`**：跳過不成對，帶了編號 `帳本讀取` 的配對會 pop 掉別人的開著事件。
    """

    def 記跳過(代碼: 階段代碼) -> None:
        帳.記一筆(事件(種類=事件種類.階段跳過, 階段=代碼.value))

    return 記跳過


def _結束事件(
    編號: int,
    定義: 階段定義,
    結果: 步驟結果 | None,
    耗時: int,
    *,
    單次最多token: int = 預設單次最多token,
) -> 事件:
    """`結果 is None` ＝ 內層丟了例外，那是**結果未知**不是確定失敗。"""
    花費 = 結果.花費 if 結果 else None
    超標 = True if (花費 is not None and 花費.新鮮token > 單次最多token) else None
    return 事件(
        種類=事件種類.階段結束,
        呼叫編號=編號,
        階段=定義.代碼.value,
        終局=(結果.終局 if 結果 else 終局.結果未知).value,
        判準綠=結果.判準綠 if 結果 else None,
        審查結論=結果.審查結論.value if 結果 and 結果.審查結論 else None,
        輸入token=花費.輸入token if 花費 else None,
        輸出token=花費.輸出token if 花費 else None,
        耗時毫秒=耗時,
        等待毫秒=結果.等待毫秒 if 結果 else None,
        文字長度=len(結果.證據) if 結果 else None,
        文字雜湊=_指紋(結果.證據) if 結果 else None,
        單次token超標=超標,
    )


def _指紋(文字: str) -> str:
    return sha256(文字.encode("utf-8")).hexdigest()[:_雜湊長度]
