"""門面額度 API 整合測試：透過假 CLI 驗證 nova.額度()、callback 叫用時機與快取機制。

會 fork 子程序的一律放在整合層。
"""

import stat
import sys
from pathlib import Path

import pytest

import nova
from nova import 家族額度, 視窗, 額度, 額度快照
from nova.載體.額度 import 額度快取路徑

# 假 codex 實作 app-server JSON-RPC 2.0 協議
假codex內容 = f"""#!{sys.executable}
import json, sys

if len(sys.argv) > 1 and sys.argv[1] == "app-server":
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except Exception:
            continue
        req_id = req.get("id")
        method = req.get("method")
        if method == "initialize":
            res = {{"jsonrpc": "2.0", "id": req_id, "result": {{"capabilities": {{}}}}}}
            sys.stdout.write(json.dumps(res) + "\\n")
            sys.stdout.flush()
        elif method == "initialized":
            notice = {{
                "jsonrpc": "2.0",
                "method": "remoteControl/status/changed",
                "params": {{"status": "idle"}},
            }}
            sys.stdout.write(json.dumps(notice) + "\\n")
            sys.stdout.flush()
        elif method == "account/rateLimits/read":
            resp = {{
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {{
                    "rateLimits": {{
                        "limitId": "codex",
                        "planType": "prolite",
                        "primary": {{
                            "usedPercent": 18,
                            "windowDurationMins": 10080,
                            "resetsAt": 1788452826,
                        }},
                        "secondary": None,
                    }}
                }}
            }}
            sys.stdout.write(json.dumps(resp) + "\\n")
            sys.stdout.flush()
"""

# 假 agy 實作 -p "/usage"
假agy內容 = f"""#!{sys.executable}
import sys

if "-p" in sys.argv and "/usage" in sys.argv:
    output = (
        "Gemini Models\\tWeekly Limit Remaining\\t89%\\t2026-09-03T19:05:42Z\\n"
        "Gemini Models\\tFive Hour Limit Remaining\\t80%\\t2026-08-29T18:09:43Z\\n"
        "Claude and GPT models\\tWeekly Limit Remaining\\t100%\\t2026-09-05T16:37:38Z\\n"
        "Claude and GPT models\\tFive Hour Limit Remaining\\t100%\\t2026-08-29T21:37:38Z\\n"
    )
    sys.stdout.write(output)
    sys.stdout.flush()
    sys.exit(0)
"""

# 會失敗的假 CLI
假CLI失敗內容 = f"""#!{sys.executable}
import sys
sys.stderr.write("連線逾時或認證失敗\\n")
sys.exit(1)
"""

# 假 CLI 的記數版：每被叫一次就往 $額度呼叫紀錄 追加一行。
假codex記數內容 = f"""#!{sys.executable}
import json, os, sys

with open(os.environ["額度呼叫紀錄"], "a") as f:
    f.write("codex\\n")

if len(sys.argv) > 1 and sys.argv[1] == "app-server":
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except Exception:
            continue
        if req.get("method") == "account/rateLimits/read":
            sys.stdout.write(json.dumps({{
                "jsonrpc": "2.0", "id": req.get("id"),
                "result": {{"rateLimits": {{"limitId": "codex", "secondary": None,
                    "primary": {{"usedPercent": 18, "windowDurationMins": 10080,
                                 "resetsAt": 1788452826}}}}}},
            }}) + "\\n")
            sys.stdout.flush()
"""

假agy記數內容 = f"""#!{sys.executable}
import os, sys

with open(os.environ["額度呼叫紀錄"], "a") as f:
    f.write("agy\\n")

sys.stdout.write("Gemini Models\\tFive Hour Limit Remaining\\t80%\\t2026-08-29T18:09:43Z\\n")
sys.stdout.flush()
"""


@pytest.fixture
def 假執行檔們(tmp_path: Path) -> dict[str, Path]:
    目錄 = tmp_path / "bin"
    目錄.mkdir(parents=True, exist_ok=True)

    codex = 目錄 / "fake-codex"
    codex.write_text(假codex內容, encoding="utf-8")
    codex.chmod(codex.stat().st_mode | stat.S_IEXEC)

    agy = 目錄 / "fake-agy"
    agy.write_text(假agy內容, encoding="utf-8")
    agy.chmod(agy.stat().st_mode | stat.S_IEXEC)

    壞codex = 目錄 / "fake-bad-codex"
    壞codex.write_text(假CLI失敗內容, encoding="utf-8")
    壞codex.chmod(壞codex.stat().st_mode | stat.S_IEXEC)

    壞agy = 目錄 / "fake-bad-agy"
    壞agy.write_text(假CLI失敗內容, encoding="utf-8")
    壞agy.chmod(壞agy.stat().st_mode | stat.S_IEXEC)

    return {"codex": codex, "agy": agy, "bad_codex": 壞codex, "bad_agy": 壞agy}


