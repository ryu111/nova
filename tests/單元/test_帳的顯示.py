"""成本要看得到，不然它只是躺在檔案裡的一個欄位。

`nova 帳本` 與 `nova 已處理` 是成本唯一的出口。這三支組字串的函式是純函式，
所以住單元層——顯示壞掉跟加總壞掉是兩件事，各自要有人守。

**沒有這幾支，「顯示」那一半完全沒有測試背書**：加總對了但印不出來，
從使用者的角度看跟沒做一樣。
"""

from nova.契約.帳本 import 一家的帳, 摘要
from nova.契約.成果 import 成果
from nova.載體.命令列 import _一次的細節, _一行成果, _一行摘要


def _一家(供應商: str, 成本: float | None) -> 一家的帳:
    return 一家的帳(
        供應商=供應商,
        次數=1,
        成功=1,
        失敗=0,
        未知=0,
        輸入token=100,
        輸出token=10,
        成本美金=成本,
    )


def _摘要(總成本: float | None, *各家: 一家的帳) -> 摘要:
    return 摘要(
        執行識別碼="20260830T091500Z-abc",
        起="t1",
        迄="t2",
        各家=各家,
        階段們=(),
        沒收尾的呼叫=(),
        壞掉的行=0,
        總token=110,
        總成本美金=總成本,
    )


def _成果(總成本: float | None) -> 成果:
    return 成果(
        執行識別碼="20260830T091500Z-abc",
        任務="做一件事",
        收場="完成",
        退出碼=0,
        起="t1",
        迄="t2",
        走了幾階=5,
        總token=110,
        總成本美金=總成本,
    )


class Test帳本那一行:
    def test_有成本就印出來(self) -> None:
        assert "US$0.3000" in _一行摘要(_摘要(0.3, _一家("claude", 0.3)))

    def test_沒有成本就不印(self) -> None:
        """**不准印成 US$0.0000。** 那會讓「沒人給成本」看起來像「免費」。"""
        行 = _一行摘要(_摘要(None, _一家("codex", None)))

        assert "US$" not in 行, 行


class Test一次的細節:
    def test_每一家的成本與總計都印(self) -> None:
        """**兩個地方都要印。** 只印總計的話，看不出是哪一家花掉的。"""
        文 = _一次的細節(_摘要(0.3, _一家("claude", 0.3)))

        assert 文.count("US$0.3000") == 2, 文

    def test_給不出成本的那一家不印金額(self) -> None:
        文 = _一次的細節(_摘要(None, _一家("claude", 0.3), _一家("codex", None)))

        assert "US$0.3000" in 文, "claude 那一家的成本還是要印"
        assert 文.count("US$") == 1, f"總計不該印，codex 也不該印：{文}"


class Test成果那一行:
    def test_有成本就印出來(self) -> None:
        assert "US$0.3000" in _一行成果(_成果(0.3))

    def test_沒有成本就不印(self) -> None:
        assert "US$" not in _一行成果(_成果(None))
