"""`nova 檢查編輯`：agent hook 叫的那一支。

## 它跟 `檢查指令` 剛好相反，而且是刻意的

| | `檢查指令`（禁令） | `檢查編輯`（預設走 nova） |
|---|---|---|
| 守什麼 | 不可逆的動作（繞過閘門、跳過 required check） | 一個**預設值**（該不該把工作丟給 nova） |
| 讀不懂輸入時 | **fail-closed**，擋下來 | **fail-open**，放行 |
| 怎麼擋 | 退出碼 2 | **印 JSON**，退出碼永遠 0 |

為什麼這一支非 fail-open 不可：它掛在 `Edit`／`Write` 上，
而**修 nova 的唯一辦法就是編輯 nova 的檔案**。fail-closed 的話，
nova 一壞（import 錯、venv 沒建好、uv 不見了）就再也修不回來——
今晚真的發生過兩次（那次掛在 `Bash` 上，還能用 Edit 逃出來；
這一支掛在 Edit 上，沒有逃生口）。

**所以擋不擋不看退出碼，只看它有沒有印出那段 JSON。**
`uv run` 自己失敗時也會回非零，跟「故意擋下」在退出碼上分不開；
改用 JSON 之後，只有 nova 真的開口說話才擋得住。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

nova執行檔 = Path(sys.executable).parent / "nova"


def _跑(*參數: str, 餵: str, 狀態: Path, 在: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=在,
        input=餵,
        env={**os.environ, "XDG_STATE_HOME": str(狀態)},
        capture_output=True,
        text=True,
        check=False,
    )


def _問一次(
    路徑: Path, *, 會話: str = "s-1", 狀態: Path, 專案: Path
) -> subprocess.CompletedProcess[str]:
    載荷 = json.dumps(
        {"session_id": 會話, "tool_name": "Edit", "tool_input": {"file_path": str(路徑)}}
    )
    return _跑("檢查編輯", "--stdin", 餵=載荷, 狀態=狀態, 在=專案)


def _擋了嗎(跑完: subprocess.CompletedProcess[str]) -> bool:
    """**只看 JSON，不看退出碼**——退出碼在這一支永遠是 0。"""
    try:
        說 = json.loads(跑完.stdout)
    except json.JSONDecodeError:
        return False
    if not isinstance(說, dict):
        return False
    細 = 說.get("hookSpecificOutput")
    return isinstance(細, dict) and 細.get("permissionDecision") == "deny"


@pytest.fixture
def 佈景(tmp_path: Path) -> tuple[Path, Path]:
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    (專案 / "src").mkdir(parents=True)
    return 狀態, 專案


class Test沒說理由就擋下來:
    def test_改repo裡的檔案要先說理由(self, 佈景: tuple[Path, Path]) -> None:
        狀態, 專案 = 佈景

        跑完 = _問一次(專案 / "src" / "某某.py", 狀態=狀態, 專案=專案)

        assert _擋了嗎(跑完), 跑完.stdout
        assert "nova 跑" in 跑完.stdout
        assert "s-1" in 跑完.stdout, "要把 session id 填好，人才照抄得了"

    def test_點開頭的地盤不擋(self, 佈景: tuple[Path, Path]) -> None:
        狀態, 專案 = 佈景
        (專案 / ".remember").mkdir()

        跑完 = _問一次(專案 / ".remember" / "now.md", 狀態=狀態, 專案=專案)

        assert not _擋了嗎(跑完), 跑完.stdout

    def test_repo外面不擋(self, 佈景: tuple[Path, Path], tmp_path: Path) -> None:
        狀態, 專案 = 佈景

        跑完 = _問一次(tmp_path / "外面.py", 狀態=狀態, 專案=專案)

        assert not _擋了嗎(跑完), 跑完.stdout


class Test說得出理由就放行:
    def test_繞過之後同一個session就不擋了(self, 佈景: tuple[Path, Path]) -> None:
        """**記號按 session 分。** 換一個 session 就要重新說一次——

        理由是「這次為什麼 nova 做不了」，那是每次工作各自成立的事。
        """
        狀態, 專案 = 佈景
        被擋 = _問一次(專案 / "src" / "某某.py", 會話="s-9", 狀態=狀態, 專案=專案)
        assert _擋了嗎(被擋)

        記 = _跑(
            "繞過",
            "--會話",
            "s-9",
            "--因為",
            "nova 的工作流中途不會回頭問我",
            餵="",
            狀態=狀態,
            在=專案,
        )
        assert 記.returncode == 0, 記.stderr

        assert not _擋了嗎(_問一次(專案 / "src" / "某某.py", 會話="s-9", 狀態=狀態, 專案=專案))

    def test_別的session不沾光(self, 佈景: tuple[Path, Path]) -> None:
        狀態, 專案 = 佈景
        _跑("繞過", "--會話", "s-9", "--因為", "某個理由", 餵="", 狀態=狀態, 在=專案)

        assert _擋了嗎(_問一次(專案 / "src" / "某某.py", 會話="s-10", 狀態=狀態, 專案=專案))

    def test_理由是空的不算說過(self, 佈景: tuple[Path, Path]) -> None:
        """**空理由等於沒理由。** 收下去的話這條規則一秒就被繞乾淨。"""
        狀態, 專案 = 佈景
        記 = _跑("繞過", "--會話", "s-9", "--因為", "   ", 餵="", 狀態=狀態, 在=專案)

        assert 記.returncode != 0
        assert _擋了嗎(_問一次(專案 / "src" / "某某.py", 會話="s-9", 狀態=狀態, 專案=專案))

    def test_理由要留下來給你看(self, 佈景: tuple[Path, Path]) -> None:
        """**記下來的理由才是這條規則真正的產出**——

        它是一份「nova 現在還做不了什麼」的清單，而那是使用者的資料。
        """
        狀態, 專案 = 佈景
        _跑("繞過", "--會話", "s-9", "--因為", "需要跨多輪對話", 餵="", 狀態=狀態, 在=專案)

        寫在哪 = list((狀態 / "nova" / "專案").glob("*/繞過/*"))
        assert len(寫在哪) == 1, 寫在哪
        assert "需要跨多輪對話" in 寫在哪[0].read_text(encoding="utf-8")


class Test退出碼永遠是零:
    """**這是這一支最要緊的保證。** 非零就等於「nova 壞了 ＝ 全部擋下」。"""

    @pytest.mark.parametrize(
        "餵什麼",
        [
            "",
            "不是 JSON",
            "{}",
            '{"session_id": "s-1"}',
            '{"tool_input": {}}',
            '{"tool_input": {"file_path": null}}',
            "[1, 2, 3]",
        ],
    )
    def test_什麼爛輸入都回零(self, 餵什麼: str, 佈景: tuple[Path, Path]) -> None:
        狀態, 專案 = 佈景

        跑完 = _跑("檢查編輯", "--stdin", 餵=餵什麼, 狀態=狀態, 在=專案)

        assert 跑完.returncode == 0, f"{餵什麼!r} → rc={跑完.returncode}\n{跑完.stderr}"

    def test_爛輸入一律放行(self, 佈景: tuple[Path, Path]) -> None:
        """讀不懂就放行。**這一支守的是預設值，不是不可逆的動作。**"""
        狀態, 專案 = 佈景

        assert not _擋了嗎(_跑("檢查編輯", "--stdin", 餵="爛掉的", 狀態=狀態, 在=專案))

    def test_真的擋下來的時候也是零(self, 佈景: tuple[Path, Path]) -> None:
        狀態, 專案 = 佈景

        跑完 = _問一次(專案 / "src" / "某某.py", 狀態=狀態, 專案=專案)

        assert 跑完.returncode == 0
        assert _擋了嗎(跑完)
