"""帳本寫出去的行為。用 `StringIO` 當串流，所以不碰磁碟、住單元層。

真的寫檔、真的被 SIGKILL 的那幾支在 `tests/整合/test_帳本落盤.py`。

**最重要的一條在 `Test帳本壞掉`**：記帳失敗不准把已經成功的呼叫變成失敗。
模型呼叫的副作用**已經發生**了，這時候丟例外會讓上游以為沒做，
於是重跑——那正是 at-most-once 要擋的事。帳本壞掉是可觀測性的損失，
不是工作的損失，兩者不准混為一談。
"""

import io
import json
from pathlib import Path
from typing import Any

import pytest

from nova.契約.帳本 import 事件, 事件種類, 落盤時加的鍵
from nova.載體.帳本 import 不記帳本, 建帳本, 預設帳本目錄


class 會爆的串流(io.StringIO):
    """寫就爆。模擬磁碟滿、fd 被關掉這一類。"""

    def write(self, s: str) -> int:
        del s
        msg = "磁碟滿了"
        raise OSError(msg)


def 讀出來(串流: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(行) for 行 in 串流.getvalue().splitlines()]


class Test落盤形狀:
    def test_一筆就是一行JSON(self) -> None:
        串流 = io.StringIO()
        帳 = 建帳本(串流, 執行識別碼="r1", 現在=lambda: "2026-08-29T00:00:00Z")
        帳.記一筆(事件(種類=事件種類.呼叫開始, 供應商="codex"))
        (行,) = 讀出來(串流)
        assert 行 == {
            "run": "r1",
            "seq": 1,
            "ts": "2026-08-29T00:00:00Z",
            "event": "call_started",
            "family": "codex",
        }

    def test_沒填的欄位不落盤(self) -> None:
        """補 null 會讓「沒這個概念」跟「值是空的」長得一樣。"""
        串流 = io.StringIO()
        帳 = 建帳本(串流, 執行識別碼="r1", 現在=lambda: "t")
        帳.記一筆(事件(種類=事件種類.呼叫開始))
        (行,) = 讀出來(串流)
        assert set(行) == {*落盤時加的鍵, "event"}

    def test_鍵一律ASCII(self) -> None:
        """中文鍵在 shell 與 jq 裡很難用，而且這個檔是給別的程式讀的。"""
        串流 = io.StringIO()
        帳 = 建帳本(串流, 執行識別碼="r1", 現在=lambda: "t")
        帳.記一筆(
            事件(
                種類=事件種類.呼叫結束,
                供應商="agy",
                終局="success",
                輸入token=10,
                輸出token=2,
                耗時毫秒=1234,
                文字長度=5,
                文字雜湊="abcd",
            )
        )
        (行,) = 讀出來(串流)
        assert all(鍵.isascii() for 鍵 in 行), 行

    def test_序號從1開始遞增(self) -> None:
        """沒有序號就分不出「順序」與「檔案被截斷過」。"""
        串流 = io.StringIO()
        帳 = 建帳本(串流, 執行識別碼="r1", 現在=lambda: "t")
        for _ in range(3):
            帳.記一筆(事件(種類=事件種類.呼叫開始))
        assert [行["seq"] for 行 in 讀出來(串流)] == [1, 2, 3]

    def test_中文值原樣寫不轉義(self) -> None:
        """`ensure_ascii=True` 會把中文轉成跳脫序列，人就讀不動了。"""
        串流 = io.StringIO()
        帳 = 建帳本(串流, 執行識別碼="r1", 現在=lambda: "t")
        帳.記一筆(事件(種類=事件種類.階段開始, 階段="驗證紅"))
        assert "驗證紅" in 串流.getvalue()


class Test呼叫編號:
    def test_成對的事件共用一個編號(self) -> None:
        """靠相鄰兩行配對，一遇到接力（巢狀）就對不起來。"""
        串流 = io.StringIO()
        帳 = 建帳本(串流, 執行識別碼="r1", 現在=lambda: "t")
        編 = 帳.新呼叫編號()
        帳.記一筆(事件(種類=事件種類.呼叫開始, 呼叫編號=編))
        帳.記一筆(事件(種類=事件種類.呼叫開始, 呼叫編號=帳.新呼叫編號()))
        帳.記一筆(事件(種類=事件種類.呼叫結束, 呼叫編號=編))
        assert [行["call"] for 行 in 讀出來(串流)] == [1, 2, 1]

    def test_編號是遞增的(self) -> None:
        串流 = io.StringIO()
        帳 = 建帳本(串流, 執行識別碼="r1", 現在=lambda: "t")
        assert [帳.新呼叫編號() for _ in range(3)] == [1, 2, 3]


