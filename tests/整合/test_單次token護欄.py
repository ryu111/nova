"""單次呼叫 token 護欄：單次呼叫內部燒掉大量 token 時，帳本要標出、退出碼為 4。

codex exec 等 CLI 在一次呼叫內部會自己跑幾十輪，單次呼叫 input_tokens
可能超過百萬。現有工作流預算只在每次呼叫之前檢查，無法阻止單次呼叫內部超支
後的下一次呼叫靜悄悄發生。

此測試保證：
1. 單次呼叫 token 超過門檻時，帳本有標記。
2. 該輪工作流收在退出碼 4（護欄碼），停止往下走。
3. 門檻是每次呼叫的，不是累計的，且能從命令列調整（--單次最多token）。
4. 低於門檻時照常走完，不准誤報。
5. **比的是新鮮 token，不是「上下文多大」**：快取讀取是重讀已經快取好的
   上下文（0.1× 計價、跟這次做了多少工無關），撐大 `input_tokens` 不算超標。
   codex 的 `input_tokens` 含 `cached_input_tokens`（`non_cached_input =
   input − cached`，codex-rs/protocol/src/protocol.rs），claude 的不含——
   對齊做在解析器，護欄只看對齊後的量。
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from nova.契約.退出碼 import 放行, 護欄碼
from nova.載體.命令列 import 主程式

做假CLI型 = Callable[..., tuple[Path, Path]]


def _做假codex實錄(目錄: Path, token: int, 文字: str = "ok\nREVIEW: PASS", 快取: int = 0) -> Path:
    """產出帶有指定 input_tokens 的 codex 實錄檔。

    `快取` 是 `cached_input_tokens`，它是 `input_tokens` 的**子集**——
    codex 就是這樣回報的，所以這裡的形狀跟實錄 `codex_ok.jsonl` 一致。
    """
    檔 = 目錄 / f"codex_{token}_{快取}.jsonl"
    行們 = [
        "Reading additional input from stdin...",
        '{"type":"thread.started","thread_id":"00000000-0000-4000-8000-000000000001"}',
        '{"type":"turn.started"}',
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "item_0", "type": "agent_message", "text": 文字},
            }
        ),
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": token,
                    "cached_input_tokens": 快取,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 50,
                    "reasoning_output_tokens": 0,
                },
            }
        ),
    ]
    檔.write_text("\n".join(行們) + "\n", encoding="utf-8")
    return 檔


def _讀帳本(目錄: Path) -> list[dict[str, object]]:
    (檔,) = list(目錄.glob("*.jsonl"))
    return [json.loads(行) for 行 in 檔.read_text(encoding="utf-8").splitlines()]


def _呼叫結束們(目錄: Path) -> list[dict[str, object]]:
    return [事 for 事 in _讀帳本(目錄) if 事.get("event") == "call_finished"]


class Test單次呼叫token護欄:
    def test_單次呼叫超過token門檻會標記帳本且收在護欄(
        self,
        tmp_path: Path,
        做假CLI: 做假CLI型,
        翻牌判準: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """單次呼叫 token 超過門檻時，帳本必須標記且退出碼為 4（護欄）。"""
        實錄 = _做假codex實錄(tmp_path, token=1_479_440)
        假, _ = 做假CLI("codex")
        monkeypatch.setenv("NOVA_FAKE_CODEX_TRANSCRIPT", str(實錄))
        帳本目錄 = tmp_path / "帳"

        碼 = 主程式(
            [
                "工作流",
                "--用",
                "codex",
                "--審查用",
                "codex",
                "--執行檔",
                str(假),
                "--工作目錄",
                str(tmp_path),
                "--判準",
                str(翻牌判準),
                "--單次最多token",
                "100000",
                "--帳本目錄",
                str(帳本目錄),
                "做點事",
            ]
        )

        assert 碼 == 護欄碼, f"超過單次 token 門檻應收在護欄碼 4，實際為 {碼}"
        事件們 = _讀帳本(帳本目錄)
        assert any(
            事.get("token_exceeded") or 事.get("single_token_exceeded") or 事.get("單次token超標")
            for 事 in 事件們
        ), "帳本沒有標記單次 token 超過門檻"

    def test_低於門檻照常走完不准誤報(
        self,
        tmp_path: Path,
        做假CLI: 做假CLI型,
        翻牌判準: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """低於門檻時正常走完，不觸發護欄且帳本不應誤標超標。"""
        實錄 = _做假codex實錄(tmp_path, token=500)
        假, _ = 做假CLI("codex")
        monkeypatch.setenv("NOVA_FAKE_CODEX_TRANSCRIPT", str(實錄))
        帳本目錄 = tmp_path / "帳"

        碼 = 主程式(
            [
                "工作流",
                "--用",
                "codex",
                "--審查用",
                "codex",
                "--執行檔",
                str(假),
                "--工作目錄",
                str(tmp_path),
                "--判準",
                str(翻牌判準),
                "--單次最多token",
                "100000",
                "--帳本目錄",
                str(帳本目錄),
                "做點事",
            ]
        )

        assert 碼 == 放行, f"低於單次 token 門檻應正常完成（碼 0），實際為 {碼}"
        事件們 = _讀帳本(帳本目錄)
        assert not any(
            事.get("token_exceeded") or 事.get("single_token_exceeded") or 事.get("單次token超標")
            for 事 in 事件們
        ), "低於門檻時帳本不應標記超標"

    def test_預設單次門檻不必手動給旗標(
        self,
        tmp_path: Path,
        做假CLI: 做假CLI型,
        翻牌判準: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """忘了傳旗標不能等於沒有單次上限——預設值就要擋下單次千萬級爆量。"""
        實錄 = _做假codex實錄(tmp_path, token=12_380_000)
        假, _ = 做假CLI("codex")
        monkeypatch.setenv("NOVA_FAKE_CODEX_TRANSCRIPT", str(實錄))
        帳本目錄 = tmp_path / "帳"

        碼 = 主程式(
            [
                "工作流",
                "--用",
                "codex",
                "--審查用",
                "codex",
                "--執行檔",
                str(假),
                "--工作目錄",
                str(tmp_path),
                "--判準",
                str(翻牌判準),
                "--帳本目錄",
                str(帳本目錄),
                "做點事",
            ]
        )

        assert 碼 == 護欄碼, f"單次千萬級 token 應觸發預設門檻收在護欄碼 4，實際為 {碼}"
        事件們 = _讀帳本(帳本目錄)
        assert any(
            事.get("token_exceeded") or 事.get("single_token_exceeded") or 事.get("單次token超標")
            for 事 in 事件們
        ), "帳本沒有標記單次 token 超過預設門檻"


class Test上限比的是新鮮token不是上下文大小:
    """`input_tokens` 大不等於燒了很多——**大部分可能是重讀的快取**。

    實測：21 筆被標 `single_token_exceeded` 的呼叫全是 codex，cache_read 佔
    input 的 90%～98%，扣掉快取之後的新鮮量只有 154,360～684,765，
    沒有一筆碰到 2,000,000。它們被收 4 的理由是「上下文很大」，
    而這條護欄要擋的是「一次呼叫燒掉的錢」（`契約/工作流.py`
    「擋下一次呼叫內部跑幾十輪的千萬級爆量」）。

    30 回合的呼叫每回合重讀 70k 上下文就是 2.1M cache_read，
    工作量卻只有 output 那 2 萬——把快取讀取算進上限，量到的是上下文大小。
    """

    def test_快取撐大的呼叫不收護欄(
        self,
        tmp_path: Path,
        做假CLI: 做假CLI型,
        翻牌判準: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """input 3,000,000、cached 2,950,000：新鮮只有 50,050，**不准收 4**。"""
        實錄 = _做假codex實錄(tmp_path, token=3_000_000, 快取=2_950_000)
        假, _ = 做假CLI("codex")
        monkeypatch.setenv("NOVA_FAKE_CODEX_TRANSCRIPT", str(實錄))
        帳本目錄 = tmp_path / "帳"

        碼 = 主程式(
            [
                "工作流",
                "--用",
                "codex",
                "--審查用",
                "codex",
                "--執行檔",
                str(假),
                "--工作目錄",
                str(tmp_path),
                "--判準",
                str(翻牌判準),
                "--帳本目錄",
                str(帳本目錄),
                "做點事",
            ]
        )

        assert 碼 == 放行, f"3M 裡有 2.95M 是快取讀取，新鮮量 50,050 遠低於 2M，實際收 {碼}"
        呼叫們 = _呼叫結束們(帳本目錄)
        assert 呼叫們, "這一輪一次模型呼叫都沒落帳"
        assert not any(事.get("single_token_exceeded") for 事 in 呼叫們), "快取讀取不准算成超標"
        assert all(事.get("cache_read_tokens") == 2_950_000 for 事 in 呼叫們), (
            "扣掉的那份要另外一欄報，不是丟掉，實際 "
            f"{[事.get('cache_read_tokens') for 事 in 呼叫們]}"
        )

    def test_新鮮量真的超標才收護欄且帳本標旗標(
        self,
        tmp_path: Path,
        做假CLI: 做假CLI型,
        翻牌判準: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """input 2,100,000、cached 0：全是新鮮的，這種才是護欄要擋的爆量。"""
        實錄 = _做假codex實錄(tmp_path, token=2_100_000, 快取=0)
        假, _ = 做假CLI("codex")
        monkeypatch.setenv("NOVA_FAKE_CODEX_TRANSCRIPT", str(實錄))
        帳本目錄 = tmp_path / "帳"

        碼 = 主程式(
            [
                "工作流",
                "--用",
                "codex",
                "--審查用",
                "codex",
                "--執行檔",
                str(假),
                "--工作目錄",
                str(tmp_path),
                "--判準",
                str(翻牌判準),
                "--帳本目錄",
                str(帳本目錄),
                "做點事",
            ]
        )

        assert 碼 == 護欄碼, f"2,100,050 新鮮 token 超過預設上限 2,000,000，實際收 {碼}"
        超標的 = [事 for 事 in _呼叫結束們(帳本目錄) if 事.get("single_token_exceeded")]
        assert 超標的, "帳本沒有標 single_token_exceeded——別的鍵不算，讀帳的人認的是這個"
