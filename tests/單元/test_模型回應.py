"""證據 schema 的契約。

這幾支測試守的是**設計決定**，不是實作細節——決定被人不小心改掉時要當場紅。
"""

import dataclasses
import typing

import pytest

from nova.契約.模型回應 import 全部失敗代碼, 回應, 用量


def _空回應(**覆寫: object) -> 回應:
    預設: dict[str, object] = {
        "文字": "ok",
        "執行成功": True,
        "失敗代碼": "none",
        "原始結束碼": 0,
        "對話識別碼": None,
        "用量": 用量(輸入token=1, 輸出token=1),
    }
    預設.update(覆寫)
    return 回應(**預設)  # type: ignore[arg-type]


def test_回應不可變() -> None:
    """證據在跨層傳遞途中被改掉，下游就無法信任它。"""
    答 = _空回應()
    with pytest.raises(dataclasses.FrozenInstanceError):
        答.文字 = "被改了"  # type: ignore[misc]


def test_沒有叫成功的欄位() -> None:
    """三家 CLI 實測：模型拒答／答錯一律 exit 0。

    介面只知道「跑完了嗎」，不知道「任務成了嗎」。提供 `成功` 欄位會讓上層拿它當
    停止條件——那是 CLAUDE.md 硬規則第 4 條與規格 §8 反模式二禁止的
    「以模型說完成了當停止條件」。設計決定見 docs/設計/02-統一LLM介面.md。
    """
    欄位名 = {欄.name for 欄 in dataclasses.fields(回應)}
    assert "成功" not in 欄位名
    assert "執行成功" in 欄位名


def test_失敗代碼全是ASCII() -> None:
    """失敗代碼要跨程序流動（CLI 輸出、日誌、CI），屬 CLAUDE.md 的 ASCII 例外。"""
    assert 全部失敗代碼, "至少要有一個失敗代碼"
    for 代碼 in 全部失敗代碼:
        assert 代碼.isascii(), f"{代碼!r} 不是 ASCII"
        assert 代碼 == 代碼.lower(), f"{代碼!r} 要小寫"


def test_失敗代碼與型別標註一致() -> None:
    """常數與 Literal 分兩個地方寫就會漂移，用測試釘在一起。"""
    標註 = typing.get_type_hints(回應)["失敗代碼"]
    assert set(typing.get_args(標註)) == set(全部失敗代碼)


def test_沒失敗時代碼是none() -> None:
    assert _空回應().失敗代碼 == "none"


def test_成本可以是空的() -> None:
    """只有 claude 給成本。codex 與 agy 只有 token 數——不准為了對稱去估算。"""
    assert 用量(輸入token=1, 輸出token=1).成本美金 is None
