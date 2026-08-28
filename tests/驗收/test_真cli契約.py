"""真的呼叫外部 CLI 的契約測試。**兩個閘都排除，要手動跑。**

```bash
uv run pytest -m 真cli -q      # 會燒 token、需要三家都認證過
```

為什麼非有不可：假 CLI 是**墊片**，墊片證明的是「參數有沒有傳對」，
不是「這組參數真的跑得起來」。實際被咬過一次——

    codex 的 `--sandbox` 與 `--approve-for-me` 互斥，一起給 exit 2。
    單元與整合層全綠，只有真跑才紅。

外部 CLI 換版本就會改行為，所以這一層永遠不能省，也永遠不該進 CI
（agy 用 Google OAuth，CI 認證方式查不到）。
"""

import pytest

from nova.契約.模型回應 import 失敗代碼, 終局
from nova.契約.角色 import 呼叫選項, 權限
from nova.載體.模型.轉接 import 建立

三家 = ("claude", "codex", "agy")

#: claude 的設定隔離（`--bare`）連 keychain 與 OAuth 都不讀，訂閱登入會死。
#: 這不是我們的 bug，是那個旗標的設計。用下面的測試把這個限制釘住。
可以隔離設定 = {"claude": False, "codex": True, "agy": True}


@pytest.mark.真cli
@pytest.mark.serial
@pytest.mark.parametrize("家", 三家)
@pytest.mark.parametrize("可以做什麼", list(權限))
def test_每家每種權限都真的跑得起來(家: str, 可以做什麼: 權限) -> None:
    """旗標組合在真的 CLI 上不會被拒。這就是 codex 那個 bug 的守門員。"""
    答 = 建立(家, 執行檔=None).詢問(  # type: ignore[arg-type]
        "回覆兩個字：可以。不要做別的。",
        選項=呼叫選項(權限=可以做什麼, 逾時秒=180.0, 隔離設定=可以隔離設定[家]),
    )
    assert 答.終局 is 終局.成功, f"{家}／{可以做什麼.value}：{答.失敗代碼.value} — {答.文字[:400]}"


@pytest.mark.真cli
@pytest.mark.serial
@pytest.mark.parametrize("家", 三家)
def test_每家都給得出用量(家: str) -> None:
    """證據不是自由文字：token 數要真的解析得出來。"""
    答 = 建立(家, 執行檔=None).詢問(  # type: ignore[arg-type]
        "回覆兩個字：可以。", 選項=呼叫選項(逾時秒=180.0, 隔離設定=可以隔離設定[家])
    )
    assert 答.用量.輸入token > 0, f"{家} 的輸入 token 解析不出來"


@pytest.mark.真cli
@pytest.mark.serial
def test_claude在設定隔離下會認證失敗而且說得出原因() -> None:
    """把已知限制釘成會紅的測試。

    `--bare` 連 keychain 與 OAuth 都不讀（`claude --help` 原文），
    所以訂閱登入會變成「Not logged in」——那句話完全沒指向真因。
    nova 補上診斷，這支測試驗的就是那段診斷。

    **這支紅了是好消息**：代表 claude 改了行為，或這台機器設了 `ANTHROPIC_API_KEY`，
    那時候 `可以隔離設定["claude"]` 就可以改回 True。
    """
    答 = 建立("claude", 執行檔=None).詢問("回覆 ok", 選項=呼叫選項(隔離設定=True, 逾時秒=120.0))
    assert 答.失敗代碼 is 失敗代碼.認證, f"預期認證失敗，實際 {答.失敗代碼.value}：{答.文字[:200]}"
    assert "ANTHROPIC_API_KEY" in 答.文字, "診斷沒說清楚是哪個旗標害的"
