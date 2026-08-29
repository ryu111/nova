"""帳本真的接上生產路徑了沒。

只有這一層驗得出「門面與 CLI 會不會記帳」——單元層的測試都是自己
手動組裝 `記帳腦`，組裝得再對也證明不了**正式路徑上有人組裝它**。
這正是「墊片證明的是轉遞形狀，不是可達性」那條判準。

全部用假 CLI，不燒 token。
"""

import json
from collections.abc import Callable
from pathlib import Path

import nova
from nova.載體.命令列 import 主程式
from nova.載體.帳本 import 預設帳本目錄

#: `做假CLI` fixture 的形狀。**各檔自己寫一份**——跨檔 import 會撞上
#: mypy 的「同一個檔算成兩個模組」（測試目錄沒有 `__init__.py`）。
#: 只有兩處重複，還沒到三次法則該抽的時候。
做假CLI型 = Callable[..., tuple[Path, Path]]


def 讀帳本(目錄: Path) -> list[dict[str, object]]:
    (檔,) = list(目錄.glob("*.jsonl"))
    return [json.loads(行) for 行 in 檔.read_text(encoding="utf-8").splitlines()]


class Test門面:
    def test_不給帳本目錄就不記帳(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        """函式庫不准偷偷往使用者家目錄寫東西。要記帳就明講在哪。

        斷言看的是 `預設帳本目錄()` 不是 `tmp_path`——**原本看 tmp_path，
        於是「門面永遠開帳本」那個負控完全沒紅**，真的寫了 73 個檔到家目錄。
        （`帳本不准寫到家目錄` fixture 已經把預設目錄導進暫存區。）
        """
        假, _ = 做假CLI()
        nova.問("在嗎", 用="claude", 執行檔=假, 工作目錄=tmp_path)
        assert not 預設帳本目錄().exists()

    def test_給了就記(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        假, _ = 做假CLI()
        帳本目錄 = tmp_path / "帳"
        nova.問("在嗎", 用="claude", 執行檔=假, 帳本目錄=帳本目錄)
        assert [事["event"] for 事 in 讀帳本(帳本目錄)] == ["call_started", "call_finished"]

    def test_接力的每一顆都記到(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        """`記帳每一顆` 有沒有真的被門面用上——沒用上就只會有一對事件。"""
        壞的 = tmp_path / "壞的"
        壞的.write_text("#!/bin/sh\nexit 2\n")
        壞的.chmod(0o755)
        好的, _ = 做假CLI("agy")
        帳本目錄 = tmp_path / "帳"
        nova.問("在嗎", 用="codex,agy", 執行檔={"codex": 壞的, "agy": 好的}, 帳本目錄=帳本目錄)
        事件們 = 讀帳本(帳本目錄)
        assert [事.get("attempt") for 事 in 事件們] == [1, 1, 2, 2]
        assert [事.get("family") for 事 in 事件們] == ["codex", "codex", "agy", "agy"]

    def test_派工把七個階段都記下來(
        self, tmp_path: Path, 做假CLI: 做假CLI型, 翻牌判準: Path
    ) -> None:
        做事的, _ = 做假CLI("codex")
        審查的, _ = 做假CLI("agy", "agy_review_pass.json")
        帳本目錄 = tmp_path / "帳"
        nova.派工(
            "做點事",
            用="codex",
            審查用="agy",
            工作目錄=tmp_path,
            判準指令=[str(翻牌判準)],
            執行檔=做事的,
            審查執行檔=審查的,
            帳本目錄=帳本目錄,
        )
        階段們 = [事["stage"] for 事 in 讀帳本(帳本目錄) if 事["event"] == "stage_finished"]
        assert 階段們 == [
            *["test", "verify-red", "impl", "verify-green"],
            *["refactor", "verify-refactor", "review"],
        ]

    def test_派工的模型呼叫也記到(self, tmp_path: Path, 做假CLI: 做假CLI型, 翻牌判準: Path) -> None:
        """階段與呼叫是兩層，都要有——只記階段就看不出換過腦。"""
        做事的, _ = 做假CLI("codex")
        審查的, _ = 做假CLI("agy", "agy_review_pass.json")
        帳本目錄 = tmp_path / "帳"
        nova.派工(
            "做點事",
            用="codex",
            審查用="agy",
            工作目錄=tmp_path,
            判準指令=[str(翻牌判準)],
            執行檔=做事的,
            審查執行檔=審查的,
            帳本目錄=帳本目錄,
        )
        種類們 = {事["event"] for 事 in 讀帳本(帳本目錄)}
        assert {"stage_started", "stage_finished", "call_started", "call_finished"} == 種類們


class TestCLI:
    def test_問預設就記帳(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        """CLI 是程式不是函式庫——程式留執行紀錄是正常的，而且不留就沒人有帳本。"""
        假, _ = 做假CLI()
        帳本目錄 = tmp_path / "帳"
        碼 = 主程式(
            ["問", "--用", "claude", "--執行檔", str(假), "--帳本目錄", str(帳本目錄), "在嗎"]
        )
        assert 碼 == 0
        assert [事["event"] for 事 in 讀帳本(帳本目錄)] == ["call_started", "call_finished"]

    def test_不記帳關得掉(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        假, _ = 做假CLI()
        帳本目錄 = tmp_path / "帳"
        主程式(
            [
                "問",
                "--用",
                "claude",
                "--執行檔",
                str(假),
                "--帳本目錄",
                str(帳本目錄),
                "--不記帳",
                "在嗎",
            ]
        )
        assert not 帳本目錄.exists()
