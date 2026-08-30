"""思考深度：統一介面上的一個旋鈕，三家各自實作。

## 三種完全不同的機制

```
claude   --effort <level>                       low, medium, high, xhigh, max
codex    -c model_reasoning_effort="<level>"    同上（nova 原本寫死 max）
agy      包在型號後綴 gemini-3.7-flash-high      只有 low, medium, high
```

**統一介面存在的理由就是吸收這種差異。** 呼叫端說「想深一點」，
不必知道那在 codex 是 TOML 設定、在 agy 是型號的一部分。

2026-08-30 踩過：把使用者說的「luna-max」當型號傳下去 → `model-not-found`。
`max` 是深度、`gpt-5.6-luna` 才是型號，那是兩個旋鈕。

## 做不到的一定要炸，不准默默降級

agy 只有三階。給它 `max` 而 nova 自作主張換成 `high`，使用者會以為
叫到了最深——**帳照付、深度沒開，而且沒有任何訊息**。那是假的安全感。
"""

from pathlib import Path

import pytest

from nova.契約.角色 import 呼叫選項
from nova.載體.模型.轉接 import agy預設模型, codex推理強度, 建命令列, 思考深度們


def _參數(家: str, **旋鈕: object) -> list[str]:
    return 建命令列(家, 執行檔=Path(f"/x/{家}")).組參數("在嗎", 呼叫選項(**旋鈕))  # type: ignore[arg-type]


class Test三家各自實作同一個旋鈕:
    def test_claude走effort旗標(self) -> None:
        參 = _參數("claude", 思考深度="high")

        assert "--effort" in 參
        assert 參[參.index("--effort") + 1] == "high"

    def test_codex走toml設定(self) -> None:
        參 = _參數("codex", 模型="gpt-5.6-luna", 思考深度="high")

        assert 'model_reasoning_effort="high"' in 參
        # **只准有一份。** 原本寫死的那條要被取代，不是再加一條——
        # 兩條 `-c` 同一個鍵，哪一條贏是 codex 的實作細節，那等於沒有保證。
        assert sum(1 for 格 in 參 if "model_reasoning_effort" in 格) == 1, 參

    def test_agy換型號後綴(self) -> None:
        """**agy 沒有旗標，深度是型號的一部分**（`agy models` 實測）。"""
        參 = _參數("agy", 思考深度="low")

        assert "gemini-3.7-flash-low" in 參
        assert "gemini-3.7-flash-high" not in 參

    def test_agy跑別家型號時不准加深度後綴(self) -> None:
        """agy 也代跑 claude／gpt 的型號，**那些型號沒有深度後綴這回事**。

        `agy models` 列得出 `claude-sonnet-4-6`、`claude-opus-4-6-thinking`、
        `gpt-oss-120b-medium`。無條件補後綴會送出 `claude-sonnet-4-6-high`
        這種不存在的型號——而那條通道的額度是獨立的一池，
        走不到就等於整池浪費。
        """
        for 型 in ("claude-sonnet-4-6", "claude-opus-4-6-thinking"):
            參 = _參數("agy", 模型=型, 思考深度="high")
            assert 型 in 參, f"{型} 被改掉了：{參}"

    def test_agy自己指定的型號也換得掉(self) -> None:
        參 = _參數("agy", 模型="gemini-3.1-pro-high", 思考深度="low")

        assert "gemini-3.1-pro-low" in 參


class Test沒給就維持各家現況:
    def test_codex維持原本寫死的那階(self) -> None:
        """**不給不等於變淺。** 改掉預設會讓既有的委派安靜地變笨。"""
        參 = _參數("codex", 模型="gpt-5.6-luna")

        assert f'model_reasoning_effort="{codex推理強度}"' in 參

    def test_claude沒給就不加旗標(self) -> None:
        """各家自己的預設是它們的決定，不是 nova 的。"""
        參 = _參數("claude")

        assert "--effort" not in 參

    def test_agy沒給就用預設型號(self) -> None:
        參 = _參數("agy")

        assert agy預設模型 in 參


class Test做不到的要炸不准默默降級:
    @pytest.mark.parametrize("深", ["xhigh", "max"])
    def test_agy沒有那幾階就當場炸(self, 深: str) -> None:
        """**默默換成 high 是假的安全感**：帳照付、深度沒開、沒有訊息。"""
        with pytest.raises(ValueError, match="agy"):
            _參數("agy", 思考深度=深)

    def test_訊息要說得出agy有哪幾階(self) -> None:
        with pytest.raises(ValueError, match="low"):
            _參數("agy", 思考深度="max")

    @pytest.mark.parametrize("家", ["claude", "codex", "agy"])
    def test_不認得的值三家都炸(self, 家: str) -> None:
        """**打錯字要當場知道。** 傳下去的話是 CLI 報錯，訊息指不回 nova。"""
        with pytest.raises(ValueError, match="思考深度"):
            _參數(家, 思考深度="非常深")


def test_可用的階是一份資料() -> None:
    """**寫成資料不是 if 鏈**：多一階就多一列。而且順序就是深淺。"""
    assert 思考深度們 == ("low", "medium", "high", "xhigh", "max")
