"""證據 schema 的契約。

這幾支測試守的是**設計決定**，不是實作細節——決定被人不小心改掉時要當場紅。
"""

import dataclasses
import typing

import pytest

from nova.契約.模型回應 import _終局表, 全部失敗代碼, 全部終局, 回應, 用量, 終局判定


def _空回應(**覆寫: object) -> 回應:
    預設: dict[str, object] = {
        "文字": "ok",
        "終局": "success",
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


def test_沒有任何布林的成敗欄位() -> None:
    """三家 CLI 實測：模型拒答／答錯一律 exit 0。

    介面只知道「跑完了嗎」，不知道「任務成了嗎」。而且「跑完了嗎」本身也不是布林——
    見 `test_終局是三值`。任何 `成功: bool` 都會讓上層拿它當停止條件，
    那是 CLAUDE.md 硬規則第 4 條與規格 §8 反模式二禁止的。
    """
    欄位名 = {欄.name for 欄 in dataclasses.fields(回應)}
    assert "成功" not in 欄位名
    assert "執行成功" not in 欄位名, "布林會把「結果未知」壓成「確定失敗」"
    assert "終局" in 欄位名


def test_終局是三值() -> None:
    """at-most-once 的地基：結果未知 ≠ 確定失敗。

    殺掉子程序時工作可能已經做了一半。把它當確定失敗，重試就會把可能做過的事
    再做一次。三值才分得開「可以重試」與「不可以重試」。
    """
    assert set(全部終局) == {"success", "failed", "unknown"}


def test_終局全是ASCII() -> None:
    """終局要跨程序流動（CLI 的 --json 輸出、日誌），屬 CLAUDE.md 的 ASCII 例外。"""
    for 值 in 全部終局:
        assert 值.isascii() and 值 == 值.lower()


class Test終局判定:
    @pytest.mark.parametrize("代碼", ["auth", "model-not-found", "usage"])
    def test_確定沒送到模型的是確定失敗(self, 代碼: str) -> None:
        """認證錯、模型不存在、旗標錯——請求根本沒出門，重試是安全的。"""
        assert 終局判定(代碼) == "failed"  # type: ignore[arg-type]

    @pytest.mark.parametrize("代碼", ["timeout", "interrupted", "upstream", "unknown"])
    def test_可能已經做了一半的是結果未知(self, 代碼: str) -> None:
        """逾時被殺、被中斷、上游 5xx、解析不出來——都可能已經產生副作用。

        寧漏不重：這幾種一律不准自動重試。
        """
        assert 終局判定(代碼) == "unknown"  # type: ignore[arg-type]

    def test_沒失敗就是成功(self) -> None:
        assert 終局判定("none") == "success"

    def test_每個失敗代碼都要有明確的終局(self) -> None:
        """新增失敗代碼卻忘了決定它可不可以重試——這支會紅。

        要驗的是**表裡有沒有那一列**，不是「回傳值合不合法」——
        `終局判定` 有 fail-closed 的預設值，所以回傳值永遠合法，那樣驗等於沒驗。
        """
        沒決定 = [代碼 for 代碼 in 全部失敗代碼 if 代碼 not in _終局表]
        assert not 沒決定, f"這些失敗代碼還沒決定可不可以重試：{沒決定}"

    def test_表裡沒有的代碼要fail_closed(self) -> None:
        """萬一真的漏了，也要落在「不准重試」那一邊。"""
        assert 終局判定("這個代碼不存在") == "unknown"  # type: ignore[arg-type]


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
