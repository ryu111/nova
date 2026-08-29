"""記帳腦：包住一顆腦，把「叫了誰、花多少、怎麼收場」記進帳本。

假腦＋`StringIO`，所以不碰網路也不碰磁碟，住單元層。

**兩條保證最值錢**：

1. 記帳腦要包在接力鏈的**裡面**（一顆腦一層）。包在外面的話，
   「第一顆掛了換第二顆」整段會壓成一筆——而那正是最需要看見的事。
2. 帳本裡的模型全文**一定是遮罩過的**，而提示一個字都不記——
   兩者不對稱是刻意的，理由在 `test_提示還是不准寫進去`。
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
from nova.載體.模型.記帳 import 文字上限, 記帳每一顆, 記帳腦


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
    成本: float | None = None,
) -> 回應:
    return 回應(
        文字=文字,
        終局=終,
        失敗代碼=代碼,
        原始結束碼=0,
        對話識別碼=None,
        用量=用量(輸入token=100, 輸出token=7, 成本美金=成本),
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

    def test_記下成本(self) -> None:
        """只有 claude 給得出來。丟掉它，帳本就永遠答不出「花了多少錢」。"""
        串流, 帳 = 建()
        記帳腦(內層=假腦("claude", 做回應(成本=0.0456)), 帳=帳).詢問("在嗎")
        assert 讀事件(串流)[-1]["cost_usd"] == 0.0456

    def test_有耗時(self) -> None:
        """沒有耗時就分不出「一秒就掛」與「跑滿三十分鐘被殺」。"""
        串流, 帳 = 建()
        記帳腦(內層=假腦("codex"), 帳=帳).詢問("在嗎")
        assert 讀事件(串流)[-1]["duration_ms"] >= 0

    def test_模型全文會記進去(self) -> None:
        """**這條保證跟以前相反，因為遮罩做出來了。**

        以前的規則是「只記長度與雜湊」，理由是 repo public 而遮罩不存在。
        遮罩存在之後，那個理由消失了——而「它說了什麼」是帳本唯一答不出來的問題
        （路線圖 ③ journal.記）。長度與雜湊仍然照記：截斷之後還是要看得出原本多長。
        """
        句 = "紫色的犀牛在星期二吃了會計師的午餐"
        串流, 帳 = 建()

        記帳腦(內層=假腦("codex", 做回應(句)), 帳=帳).詢問("在嗎")

        結束 = 讀事件(串流)[-1]
        assert 結束["text"] == 句
        assert 結束["text_len"] == len(句)
        assert 結束["text_sha256"]
        assert 結束["redactions"] == 0

    def test_全文裡的祕密進不了帳本(self) -> None:
        """**這支才是遮罩存在的理由。** 沒有它，上面那支等於把外洩路徑打開。"""
        假金鑰 = "AKIAIOSFODNN7EXAMPLE"
        串流, 帳 = 建()

        記帳腦(內層=假腦("codex", 做回應(f"我讀到 {假金鑰} 這串")), 帳=帳).詢問("在嗎")

        assert 假金鑰 not in 串流.getvalue()
        assert 讀事件(串流)[-1]["redactions"] == 1

    def test_太長的全文會截斷但長度還是原始長度(self) -> None:
        """帳本是 append-only 的 jsonl，一筆 100KB 會讓它變成不能 tail 的東西。

        **截斷要看得出來**：`text_len` 仍是原始長度，另外掛一個截斷旗標。
        少了那兩格，截斷過的全文會長得像模型只講了這麼多。
        """
        句 = "很長" * 20000
        串流, 帳 = 建()

        記帳腦(內層=假腦("codex", 做回應(句)), 帳=帳).詢問("在嗎")

        結束 = 讀事件(串流)[-1]
        assert len(結束["text"]) < len(句)
        assert 結束["text_len"] == len(句)
        assert 結束["text_truncated"] is True

    def test_遮罩要在截斷之前(self) -> None:
        """**順序反過來會漏半個祕密。**

        祕密剛好跨在截斷邊界上時：先截斷的話，前半段原封不動留在帳本裡，
        而且看起來完全正常（後半段不見了，像是模型只講了這麼多）。
        先遮罩的話整串變成一個標記，怎麼截都不會露。

        這一支守的是 `_遮過再截斷` 的順序——那句話原本只寫在 docstring 裡。
        """
        金鑰 = "AKIAIOSFODNN7EXAMPLE"
        句 = "填" * (文字上限 - 10) + 金鑰 + " 尾巴"
        串流, 帳 = 建()

        記帳腦(內層=假腦("codex", 做回應(句)), 帳=帳).詢問("在嗎")

        寫下去的 = 串流.getvalue()
        for 長 in range(8, len(金鑰) + 1):
            assert 金鑰[:長] not in 寫下去的, f"洩了金鑰的前 {長} 個字"

    def test_明講不記全文時只剩長度與雜湊(self) -> None:
        """改預設不等於拿掉退路。想關掉的人要關得掉。"""
        句 = "紫色的犀牛在星期二吃了會計師的午餐"
        串流, 帳 = 建()

        記帳腦(內層=假腦("codex", 做回應(句)), 帳=帳, 記全文=False).詢問("在嗎")

        assert 句 not in 串流.getvalue()
        結束 = 讀事件(串流)[-1]
        assert "text" not in 結束
        assert 結束["text_len"] == len(句)

    def test_提示還是不准寫進去(self) -> None:
        """**提示跟回應不對稱，這是刻意的。**

        路線圖那一格說的是「它說的話」——模型的輸出。提示裡有前情、有進度檔、
        有 nova 自己組進去的檔案內容，外洩面大得多，而且它答不了
        「模型說了什麼」那個問題。所以只開回應這一邊。
        """
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
