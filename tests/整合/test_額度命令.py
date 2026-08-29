"""額度查詢整合測試：透過假 CLI 驗證 JSON-RPC app-server 與 /usage 的端到端整合。

會 fork 子程序的一律放在整合層。
"""

import json
import stat
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from nova.載體.命令列 import 主程式

做假CLI型 = Callable[..., tuple[Path, Path]]

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
            # 夾雜通知雜訊
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


class Test額度命令整合:
    def test_兩家都成功時寫出快取檔且退出碼為0(
        self,
        假執行檔們: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        狀態目錄 = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(狀態目錄))
        monkeypatch.setattr(
            "nova.載體.模型.轉接.找執行檔",
            lambda 家, **_: 假執行檔們["codex"] if 家 == "codex" else 假執行檔們["agy"],
        )

        碼 = 主程式(["額度"])
        assert 碼 == 0

        快取檔 = 狀態目錄 / "nova" / "額度" / "快取.json"
        assert 快取檔.is_file(), "快取檔必須被建立"

        資料 = json.loads(快取檔.read_text(encoding="utf-8"))
        assert "ts" in 資料 and isinstance(資料["ts"], int)
        assert "families" in 資料

        家族字典 = {f["family"]: f["windows"] for f in 資料["families"]}
        assert "cx" in 家族字典
        assert "ay" in 家族字典

        assert 家族字典["cx"] == [{"label": "7d", "used_percent": 18, "resets_at": 1788452826}]
        assert len(家族字典["ay"]) == 2
        assert 家族字典["ay"][0]["label"] == "7d"
        assert 家族字典["ay"][0]["used_percent"] == 11
        assert 家族字典["ay"][1]["label"] == "5h"
        assert 家族字典["ay"][1]["used_percent"] == 20

        擷取 = capsys.readouterr()
        assert "codex" in 擷取.err or "cx" in 擷取.err
        assert "agy" in 擷取.err or "ay" in 擷取.err

    def test_只有一家能問到時檔案裡只有那一家且退出碼是1(
        self,
        假執行檔們: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        """誠實規則：問不到就不要寫那一家，不准補 0%，但成功的那家仍要寫入，退出碼為 1。"""
        狀態目錄 = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(狀態目錄))
        monkeypatch.setattr(
            "nova.載體.模型.轉接.找執行檔",
            lambda 家, **_: 假執行檔們["codex"] if 家 == "codex" else 假執行檔們["bad_agy"],
        )

        碼 = 主程式(["額度"])
        assert 碼 == 1

        快取檔 = 狀態目錄 / "nova" / "額度" / "快取.json"
        assert 快取檔.is_file(), "成功的那家仍然要寫入檔案"

        資料 = json.loads(快取檔.read_text(encoding="utf-8"))
        家族清單 = [f["family"] for f in 資料["families"]]
        assert "cx" in 家族清單
        assert "ay" not in 家族清單, "失敗的 agy 絕對不准出現在快取中，不准補 0%"

        擷取 = capsys.readouterr()
        assert "失敗" in 擷取.err or "bad" in 擷取.err

    def test_兩家都失敗時退出碼是1(
        self,
        假執行檔們: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        狀態目錄 = tmp_path / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(狀態目錄))
        monkeypatch.setattr(
            "nova.載體.模型.轉接.找執行檔",
            lambda 家, **_: 假執行檔們["bad_codex"] if 家 == "codex" else 假執行檔們["bad_agy"],
        )

        碼 = 主程式(["額度"])
        assert 碼 == 1
