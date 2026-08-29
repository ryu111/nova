"""讀取端：把一串事件收斂成一次執行的摘要。

純函式（吃字串序列、吐資料類別），所以住單元層。真的讀檔與 CLI 在
`tests/整合/test_帳本讀取端.py`。

**沒有讀取端的帳本只是寫檔案給沒人看**——路線圖第 4 項的措辭是
「沒有讀取端就不准宣稱補了 State」。這一層就是那個讀取端。
"""

import json

import pytest

from nova.載體.帳本讀取 import 收斂


def 事件行(**欄位: object) -> str:
    return json.dumps(欄位, ensure_ascii=False)


def _一次呼叫(編號: int, 家: str, *, 成本: float | None = None) -> list[str]:
    """一對成對事件。`成本=None` 代表那一家沒回報成本（codex 與 agy 就是這樣）。"""
    收尾: dict[str, object] = {
        "run": "r",
        "seq": 編號 * 2,
        "ts": f"t{編號 * 2}",
        "event": "call_finished",
        "call": 編號,
        "family": 家,
        "outcome": "success",
        "input_tokens": 100,
        "output_tokens": 10,
    }
    if 成本 is not None:
        收尾["cost_usd"] = 成本
    return [
        事件行(
            run="r",
            seq=編號 * 2 - 1,
            ts=f"t{編號 * 2 - 1}",
            event="call_started",
            call=編號,
            family=家,
        ),
        事件行(**收尾),
    ]


def 呼叫(編號: int, 家: str, 終局: str = "success", 入: int = 100, 出: int = 7) -> list[str]:
    return [
        事件行(run="r", seq=編號 * 2 - 1, ts="t1", event="call_started", call=編號, family=家),
        事件行(
            run="r",
            seq=編號 * 2,
            ts="t2",
            event="call_finished",
            call=編號,
            family=家,
            outcome=終局,
            input_tokens=入,
            output_tokens=出,
        ),
    ]


class Test基本統計:
    def test_空的帳本不會爆(self) -> None:
        果 = 收斂([])
        assert 果.總token == 0
        assert 果.各家 == ()

    def test_一次成功呼叫(self) -> None:
        果 = 收斂(呼叫(1, "codex"))
        (家,) = 果.各家
        assert (家.供應商, 家.次數, 家.成功) == ("codex", 1, 1)
        assert 果.總token == 107

    def test_兩家分開算(self) -> None:
        果 = 收斂([*呼叫(1, "codex", "failed"), *呼叫(2, "agy")])
        assert {家.供應商: 家.成功 for 家 in 果.各家} == {"codex": 0, "agy": 1}
        assert {家.供應商: 家.失敗 for 家 in 果.各家} == {"codex": 1, "agy": 0}

    def test_結果未知單獨一格(self) -> None:
        """未知不准併進失敗——那兩者的重試政策相反。"""
        果 = 收斂(呼叫(1, "codex", "unknown"))
        (家,) = 果.各家
        assert (家.失敗, 家.未知) == (0, 1)

    def test_執行識別碼與起迄(self) -> None:
        果 = 收斂(呼叫(1, "codex"))
        assert (果.執行識別碼, 果.起, 果.迄) == ("r", "t1", "t2")


