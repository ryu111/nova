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

from nova.契約.模型回應 import 終局
from nova.契約.角色 import 呼叫選項, 權限
from nova.載體.模型.轉接 import 建立

三家 = ("claude", "codex", "agy")

#: 三家都隔離得了。claude 走 `--setting-sources ""`——實測讀不到 CLAUDE.md，
#: 而且訂閱登入照樣能用（`--bare` 才是會弄壞認證的那條）。
可以隔離設定 = {"claude": True, "codex": True, "agy": True}


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
def test_claude隔離設定之後讀不到CLAUDE_md() -> None:
    """設定隔離要真的隔離，不能只是旗標長得像。

    這支同時守兩件事：CLAUDE.md 讀不到（行為由 nova 決定，不由使用者家目錄決定），
    而且**認證沒被弄壞**（訂閱登入還能用）。
    `--bare` 過得了前者、過不了後者，所以不能用它。

    （這支取代了原本「claude 在設定隔離下必定認證失敗」那支——
    那條限制在 `--setting-sources` 出現之後就不成立了。）
    """
    答 = 建立("claude", 執行檔=None).詢問(
        "這個專案的 CLAUDE.md 裡有寫到什麼？如果你看不到任何 CLAUDE.md，只回覆「看不到」",
        選項=呼叫選項(隔離設定=True, 逾時秒=180.0),
    )
    assert 答.終局 is 終局.成功, f"認證被弄壞了：{答.失敗代碼.value} — {答.文字[:200]}"
    assert "看不到" in 答.文字, f"CLAUDE.md 沒被擋住：{答.文字[:300]}"


@pytest.mark.真cli
@pytest.mark.serial
@pytest.mark.parametrize("家", ["codex", "agy"])
def test_記住sid就能續接同一段對話(家: str) -> None:
    """持久對話：第一輪留檔並記下 sid，第二輪帶回去接得上。"""
    第一輪 = 建立(家, 執行檔=None).詢問(  # type: ignore[arg-type]
        "記住：我的暗號是芭樂。只回覆「記住了」",
        選項=呼叫選項(逾時秒=180.0, 保留對話=True, 隔離設定=可以隔離設定[家]),
    )
    assert 第一輪.終局 is 終局.成功, 第一輪.文字[:200]
    assert 第一輪.對話識別碼, f"{家} 沒給 sid，續接不了"

    第二輪 = 建立(家, 執行檔=None).詢問(  # type: ignore[arg-type]
        "我的暗號是什麼？只回覆那兩個字",
        選項=呼叫選項(逾時秒=180.0, 續接=第一輪.對話識別碼, 隔離設定=可以隔離設定[家]),
    )
    assert 第二輪.終局 is 終局.成功, 第二輪.文字[:200]
    assert "芭樂" in 第二輪.文字, f"{家} 沒接上前一輪：{第二輪.文字[:200]}"