class Test帳本壞掉:
    """副作用發生**之後**的記帳失敗一律 fail-open，但要大聲。"""

    def test_寫不進去不准往上丟(self) -> None:
        """丟例外會讓上游以為模型呼叫失敗，於是重跑一件可能已經做過的事。"""
        帳 = 建帳本(會爆的串流(), 執行識別碼="r1", 現在=lambda: "t")
        帳.記一筆(事件(種類=事件種類.呼叫結束))  # 不准 raise

    def test_壞掉要印到stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        """靜默地不記帳＝以後看著空帳本以為「那次沒發生」。"""
        帳 = 建帳本(會爆的串流(), 執行識別碼="r1", 現在=lambda: "t")
        帳.記一筆(事件(種類=事件種類.呼叫結束))
        assert "帳本" in capsys.readouterr().err

    def test_只吵一次(self, capsys: pytest.CaptureFixture[str]) -> None:
        """磁碟滿的時候每一筆都會失敗。每筆都印會把真正的輸出洗掉。"""
        帳 = 建帳本(會爆的串流(), 執行識別碼="r1", 現在=lambda: "t")
        for _ in range(5):
            帳.記一筆(事件(種類=事件種類.呼叫結束))
        assert capsys.readouterr().err.count("帳本") == 1


class Test不記帳本:
    def test_吃得下任何事件(self) -> None:
        """「不開帳本」要跟「開了帳本」形狀完全一樣，呼叫端才不必寫 if。"""
        帳 = 不記帳本()
        帳.記一筆(事件(種類=事件種類.呼叫開始))

    def test_編號照樣發(self) -> None:
        """不記帳也要發得出編號——否則呼叫端得分兩條路寫。"""
        帳 = 不記帳本()
        assert 帳.新呼叫編號() != 帳.新呼叫編號()


class Test成本:
    """claude 是三家裡唯一給得出美金成本的。**寫進帳本的那一刻不要把它丟掉。**

    這條是 workflow 研究抓到的：`用量.成本美金` 存在，但 `契約/帳本.py` 的
    事件沒有對應欄位，於是唯一的一手成本數字在記帳時蒸發。
    帳本回答得了「花多少 token」，回答不了「花多少錢」——而那兩個不是同一件事
    （不同家、不同型號的單價差很多）。
    """

    def test_成本落得了盤(self) -> None:
        串流 = io.StringIO()
        帳 = 建帳本(串流, 執行識別碼="r1", 現在=lambda: "t")
        帳.記一筆(事件(種類=事件種類.呼叫結束, 供應商="claude", 成本美金=0.0123))
        (行,) = 讀出來(串流)
        assert 行["cost_usd"] == 0.0123

    def test_沒有成本就不落盤(self) -> None:
        """codex 與 agy 給不出成本。補一個 0 會讓「沒這個概念」跟「免費」長得一樣。"""
        串流 = io.StringIO()
        帳 = 建帳本(串流, 執行識別碼="r1", 現在=lambda: "t")
        帳.記一筆(事件(種類=事件種類.呼叫結束, 供應商="agy"))
        assert "cost_usd" not in 讀出來(串流)[0]


class Test帳本要按專案分:
    """「屬於某個專案」跟「存在那個專案裡面」是兩件事。

    帳本原本是全域的：`~/.local/state/nova/帳本/`，所有專案的執行混在一起。
    實測 2026-08-29，86 次執行躺在同一個目錄裡，分不出哪次是在哪個專案跑的。

    **存在專案外面是對的**（模型摸不到，而且帳本裡有不該進版控的東西），
    但那只解了完整性那條軸，沒解歸屬那條：
    nova 用到新專案時，那個專案的紀錄應該歸那個專案。

    解法是把「屬於哪個專案」當成**索引**問題而不是**存放位置**問題——
    存在專案外面、用專案當鍵，兩件事同時成立。
    """

    def test_不同專案的帳本不會混在一起(self, tmp_path: Path) -> None:
        甲 = 預設帳本目錄(tmp_path / "專案甲")
        乙 = 預設帳本目錄(tmp_path / "專案乙")
        assert 甲 != 乙

    def test_同一個專案永遠是同一個目錄(self, tmp_path: Path) -> None:
        """不然每跑一次就開一個新目錄，等於沒有跨執行的歷史。"""
        assert 預設帳本目錄(tmp_path / "甲") == 預設帳本目錄(tmp_path / "甲")

    def test_相對路徑與絕對路徑指同一個專案(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**沒解析成絕對路徑就等於沒分對**——`.` 跟完整路徑會被當成兩個專案。"""
        專案 = tmp_path / "甲"
        專案.mkdir()
        monkeypatch.chdir(專案)
        assert 預設帳本目錄(Path()) == 預設帳本目錄(專案)

    def test_目錄名看得出是哪個專案(self, tmp_path: Path) -> None:
        """純雜湊看不出是誰的帳。**要人查得動**——那是帳本存在的理由。"""
        專案 = tmp_path / "某個專案"
        assert "某個專案" in str(預設帳本目錄(專案))

    def test_不落在專案裡面(self, tmp_path: Path) -> None:
        """**歸屬換了，完整性不准跟著換掉。** 落在專案裡模型就摸得到。"""
        專案 = tmp_path / "甲"
        專案.mkdir()
        assert 專案.resolve() not in 預設帳本目錄(專案).resolve().parents
