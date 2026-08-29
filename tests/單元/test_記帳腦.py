"""記帳腦：包住一顆腦，把「叫了誰、花多少、怎麼收場」記進帳本。

假腦＋`StringIO`，所以不碰網路也不碰磁碟，住單元層。

**兩條保證最值錢**：

1. 記帳腦要包在接力鏈的**裡面**（一顆腦一層）。包在外面的話，
   「第一顆掛了換第二顆」整段會壓成一筆——而那正是最需要看見的事。
2. 帳本裡**沒有模型全文**。repo 是 public，遮罩機制還不存在。
"""

import io
import json
from contextlib import suppress
from typing import Any

from nova.契約.帳本 import 事件種類
from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局
from nova.契約.角色 import 呼叫選項, 權限, 語言模型, 預設選項
from nova.載體.帳本 import 帳本, 建帳本
from nova.載體.模型.接力 import 接力腦
from nova.載體.模型.記帳 import 記帳每一顆, 記帳腦


class 假腦:
    """回固定答案的一顆腦。`要爆` 用來驗「例外也要留下結束事件」。"""

    def __init__(self, 名: str, 答: 回應 | None = None, *, 要爆: bool = False) -> None:
        """`答` 不給就回一個成功的預設。"""
        self._名 = 名
        self._答 = 答 or 做回應()
        self._要爆 = 要爆

    @property
    def 名稱(self) -> str:
        return self._名

    def 詢問(self, 提示: str, *, 選項: 呼叫選項 = 預設選項) -> 回應:
        del 提示, 選項
        if self._要爆:
            msg = "腦炸了"
            raise RuntimeError(msg)
        return self._答


def 做回應(
    文字: str = "ok",
    終: 終局 = 終局.成功,
    代碼: 失敗代碼 = 失敗代碼.無,
) -> 回應:
    return 回應(
        文字=文字,
        終局=終,
        失敗代碼=代碼,
        原始結束碼=0,
        對話識別碼=None,
        用量=用量(輸入token=100, 輸出token=7),
    )


def 建() -> tuple[io.StringIO, 帳本]:
    串流 = io.StringIO()
    return 串流, 建帳本(串流, 執行識別碼="r1", 現在=lambda: "t")


def 讀事件(串流: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(行) for 行 in 串流.getvalue().splitlines()]


class Test成對事件:
    def test_成功會留下開始與結束(self) -> None:
        串流, 帳 = 建()
        記帳腦(內層=假腦("codex"), 帳=帳).詢問("在嗎")
        事件們 = 讀事件(串流)
        assert [事["event"] for 事 in 事件們] == [
            事件種類.呼叫開始.value,
            事件種類.呼叫結束.value,
        ]
        assert {事["call"] for 事 in 事件們} == {1}

    def test_開始事件在呼叫之前就寫掉(self) -> None:
        """被逾時殺掉時結束事件永遠不會寫出來——那時候只剩開始事件可看。"""
        串流, 帳 = 建()
        腦 = 記帳腦(內層=假腦("codex", 要爆=True), 帳=帳)
        with suppress(RuntimeError):
            腦.詢問("在嗎")
        assert 讀事件(串流)[0]["event"] == 事件種類.呼叫開始.value

    def test_腦炸了也要留下結束事件(self) -> None:
        """例外不是「沒發生」。少了結束事件，事後看起來像卡在那裡沒回來。"""
        串流, 帳 = 建()
        腦 = 記帳腦(內層=假腦("codex", 要爆=True), 帳=帳)
        with suppress(RuntimeError):
            腦.詢問("在嗎")
        結束 = 讀事件(串流)[-1]
        assert 結束["event"] == 事件種類.呼叫結束.value
        assert 結束["outcome"] == 終局.結果未知.value

    def test_例外照樣往上丟(self) -> None:
        """記帳不准把例外吃掉——吞掉就變成假的成功。"""
        串流, 帳 = 建()
        腦 = 記帳腦(內層=假腦("codex", 要爆=True), 帳=帳)
        炸了 = False
        try:
            腦.詢問("在嗎")
        except RuntimeError:
            炸了 = True
        assert 炸了


