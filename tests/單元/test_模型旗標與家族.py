"""守住 `--模型` 的階段範圍與各家型號的命名空間歸屬。"""

import argparse
from pathlib import Path
from typing import Any

import pytest

from nova.契約.工作流 import 階段代碼
from nova.契約.模型回應 import 終局
from nova.契約.角色 import 呼叫選項
from nova.載體.命令列 import _這次的TDD角色藍圖
from nova.載體.模型 import 本地, 轉接
from nova.載體.模型.執行 import 執行結果
from nova.載體.模型.轉接 import agy預設模型, codex常用模型, codex高階模型, 建立


def _工作流參數(*, 用: str | None, 審查用: str | None, 模型: str | None) -> argparse.Namespace:
    """組出 `_這次的TDD角色藍圖` 需要的最小命令列參數。"""
    return argparse.Namespace(用=用, 審查用=審查用, 逾時=None, 模型=模型)


@pytest.mark.parametrize(
    ("審查用", "審查階段的型號"),
    [
        (None, codex高階模型),
        ("codex", codex高階模型),
        ("codex,agy", codex高階模型),
        ("claude", None),
        ("agy", None),
        ("agy,codex", None),
    ],
)
def test_模型旗標只套用到用指名的階段(審查用: str | None, 審查階段的型號: str | None) -> None:
    """守住 `--模型` 跟 `--用` 對稱：`--模型` 只落在 `--用` 指名的那幾階。

    審查那階由 `--審查用` 管：還是派工表原本那一家就留著派工表的型號，
    換了家就清空讓那一家用自己的預設——兩種都不准拿到工作階段的型號。
    """
    藍圖們 = {
        藍圖.識別碼: 藍圖
        for 藍圖 in _這次的TDD角色藍圖(_工作流參數(用="claude", 審查用=審查用, 模型="sonnet"))
    }

    for 階段 in (階段代碼.測試, 階段代碼.實作, 階段代碼.重構):
        assert 藍圖們[階段.value].模型 == "sonnet"
    assert 藍圖們[階段代碼.審查.value].模型 == 審查階段的型號


@pytest.mark.parametrize(
    ("家", "外來型號"),
    [
        ("codex", "sonnet"),
        ("codex", agy預設模型),
        ("codex", "gpt-5.6-vega"),
        ("agy", "sonnet"),
        ("agy", codex高階模型),
        ("agy", "claude-sonnet-9-9"),
        ("local", "opus"),
        ("local", codex常用模型),
    ],
)
def test_不屬於這一家的型號在送出前就炸(
    家: str, 外來型號: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """守住型號的家族歸屬：這一家沒認過的型號不准送進子程序或 HTTP 端點。

    認的是**這一家列得出來的那幾顆**，不是「看起來像」——別家的型號、
    以及沒有人認領過的字串，都要在送出前當場炸。
    """
    送出過: list[str] = []

    def 假跑(*位置: object, **具名: object) -> 執行結果:
        del 位置, 具名
        送出過.append("子程序")
        return 執行結果(標準輸出="", 標準錯誤="", 結束碼=0)

    def 假發請求(*位置: object, **具名: object) -> dict[str, Any]:
        del 位置, 具名
        送出過.append("HTTP")
        return {}

    monkeypatch.setattr(轉接, "跑cli", 假跑)
    monkeypatch.setattr(本地.本地腦, "_發出請求", 假發請求)
    腦 = 建立(家, 執行檔=None if 家 == 本地.家族名 else Path(f"/x/{家}"))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=f"{外來型號} 不屬於 {家}"):
        腦.詢問("提示", 選項=呼叫選項(模型=外來型號))

    assert not 送出過


@pytest.mark.parametrize(
    "型號", ["sonnet", "opus", "claude-opus-4-6-20260501", "some-internal-alias-42"]
)
def test_claude接受任意型號並原樣送出(型號: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """守住 claude 宣告的開放型號集合：任意字串都吃，不套別家的白名單。"""
    送出的參數: list[list[str]] = []

    def 假跑(執行檔: Path, 參數: list[str], **具名: object) -> 執行結果:
        del 執行檔, 具名
        送出的參數.append(list(參數))
        return 執行結果(
            標準輸出='{"type":"result","is_error":false,"result":"好了"}',
            標準錯誤="",
            結束碼=0,
        )

    monkeypatch.setattr(轉接, "跑cli", 假跑)

    答 = 建立("claude", 執行檔=Path("/x/claude")).詢問("提示", 選項=呼叫選項(模型=型號))

    assert 答.終局 is 終局.成功
    assert len(送出的參數) == 1
    assert 送出的參數[0][送出的參數[0].index("--model") + 1] == 型號
