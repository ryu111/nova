"""閘每跑一條規則就記一筆——這是「哪條規則在守東西」唯一的資料來源。

Fowler 在〈sensors〉裡問過「如果 sensors 從來不觸發，那是品質高還是偵測不夠」，
她自己的答法逐字是：

> "So I started **logging a history of sensor states every time they were checked**,
> to get some data."

而那份歷史回答得了：失敗頻率的趨勢（指引或模型在進步）、**從來不失敗的感測器
＝不必要的訊號**、常失敗的規則＝該補指引的地方。

nova 的零件早就齊了（帳本會寫、讀取端有 `收斂`），**唯一缺的就是閘不寫帳本**。
這支測試把那條線接上。
"""

import io
import json
from typing import Any

from nova.契約.帳本 import 事件種類
from nova.載體.帳本 import 帳本, 建帳本
from nova.載體.閘 import 規則, 跑閘


def 建() -> tuple[io.StringIO, 帳本]:
    串流 = io.StringIO()
    return 串流, 建帳本(串流, 執行識別碼="r1", 現在=lambda: "t")


def 讀(串流: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(行) for 行 in 串流.getvalue().splitlines()]


def 做規則(代碼: str, *, 通過: bool = True) -> 規則:
    return 規則(
        代碼=代碼,
        名稱=代碼,
        閘點=frozenset({"提交"}),
        負責層="載體",
        檢查=lambda: (通過, "證據"),
    )


class Test成對事件:
    def test_一條規則留下開始與結束(self) -> None:
        串流, 帳 = 建()
        跑閘("提交", [做規則("lint")], 帳=帳)
        assert [事["event"] for 事 in 讀(串流)] == [
            事件種類.規則開始.value,
            事件種類.規則結束.value,
        ]

    def test_記下規則代碼與閘點(self) -> None:
        """沒有規則代碼就統計不出「哪一條」；沒有閘點就分不出提交閘與 CI。"""
        串流, 帳 = 建()
        跑閘("提交", [做規則("lint")], 帳=帳)
        開始 = 讀(串流)[0]
        assert (開始["rule"], 開始["gate_point"]) == ("lint", "提交")

    def test_記下紅綠(self) -> None:
        串流, 帳 = 建()
        跑閘("提交", [做規則("lint", 通過=False)], 帳=帳)
        assert 讀(串流)[-1]["gate_green"] is False

    def test_規則自己爆了也要記(self) -> None:
        """爆掉算紅（fail-closed）。不記的話那條規則在統計裡永遠看起來很乖。"""

        def 會爆() -> tuple[bool, str]:
            msg = "壞了"
            raise RuntimeError(msg)

        壞規則 = 規則(代碼="壞的", 名稱="壞的", 閘點=frozenset({"提交"}), 負責層="載體", 檢查=會爆)
        串流, 帳 = 建()
        跑閘("提交", [壞規則], 帳=帳)
        assert 讀(串流)[-1]["gate_green"] is False

    def test_提前停止之後沒跑的不准記(self) -> None:
        """沒跑就是沒跑。補一筆會讓觸發率統計把「沒輪到」算成「通過」。"""
        串流, 帳 = 建()
        跑閘("提交", [做規則("a", 通過=False), 做規則("b")], 帳=帳, 提前停止=True)
        assert {事["rule"] for 事 in 讀(串流)} == {"a"}


def test_不給帳本也要跑得動() -> None:
    """記帳是可觀測性，不是閘的職責。忘了給帳本不該讓閘不能跑。"""
    assert len(跑閘("提交", [做規則("lint")])) == 1