class Test記了什麼:
    def test_記下家與模型與權限(self) -> None:
        串流, 帳 = 建()
        腦 = 記帳腦(內層=假腦("codex"), 帳=帳)
        腦.詢問("在嗎", 選項=呼叫選項(模型="gpt-5.6-sol", 權限=權限.可編輯))
        開始 = 讀事件(串流)[0]
        assert 開始["family"] == "codex"
        assert 開始["model"] == "gpt-5.6-sol"
        assert 開始["permission"] == 權限.可編輯.value

    def test_記下token與失敗代碼(self) -> None:
        串流, 帳 = 建()
        腦 = 記帳腦(內層=假腦("agy", 做回應("", 終局.結果未知, 失敗代碼.逾時)), 帳=帳)
        腦.詢問("在嗎")
        結束 = 讀事件(串流)[-1]
        assert 結束["input_tokens"] == 100
        assert 結束["output_tokens"] == 7
        assert 結束["failure_code"] == 失敗代碼.逾時.value

    def test_有耗時(self) -> None:
        """沒有耗時就分不出「一秒就掛」與「跑滿三十分鐘被殺」。"""
        串流, 帳 = 建()
        記帳腦(內層=假腦("codex"), 帳=帳).詢問("在嗎")
        assert 讀事件(串流)[-1]["duration_ms"] >= 0

    def test_不准把模型全文寫進去(self) -> None:
        """repo 是 public，而遮罩機制還不存在。只記長度與雜湊。"""
        句 = "紫色的犀牛在星期二吃了會計師的午餐"
        串流, 帳 = 建()
        記帳腦(內層=假腦("codex", 做回應(句)), 帳=帳).詢問("在嗎")
        assert 句 not in 串流.getvalue()
        結束 = 讀事件(串流)[-1]
        assert 結束["text_len"] == len(句)
        assert 結束["text_sha256"]

    def test_提示也不准寫進去(self) -> None:
        句 = "我的密碼是螢火蟲七號"
        串流, 帳 = 建()
        記帳腦(內層=假腦("codex"), 帳=帳).詢問(句)
        assert 句 not in 串流.getvalue()


class Test包在接力鏈裡面:
    def test_每一顆各有一對事件(self) -> None:
        """包在鏈外面的話，這裡只會看到一對——換腦這件事整個消失。"""
        串流, 帳 = 建()
        壞的 = 假腦("codex", 做回應("不行", 終局.確定失敗, 失敗代碼.用法錯誤))
        鏈 = 接力腦(名稱="鏈", 腦們=記帳每一顆((壞的, 假腦("agy")), 帳))
        答 = 鏈.詢問("在嗎")
        assert 答.終局 is 終局.成功
        事件們 = 讀事件(串流)
        assert len(事件們) == 4
        assert [事.get("attempt") for 事 in 事件們] == [1, 1, 2, 2]
        assert [事.get("family") for 事 in 事件們] == ["codex", "codex", "agy", "agy"]

    def test_編號不會撞(self) -> None:
        """每顆腦各數自己的話，兩顆都會叫自己第一號，配對就爛了。"""
        串流, 帳 = 建()
        壞的 = 假腦("codex", 做回應("不行", 終局.確定失敗, 失敗代碼.用法錯誤))
        接力腦(名稱="鏈", 腦們=記帳每一顆((壞的, 假腦("agy")), 帳)).詢問("在嗎")
        assert [事["call"] for 事 in 讀事件(串流)] == [1, 1, 2, 2]

    def test_只有一顆也照樣編號(self) -> None:
        串流, 帳 = 建()
        (腦,) = 記帳每一顆((假腦("codex"),), 帳)
        腦.詢問("在嗎")
        assert 讀事件(串流)[0]["attempt"] == 1


def test_名稱要透出來() -> None:
    """包一層之後名字變了的話，接力鏈印出來的「試過誰」就會變成包裝的名字。"""
    _, 帳 = 建()
    assert 記帳腦(內層=假腦("codex"), 帳=帳).名稱 == "codex"


def test_記帳腦是一顆腦() -> None:
    """里氏替換：它要能塞進任何吃 `語言模型` 的地方。"""
    _, 帳 = 建()
    assert isinstance(記帳腦(內層=假腦("codex"), 帳=帳), 語言模型)
