"""三家 CLI 的 envelope → nova 的 回應。

測試餵的是 `tests/整合/實錄/` 裡**真的跑出來**的輸出，不是手寫的假資料——
手寫假資料只會證明解析器符合我對格式的想像。
"""

from pathlib import Path

import pytest

from nova.契約.模型回應 import 失敗代碼, 終局
from nova.載體.模型.解析 import 解析agy, 解析claude, 解析codex

實錄 = Path(__file__).resolve().parents[2] / "tests" / "整合" / "實錄"


def 讀(名: str) -> str:
    return (實錄 / 名).read_text(encoding="utf-8")


class Testclaude:
    def test_成功(self) -> None:
        答 = 解析claude(讀("claude_ok.json"), 0)
        assert 答.終局 == "success"
        assert 答.文字 == "ok"
        assert 答.失敗代碼 == "none"
        assert 答.用量.成本美金 == pytest.approx(0.034416)
        assert 答.用量.輸入token == 10
        assert 答.對話識別碼 == "00000000-0000-4000-8000-000000000000"

    def test_模型不存在_不准看subtype(self) -> None:
        """這份實錄裡 `is_error:true` 但 `subtype` 仍是 `"success"`。

        拿 subtype 當判準會把失敗讀成成功——這支測試就是釘死這件事的。
        """
        原始 = 讀("claude_bad.txt")
        assert '"subtype":"success"' in 原始.replace(" ", ""), "實錄前提變了，測試要重寫"

        答 = 解析claude(原始, 1)
        assert 答.終局 != "success"
        assert 答.失敗代碼 == "model-not-found"
        assert 答.原始結束碼 == 1

    def test_忽略envelope前面的非json雜訊(self) -> None:
        """claude 失敗時會先吐 `[claude-code:unrecognized_model] …` 與 `Warning:` 純文字。"""
        assert 讀("claude_bad.txt").splitlines()[0].startswith("[claude-code:")
        assert 解析claude(讀("claude_bad.txt"), 1).用量.輸入token == 0


class Testcodex:
    def test_成功(self) -> None:
        答 = 解析codex(讀("codex_ok2.jsonl"), 0)
        assert 答.終局 == "success"
        assert 答.文字 == "ok"
        assert 答.用量.輸入token == 13368
        assert 答.用量.快取讀取token == 11008
        assert 答.用量.成本美金 is None, "codex 不給成本，不准自己估"

    def test_忽略認不得的行與事件(self) -> None:
        """認不得的行與事件都要被跳過。

        第一行是純文字 `Reading additional input from stdin...`，
        後面還有 cmux shim 插進來的兩條 `--dangerously-bypass-hook-trust` 事件。
        """
        原始 = 讀("codex_ok.jsonl")
        assert 原始.splitlines()[0] == "Reading additional input from stdin..."
        assert "dangerously-bypass-hook-trust" in 原始
        答 = 解析codex(原始, 0)
        assert 答.終局 == "success"
        assert 答.文字 == "ok", "雜訊事件不該被當成模型的回答"

    def test_模型不存在(self) -> None:
        答 = 解析codex(讀("codex_bad.txt"), 1)
        assert 答.終局 != "success"
        assert 答.失敗代碼 == "model-not-found"


class Testagy:
    def test_成功(self) -> None:
        答 = 解析agy(讀("agy_ok.json"), 0)
        assert 答.終局 == "success"
        assert 答.文字 == "ok\n"
        assert 答.用量.輸入token == 13721
        assert 答.用量.思考token == 29
        assert 答.對話識別碼 == "00000000-0000-4000-8000-000000000009"

    def test_模型不存在(self) -> None:
        答 = 解析agy(讀("agy_bad.txt"), 1)
        assert 答.終局 != "success"
        assert 答.失敗代碼 == "model-not-found"

    def test_串流格式(self) -> None:
        """stream-json 的鍵是 `event` 不是 `type`，最後一則是 `result`。"""
        答 = 解析agy(讀("agy_stream.jsonl"), 0)
        assert 答.終局 == "success"
        assert 答.文字 == "ok\n"


class Test壞掉的輸出要fail_closed:
    @pytest.mark.parametrize("解析", [解析claude, 解析codex, 解析agy])
    def test_整份解不動要回unknown(self, 解析: object) -> None:
        答 = 解析("這根本不是 JSON\n也不是\n", 0)  # type: ignore[operator]
        assert 答.終局 != "success"
        assert 答.失敗代碼 == "unknown"

    @pytest.mark.parametrize("解析", [解析claude, 解析codex, 解析agy])
    def test_空輸出加結束碼0也要紅(self, 解析: object) -> None:
        """agy issue #76：1.0.0 在 non-TTY 下 stdout 全空但結束碼仍是 0。

        「結束碼 0 就當成功」會把這種失敗讀成「模型回了空字串」。
        """
        答 = 解析("", 0)  # type: ignore[operator]
        assert 答.終局 != "success"
        assert 答.失敗代碼 == "unknown"

    @pytest.mark.parametrize("解析", [解析claude, 解析codex, 解析agy])
    def test_旗標用錯是usage(self, 解析: object) -> None:
        """三家一致：不存在的旗標 → 結束碼 2（claude 是 1，見下方個別斷言）。"""
        答 = 解析("unknown flag\n", 2)  # type: ignore[operator]
        assert 答.失敗代碼 == "usage"


_claude空回應 = (
    '{"type":"result","subtype":"success","is_error":false,"result":"",'
    '"session_id":"x","usage":{"input_tokens":1,"output_tokens":0}}'
)
_agy空回應 = (
    '{"conversation_id":"x","status":"SUCCESS","response":"","error":null,'
    '"usage":{"input_tokens":1,"output_tokens":0}}'
)
_codex沒說話 = (
    '{"type":"thread.started","thread_id":"x"}\n'
    '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":0}}'
)


class Test成功但沒話說:
    """CLI 說成功、卻一個字都沒回，那不是成功，是不知道發生什麼事。

    實測（agy 的 `generate_image`）：模型呼叫工具、工具 `state: ERROR`，
    而 envelope 仍然是 `status: SUCCESS`、`error: null`、`response: ""`。
    診斷被整個吞掉。當成功會讓上游以為事情辦完了。
    """

    def test_claude空回應降成未知(self) -> None:
        答 = 解析claude(_claude空回應, 0)
        assert 答.終局 is 終局.結果未知
        assert 答.失敗代碼 is 失敗代碼.未知

    def test_agy空回應降成未知(self) -> None:
        assert 解析agy(_agy空回應, 0).終局 is 終局.結果未知

    def test_codex沒說話也降成未知(self) -> None:
        assert 解析codex(_codex沒說話, 0).終局 is 終局.結果未知

    def test_空白字元不算有說話(self) -> None:
        只有空白 = _agy空回應.replace('"response":""', '"response":"  "')
        assert 解析agy(只有空白, 0).終局 is 終局.結果未知

    def test_有說話就照常成功(self) -> None:
        有話 = _agy空回應.replace('"response":""', '"response":"好"')
        assert 解析agy(有話, 0).終局 is 終局.成功
