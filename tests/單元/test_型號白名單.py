"""agy 的 Gemini 族只准一顆型號，別族不受限。

**白名單不是黑名單**：agy 每次上架新型號，黑名單就漏一格，
而漏掉的那格會安靜地照跑——帳單看得到、當下看不到。
"""

from pathlib import Path

import pytest

from nova.契約.角色 import 呼叫選項, 權限
from nova.載體.模型.轉接 import agy預設模型, 建命令列


def _型號(模型: str | None, 深度: str = "high") -> str:
    參 = 建命令列("agy", 執行檔=Path("/x/agy")).組參數(
        "在嗎", 呼叫選項(權限=權限.可編輯, 模型=模型, 思考深度=深度)
    )
    return 參[參.index("--model") + 1]


def test_不給模型就是那一顆() -> None:
    assert _型號(None) == agy預設模型


@pytest.mark.parametrize("型", ["gemini-3.7-flash", "gemini-3.7-flash-high"])
def test_那一顆的兩種寫法都准(型: str) -> None:
    """給不給後綴都算同一顆——深度旋鈕會把後綴補成 high。"""
    assert _型號(型) == agy預設模型


@pytest.mark.parametrize(
    "型",
    ["gemini-3.1-pro", "gemini-3.1-pro-high", "gemini-3.5-flash-high", "gemini-3.6-flash-low"],
)
def test_gemini族的其他型號一律當場擋(型: str) -> None:
    """使用者裁定（2026-08-31）：Gemini 那池只用 `gemini-3.7-flash-high`。

    池是共用的，換一顆 Gemini 不會換到另一份額度，只會用更貴的單價吃同一池。
    """
    with pytest.raises(ValueError, match="gemini"):
        _型號(型)


@pytest.mark.parametrize(
    "型", ["claude-sonnet-4-6", "claude-opus-4-6-thinking", "gpt-oss-120b-medium"]
)
def test_別族不受這條限制(型: str) -> None:
    """claude／gpt 是 agy 代跑的**另一個額度池**，不吃 Gemini 那份。"""
    assert _型號(型) == 型
