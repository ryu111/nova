"""記帳執行器：把工作流每一個階段記進帳本。

假執行器＋`StringIO`，零 LLM 零子程序。

跟 `記帳腦` 是同一組保證的另一半：腦那層回答「叫了誰、花多少」，
階段這層回答「走到哪、紅還是綠、審查給了什麼判定」。
"""

import io
import json
from contextlib import suppress
from typing import Any

from nova.契約.工作流 import (
    任務,
    出口標籤,
    審查判定,
    步驟結果,
    種類,
    結束,
    結束代碼,
    階段代碼,
    階段定義,
)
from nova.契約.帳本 import 事件種類
from nova.契約.模型回應 import 用量, 終局
from nova.載體.帳本 import 帳本, 建帳本
from nova.載體.階段記帳 import 記帳執行器

一個階段 = 階段定義(
    代碼=階段代碼.實作,
    名稱="實作",
    種類=種類.模型,
    期望綠=None,
    出口={
        出口標籤.綠: 階段代碼.驗證綠,
        出口標籤.結果未知: 結束(結束代碼.護欄, "結果未知"),
        出口標籤.確定失敗: 結束(結束代碼.中止, "做不出來"),
    },
)


def 建() -> tuple[io.StringIO, 帳本]:
    串流 = io.StringIO()
    return 串流, 建帳本(串流, 執行識別碼="r1", 現在=lambda: "t")


def 讀事件(串流: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(行) for 行 in 串流.getvalue().splitlines()]


def 做步驟(證據: str = "做完了", 結論: 審查判定 | None = None) -> 步驟結果:
    return 步驟結果(
        階段=階段代碼.實作,
        終局=終局.成功,
        判準綠=None,
        證據=證據,
        審查結論=結論,
        花費=用量(輸入token=50, 輸出token=3),
    )


def 跑一次(帳: 帳本, 結果: 步驟結果) -> 步驟結果:
    def 內層(定義: 階段定義, 任: 任務, 軌跡: tuple[步驟結果, ...]) -> 步驟結果:
        del 定義, 任, 軌跡
        return 結果

    包好的 = 記帳執行器(內層, 帳)
    return 包好的(一個階段, 任務(描述="做點事", 工作目錄=None), ())  # type: ignore[arg-type]


class Test成對事件:
    def test_一個階段留下開始與結束(self) -> None:
        串流, 帳 = 建()
        跑一次(帳, 做步驟())
        assert [事["event"] for 事 in 讀事件(串流)] == [
            事件種類.階段開始.value,
            事件種類.階段結束.value,
        ]

    def test_共用一個編號(self) -> None:
        串流, 帳 = 建()
        跑一次(帳, 做步驟())
        assert {事["call"] for 事 in 讀事件(串流)} == {1}

    def test_執行器炸了也要留下結束事件(self) -> None:
        """少了結束事件，事後看起來像卡在那個階段沒回來。"""

        def 會爆(定義: 階段定義, 任: 任務, 軌跡: tuple[步驟結果, ...]) -> 步驟結果:
            del 定義, 任, 軌跡
            msg = "階段爆了"
            raise RuntimeError(msg)

        串流, 帳 = 建()
        with suppress(RuntimeError):
            記帳執行器(會爆, 帳)(一個階段, 任務(描述="x", 工作目錄=None), ())  # type: ignore[arg-type]
        結束 = 讀事件(串流)[-1]
        assert 結束["event"] == 事件種類.階段結束.value
        assert 結束["outcome"] == 終局.結果未知.value


class Test記了什麼:
    def test_記下階段名(self) -> None:
        串流, 帳 = 建()
        跑一次(帳, 做步驟())
        assert 讀事件(串流)[0]["stage"] == 階段代碼.實作.value

    def test_記下token(self) -> None:
        串流, 帳 = 建()
        跑一次(帳, 做步驟())
        結束 = 讀事件(串流)[-1]
        assert (結束["input_tokens"], 結束["output_tokens"]) == (50, 3)

    def test_記下審查判定(self) -> None:
        """審查的驗收權在判定上。帳本沒記判定，事後就分不出通過與沒給結論。"""
        串流, 帳 = 建()
        跑一次(帳, 做步驟(結論=審查判定.要求修改))
        assert 讀事件(串流)[-1]["verdict"] == 審查判定.要求修改.value

    def test_判準綠是布林不是省略(self) -> None:
        串流, 帳 = 建()
        判準結果 = 步驟結果(階段=階段代碼.驗證紅, 終局=終局.成功, 判準綠=False, 證據="紅了")
        跑一次(帳, 判準結果)
        assert 讀事件(串流)[-1]["gate_green"] is False

    def test_證據不准寫全文(self) -> None:
        """證據是模型講的話。repo 是 public，只記長度與雜湊。"""
        句 = "紫色的犀牛在星期二吃了會計師的午餐"
        串流, 帳 = 建()
        跑一次(帳, 做步驟(證據=句))
        assert 句 not in 串流.getvalue()
        assert 讀事件(串流)[-1]["text_len"] == len(句)


def test_回傳值原樣透出() -> None:
    """包一層不准改結果——改了工作流的狀態機就走錯路。"""
    _, 帳 = 建()
    結果 = 做步驟()
    assert 跑一次(帳, 結果) is 結果
