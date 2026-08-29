"""禁令在 nova 自己起不來的時候，必須擋下而不是放行。

**這是實際發生過的。** 2026-08-30 改壞 `載體/命令列.py` 的一個 import，
接下來每一次 Bash 都收到

    PreToolUse:Bash hook error
    Failed with non-blocking status code: Traceback (most recent call last):

連續 12 次。「non-blocking」的意思是**指令照跑**——那幾分鐘裡三條禁令
（`--no-verify`、`--admin`、`gh pr merge` 缺 `--delete-branch`）等於不存在，
而且沒有任何東西提醒「你現在沒有護欄」。這正是假的安全感。

退出碼的語意（實測）：

| nova 回什麼 | 什麼情況 | Claude Code 怎麼解讀 |
|---|---|---|
| 0 | 放行 | 跑 |
| 2 | 禁令擋下 | **擋** |
| 1、127… | nova 起不來、uv 掛了、venv 壞了 | 非阻斷錯誤 → **跑** |

第三列就是洞：**「沒有答案」被當成「答案是放行」**。

修法在宿主那一側加 `|| exit 2`，把「沒答案」映成擋下。判決本身仍然歸 nova
——宿主只做「叫你的 CLI」與「你沒答就當你說不」，沒有裝任何判斷邏輯。
這條界線在 `~/.claude/CLAUDE.md` 的「你的邏輯不准住在別人的設定檔裡」。

**這支測試就是那條界線的另一半。** 宿主那一側測不到，所以由 nova 讀那個檔、
斷言它的形狀——nova 宣稱「這三條會被自動擋下」，把關器就必須真的存在。
"""

import json
from pathlib import Path

import pytest

專案根 = Path(__file__).resolve().parent.parent.parent
設定檔 = 專案根 / ".claude" / "settings.json"


@pytest.fixture(scope="module")
def 禁令hook() -> dict[str, object]:
    """挑出掛在 Bash 上的那個 PreToolUse hook。"""
    設定 = json.loads(設定檔.read_text(encoding="utf-8"))
    掛在Bash上的 = [
        單條
        for 組 in 設定["hooks"]["PreToolUse"]
        if 組.get("matcher") == "Bash"
        for 單條 in 組["hooks"]
    ]
    叫nova的 = [單條 for 單條 in 掛在Bash上的 if "檢查指令" in str(單條.get("command", ""))]
    assert 叫nova的, f"沒有任何 PreToolUse／Bash hook 叫 nova 檢查指令：{設定}"
    return 叫nova的[0]  # type: ignore[no-any-return]


def test_禁令hook存在(禁令hook: dict[str, object]) -> None:
    """只以文件形式存在的規範等於不存在——要有人真的叫它。"""
    assert 禁令hook["type"] == "command"


def test_nova起不來的時候要擋下不是放行(禁令hook: dict[str, object]) -> None:
    """指令必須把非零退出碼映成 2。

    Claude Code 只認 2 是「擋」，其他非零都是「非阻斷錯誤」然後照跑。
    所以少了這一段，nova 一壞掉禁令就靜默消失。
    """
    指令 = str(禁令hook["command"])

    assert "|| exit 2" in 指令, f"禁令 hook 沒有 fail-closed，nova 起不來時會靜默放行：{指令}"


def test_判決還是由nova做(禁令hook: dict[str, object]) -> None:
    """**這支防的是修過頭。**

    把宿主那行寫成「自己 grep 危險字串」也能 fail-closed，但那就是把邏輯
    搬進別人的設定檔——測不到，而且換一個 LLM 宿主就整個消失。
    宿主只准做兩件事：叫 nova 的 CLI、把「沒答案」當成不。
    """
    指令 = str(禁令hook["command"])

    assert "nova 檢查指令" in 指令
    for 危險 in ("no-verify", "--admin", "grep", "if "):
        assert 危險 not in 指令, f"宿主的設定檔裡出現了判斷邏輯（{危險}）：{指令}"