class Test額度門面:
    def test_門面匯出符號(self) -> None:
        """確認 __all__ 包含額度相關匯出項目。"""
        assert "額度" in nova.__all__
        assert "額度快照" in nova.__all__
        assert "家族額度" in nova.__all__
        assert "視窗" in nova.__all__

    def test_查詢成功回傳完整快照(
        self,
        假執行檔們: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        狀態目錄 = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(狀態目錄))
        monkeypatch.setattr(
            "nova.載體.模型.轉接.找執行檔",
            lambda 家, **_: 假執行檔們["codex"] if 家 == "codex" else 假執行檔們["agy"],
        )

        快照 = 額度()
        assert isinstance(快照, 額度快照)
        assert isinstance(快照.時間, int)
        assert len(快照.家族們) == 2

        家族表 = {家.家: 家 for 家 in 快照.家族們}
        assert "codex" in 家族表
        assert "agy" in 家族表

        cx = 家族表["codex"]
        assert cx.失敗原因 is None
        assert cx.視窗們 == (視窗(標籤="7d", 用掉百分比=18, 重置於=1788452826),)

        ay = 家族表["agy"]
        assert ay.失敗原因 is None
        assert len(ay.視窗們) == 2
        assert ay.視窗們[0].標籤 == "5h"
        assert ay.視窗們[0].用掉百分比 == 20
        assert ay.視窗們[1].標籤 == "7d"
        assert ay.視窗們[1].用掉百分比 == 11

    def test_每家回呼在兩家都問完之前就被叫第一次(
        self,
        假執行檔們: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """證明 callback 在拿到第一家結果時立刻呼叫，此時快取檔尚未寫出。"""
        狀態目錄 = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(狀態目錄))
        monkeypatch.setattr(
            "nova.載體.模型.轉接.找執行檔",
            lambda 家, **_: 假執行檔們["codex"] if 家 == "codex" else 假執行檔們["agy"],
        )

        快取檔 = 額度快取路徑()
        收到紀錄: list[tuple[str, bool]] = []

        def 記錄回呼(家族: 家族額度) -> None:
            收到紀錄.append((家族.家, 快取檔.exists()))

        快照 = 額度(每家=記錄回呼)
        assert len(收到紀錄) == 2, "每家 callback 必須被叫兩次"
        assert 收到紀錄[0][0] == "codex"
        assert 收到紀錄[0][1] is False, "第一次回呼時快取檔不該存在（寫快取是最後一步）"
        assert 收到紀錄[1][0] == "agy"
        assert 快取檔.is_file(), "全部查詢完畢後快取檔必須已寫入"
        assert len(快照.家族們) == 2

    def test_每家回呼拋出例外時吞掉例外並跑完查詢(
        self,
        假執行檔們: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """外面傳進來的 callback 炸掉不准把整個查詢帶走。"""
        狀態目錄 = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(狀態目錄))
        monkeypatch.setattr(
            "nova.載體.模型.轉接.找執行檔",
            lambda 家, **_: 假執行檔們["codex"] if 家 == "codex" else 假執行檔們["agy"],
        )

        被叫次數 = 0

        def 炸開的回呼(_: 家族額度) -> None:
            nonlocal 被叫次數
            被叫次數 += 1
            錯誤訊息 = "外部 callback 拋出例外"
            raise RuntimeError(錯誤訊息)

        快照 = 額度(每家=炸開的回呼)
        assert 被叫次數 == 2, "即使第一次回呼拋出例外，第二家仍應被查詢並呼叫"
        assert len(快照.家族們) == 2, "回傳之快照應完整"

    def test_部分失敗時快照包含失敗原因(
        self,
        假執行檔們: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """失敗的那家在快照裡失敗原因不是 None、視窗們為空。"""
        狀態目錄 = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(狀態目錄))
        monkeypatch.setattr(
            "nova.載體.模型.轉接.找執行檔",
            lambda 家, **_: 假執行檔們["codex"] if 家 == "codex" else 假執行檔們["bad_agy"],
        )

        收到的家族們: list[家族額度] = []
        快照 = 額度(每家=收到的家族們.append)

        assert len(快照.家族們) == 2
        家族表 = {家.家: 家 for 家 in 快照.家族們}

        assert 家族表["codex"].失敗原因 is None
        assert len(家族表["codex"].視窗們) == 1

        assert 家族表["agy"].失敗原因 is not None
        assert 家族表["agy"].視窗們 == ()

        assert len(收到的家族們) == 2
        assert 收到的家族們[1].家 == "agy"
        assert 收到的家族們[1].失敗原因 is not None


class Test節流與快取讀取:
    """測試最舊秒大於快取年紀時不重新向 CLI 發出查詢，直接回傳快照並觸發 callback。"""

    def _裝記數的假CLI(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        目錄 = tmp_path / "bin"
        目錄.mkdir(parents=True, exist_ok=True)
        紀錄 = tmp_path / "呼叫紀錄.txt"
        monkeypatch.setenv("額度呼叫紀錄", str(紀錄))
        for 名, 內容 in (("codex", 假codex記數內容), ("agy", 假agy記數內容)):
            檔 = 目錄 / f"count-{名}"
            檔.write_text(內容, encoding="utf-8")
            檔.chmod(檔.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setattr(
            "nova.載體.模型.轉接.找執行檔",
            lambda 家, **_: 目錄 / f"count-{家 if 家 in ('codex', 'agy') else 'codex'}",
        )
        return 紀錄

    def test_最舊秒大於快取年紀時不重新向CLI查詢(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        紀錄 = self._裝記數的假CLI(tmp_path, monkeypatch)

        快照1 = 額度(最舊秒=900)
        第一次次數 = 紀錄.read_text(encoding="utf-8").count("\n")
        assert 第一次次數 == 2, "第一次無快取，應查詢兩家"

        收到的家族: list[str] = []
        快照2 = 額度(最舊秒=900, 每家=lambda 家族: 收到的家族.append(家族.家))
        第二次次數 = 紀錄.read_text(encoding="utf-8").count("\n")

        assert 第二次次數 == 第一次次數, "快取還新時不准再去問 CLI"
        assert 收到的家族 == ["codex", "agy"], "從快取讀取仍須觸發每家回呼"
        assert len(快照2.家族們) == len(快照1.家族們)