class Test成本統計:
    def test_有成本與沒成本混在一起時總成本應為None(self) -> None:
        """缺一筆成本就整個不給，不能只加上有回報的那一筆。"""
        行們 = [
            事件行(run="r", seq=1, ts="t1", event="call_started", call=1, family="claude"),
            事件行(
                run="r",
                seq=2,
                ts="t2",
                event="call_finished",
                call=1,
                family="claude",
                outcome="success",
                input_tokens=100,
                output_tokens=10,
                cost_usd=0.25,
            ),
            事件行(run="r", seq=3, ts="t3", event="call_started", call=2, family="codex"),
            事件行(
                run="r",
                seq=4,
                ts="t4",
                event="call_finished",
                call=2,
                family="codex",
                outcome="success",
                input_tokens=200,
                output_tokens=20,
            ),
        ]

        果 = 收斂(行們)

        assert 果.總成本美金 is None

    def test_全部都有成本時總成本是加總(self) -> None:
        """**這支是上一支的另一半。**

        只守「混著的時候是 None」的話，一個永遠回 None 的實作也會綠——
        那等於成本從來沒被讀出來過，而且看起來完全正常。
        """
        行們 = [
            *_一次呼叫(1, "claude", 成本=0.25),
            *_一次呼叫(2, "claude", 成本=0.75),
        ]

        果 = 收斂(行們)

        assert 果.總成本美金 == 1.0

    def test_同一家的多筆成本會累加(self) -> None:
        """只記最後一筆或只記第一筆都會低報，而低報看起來像個數字。"""
        果 = 收斂([*_一次呼叫(1, "claude", 成本=0.1), *_一次呼叫(2, "claude", 成本=0.2)])

        (那一家,) = 果.各家
        assert 那一家.成本美金 == pytest.approx(0.3)

    def test_一家有成本另一家沒有時只有沒有的那家是None(self) -> None:
        """家族層級也要分得開——不然看不出「是誰沒給」。"""
        果 = 收斂([*_一次呼叫(1, "claude", 成本=0.5), *_一次呼叫(2, "codex")])

        依家 = {家.供應商: 家.成本美金 for 家 in 果.各家}
        assert 依家 == {"claude": 0.5, "codex": None}

    def test_完全沒有成本時總成本也是None(self) -> None:
        """跟「混著」同樣回 None，但**理由不同**，所以分開守。

        混著是「有資料但不完整」，全都沒有是「這次根本沒有人給成本」。
        把兩者合成一支測試的話，實作只要處理其中一種就會綠。
        """
        果 = 收斂([*_一次呼叫(1, "codex"), *_一次呼叫(2, "agy")])

        assert 果.總成本美金 is None
        assert all(家.成本美金 is None for 家 in 果.各家)


class Test階段:
    def test_階段照順序列出來(self) -> None:
        行們 = [
            事件行(run="r", seq=1, ts="t", event="stage_started", call=1, stage="test"),
            事件行(run="r", seq=2, ts="t", event="stage_finished", call=1, stage="test"),
            事件行(run="r", seq=3, ts="t", event="stage_started", call=2, stage="impl"),
            事件行(run="r", seq=4, ts="t", event="stage_finished", call=2, stage="impl"),
        ]
        assert 收斂(行們).階段們 == ("test", "impl")

    def test_階段的token不准重複算(self) -> None:
        """階段結束帶的 token 是它裡面那幾次呼叫的加總——兩邊都加就變兩倍。"""
        行們 = [
            事件行(run="r", seq=1, ts="t", event="stage_started", call=1, stage="impl"),
            *呼叫(2, "codex"),
            事件行(
                run="r",
                seq=4,
                ts="t",
                event="stage_finished",
                call=1,
                stage="impl",
                input_tokens=100,
                output_tokens=7,
            ),
        ]
        assert 收斂(行們).總token == 107


class Test沒收尾的呼叫:
    def test_只有開始沒有結束要抓出來(self) -> None:
        """這是被殺掉的證據。少了它，帳本看起來就像那次呼叫沒發生過。"""
        行們 = [事件行(run="r", seq=1, ts="t", event="call_started", call=9, family="codex")]
        assert 收斂(行們).沒收尾的呼叫 == (9,)

    def test_成對的不算(self) -> None:
        assert 收斂(呼叫(1, "codex")).沒收尾的呼叫 == ()

    def test_階段也算(self) -> None:
        行們 = [事件行(run="r", seq=1, ts="t", event="stage_started", call=3, stage="impl")]
        assert 收斂(行們).沒收尾的呼叫 == (3,)


class Test壞掉的行:
    def test_不是JSON的行要跳過不要爆(self) -> None:
        """失敗模型明講不防「磁碟滿留下半行」，所以讀取端必須跳得過。

        整份讀不動比少一行糟得多——那等於一次磁碟意外洗掉整次執行的證據。
        """
        果 = 收斂(["{半行", *呼叫(1, "codex")])
        assert 果.壞掉的行 == 1
        assert 果.總token == 107

    def test_沒有event欄位的也算壞行(self) -> None:
        果 = 收斂([事件行(run="r", seq=1, ts="t")])
        assert 果.壞掉的行 == 1

    def test_空白行不算壞行(self) -> None:
        """檔尾的換行不是損壞。"""
        assert 收斂(["", "  "]).壞掉的行 == 0

    def test_認不得的事件種類算壞行(self) -> None:
        """fail-closed：默默忽略會讓「格式改過了」看起來像「那次沒發生」。"""
        果 = 收斂([事件行(run="r", seq=1, ts="t", event="future_event")])
        assert 果.壞掉的行 == 1
