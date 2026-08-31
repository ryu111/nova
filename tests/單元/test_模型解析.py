"""三家 CLI 的 envelope → nova 的 回應。

測試餵的是 `tests/整合/實錄/` 裡**真的跑出來**的輸出，不是手寫的假資料——
手寫假資料只會證明解析器符合我對格式的想像。
"""

import json
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


class Test診斷不准被自己的罐頭句擋掉:
    """CLI 明明講了為什麼失敗，nova 卻回「不知道發生什麼事」。

    真實案例（2026-08-29，就是這條 bug 被抓到的那次）：叫 agy 讀網頁，
    它的 stderr 寫得清清楚楚——

        jetski: no output produced — a tool required the "read_url" permission
        that headless mode cannot prompt for, so it was auto-denied.

    而 nova 回的是「CLI 回報成功但一個字都沒說——工具可能失敗了而錯誤被吞掉」。

    原因是順序錯了：`_成功但沒話說算未知` 先把 `文字` 填成那句罐頭，
    `_補上診斷` 的守衛 `if 答.文字.strip(): return 答` 就以為「已經有話說了」，
    把真的診斷擋在門外。**是 nova 自己的填充句吞掉了證據。**

    這一格是「觀察」通往「推理」的關口：拿不到失敗原因，
    轉移表就只能一律停，沒辦法依失敗種類換策略。
    """

    def test_agy空回應時要拿stderr當證據(self) -> None:
        信封 = json.dumps(
            {"conversation_id": "x", "status": "SUCCESS", "response": "", "num_turns": 1}
        )
        診斷 = (
            'jetski: no output produced — a tool required the "read_url" permission '
            "that headless mode cannot prompt for, so it was auto-denied."
        )
        答 = 解析agy(信封, 0, 診斷)
        assert 答.終局 is 終局.結果未知, "空回應還是結果未知，這條沒變"
        assert "read_url" in 答.文字, f"真的診斷被吞掉了：{答.文字}"

    def test_沒有stderr時才回罐頭句(self) -> None:
        """有話說就說真的，沒話說才用罐頭——**罐頭是後備不是預設**。"""
        信封 = json.dumps({"conversation_id": "x", "status": "SUCCESS", "response": ""})
        答 = 解析agy(信封, 0, "")
        assert 答.終局 is 終局.結果未知
        assert 答.文字, "完全沒證據的時候還是要講一句話，不能回空字串"

    def test_三家都要收得下stderr(self) -> None:
        """介面隔離：三家同形，不要只有踩到 bug 的那一家特別。"""
        for 解析, 輸出 in (
            (解析claude, '{"result":"","is_error":false}'),
            (解析codex, ""),
            (解析agy, '{"status":"SUCCESS","response":""}'),
        ):
            答 = 解析(輸出, 0, "某家的診斷字樣ABC")
            assert "某家的診斷字樣ABC" in 答.文字, f"{解析.__name__} 沒把 stderr 當證據"


class Test權限被擋要分得出來:
    """agy 在 headless 模式拒絕工具時，這是環境層的確定失敗。

    真實案例（PR #57 撿回 stderr 之後才看得到的那一行，這次是 `command`）：

        jetski: no output produced — a tool required the "command" permission
        that headless mode cannot prompt for, so it was auto-denied.

    工具在第一步就被權限系統拒絕，沒有任何動作發生；不能把它降成
    「可能已經做了一半」的結果未知。診斷也要保留供應商、工具與權限名稱，
    人才能去修環境，而不是去猜工作流有沒有半成品。
    """

    def test_agy的auto_deny要分成確定失敗(self) -> None:
        信封 = json.dumps({"status": "SUCCESS", "response": ""})
        診斷 = (
            'agy: jetski: no output produced — the "run_command" tool '
            'required the "command" permission that headless mode cannot prompt for, '
            "so it was auto-denied."
        )
        答 = 解析agy(信封, 0, 診斷)
        assert 答.失敗代碼 is 失敗代碼.權限被擋
        assert 答.終局 is 終局.確定失敗, "權限在模型開始前被拒，不能算結果未知"

    def test_agy的auto_deny訊息要指得出家工具和權限(self) -> None:
        信封 = json.dumps({"status": "SUCCESS", "response": ""})
        診斷 = (
            'agy: jetski: no output produced — the "run_command" tool '
            'required the "command" permission that headless mode cannot prompt for, '
            "so it was auto-denied."
        )
        答 = 解析agy(信封, 0, 診斷)

        for 片段 in (
            "agy",
            "run_command",
            '"command"',
            "--add-dir",
            "檔案存取",
            "headless",
            "auto-denied",
        ):
            assert 片段 in 答.文字, f"權限被拒的環境證據少了 {片段!r}：{答.文字}"
        assert 答.終局 is 終局.確定失敗, "環境層失敗的訊息不能伴隨結果未知"

    def test_codex的沙箱拒絕要分成權限被擋(self) -> None:
        """實測原文（設計文件 02 有貼）：

        失敗：系統拒絕寫入 `/Users/sbu/nova-越界測試.txt`（operation not permitted）
        """
        assert (
            解析codex("", 1, "write failed: operation not permitted").失敗代碼 is 失敗代碼.權限被擋
        )

    def test_一般的空回應還是未知(self) -> None:
        """**這支防的是分過頭。** 沒有權限字樣就不准說是權限問題——

        誤判成權限會讓接力停止換腦，而那可能正是換腦能救的一次。
        """
        信封 = json.dumps({"status": "SUCCESS", "response": ""})
        assert 解析agy(信封, 0, "").失敗代碼 is 失敗代碼.未知


class Test額度用完要分得出來:
    """額度用完是**接力鏈存在的理由**，而它現在不會觸發。

    今天的行為：codex 額度用完 → stderr 有 `You've hit your usage limit`
    → 分類成 `unknown` → 終局`結果未知` → 可編輯模式下接力不換腦 → 整條鏈停住。
    **一條 `--用 codex,agy` 的鏈，在最該換手的時候不換。**

    字串出處（不是想像的）：openai/codex issue #38603 貼出實際重現——
    `codex exec --sandbox read-only --skip-git-repo-check "Reply with exactly: OK"`
    的輸出是

        ERROR: You've hit your usage limit. Upgrade to Plus to continue using
        Codex (https://chatgpt.com/explore/plus), or try again at Sep 13th, 2026 7:11 PM.

    **日期是動態的，所以比對只能挑穩定片段。**

    為什麼是`確定失敗`不是`結果未知`：這是請求被拒，模型一個字都沒跑，
    沒有任何副作用——那正是「可以安全換下一家」的定義。
    """

    def test_codex額度用完(self) -> None:
        訊息 = (
            "ERROR: You've hit your usage limit. Upgrade to Plus to continue "
            "using Codex (https://chatgpt.com/explore/plus), or try again at "
            "Sep 13th, 2026 7:11 PM."
        )
        答 = 解析codex("", 1, 訊息)
        assert 答.失敗代碼 is 失敗代碼.額度耗盡
        assert 答.終局 is 終局.確定失敗, "沒做事就沒有副作用，可以安全換下一家"

    def test_暫時限流不算額度用完(self) -> None:
        """**這支防的是把兩件事混在一起。** 429 是等一下就好，額度用完是要等重置。

        原文（同一份研究）：`code: "rate_limit_exceeded"`、`429 Too Many Requests`。
        """
        答 = 解析codex("", 1, 'error: code "rate_limit_exceeded", 429 Too Many Requests')
        assert 答.失敗代碼 is not 失敗代碼.額度耗盡


class Test額度字串三家都要涵蓋:
    """上一輪只有 codex 有字串。這輪把 claude 與 agy 補上。

    **claude 的變體是會長出來的**——官方錯誤文件列的是

        You've hit your session limit · resets 3:45pm
        You've hit your weekly limit · resets Mon 12:00am
        You've hit your Opus limit · resets 3:45pm
        You've hit your Sonnet limit · resets 3:45pm

    中間那個字是**方案期間或型號名**。寫死這四個，出第五個型號就靜默失效——
    而靜默失效的分類器比沒有分類器更糟：它讓人以為有在守。
    所以這一組改用樣式比對，`hit your <任何一個字> limit`。

    出處：anthropics/claude-code issue #86272（重現命令
    `echo "Reply with only READY." | claude -p --model claude-opus-5`）
    ＋ Claude Code 官方 Errors — Usage limits。
    """

    def test_claude的四種額度講法都要命中(self) -> None:
        for 講法 in (
            "You've hit your session limit · resets 3:50pm (Asia/Tokyo)",
            "You've hit your weekly limit · resets Mon 12:00am",
            "You've hit your Opus limit · resets 3:45pm",
            "You've hit your Sonnet limit · resets 3:45pm",
        ):
            assert 解析claude("", 1, 講法).失敗代碼 is 失敗代碼.額度耗盡, 講法

    def test_還沒出現的型號名也要命中(self) -> None:
        """**這支才是重點。** 上面四支寫死也會過，這支寫死就過不了。"""
        講法 = "You've hit your Nebula limit · resets 3:45pm"
        assert 解析claude("", 1, 講法).失敗代碼 is 失敗代碼.額度耗盡

    def test_agy的individual_quota要命中(self) -> None:
        """出處：google-antigravity/antigravity-cli issue #789（`agy 1.1.12`）。

        **注意它帶著 `429` 但不是暫時限流**——是要等 143 小時的每日配額。
        所以這條要排在 HTTP 狀態分類前面，不然會被判成 `上游`。
        """
        for 講法 in (
            "⚠ Individual quota reached. Please upgrade your subscription. Resets in 143h57m55s.",
            "RESOURCE_EXHAUSTED (code 429): Individual quota reached. Resets in 167h39m40s.",
        ):
            assert 解析agy("", 1, 講法).失敗代碼 is 失敗代碼.額度耗盡, 講法

    def test_不准把暫時限流誤判成額度用完(self) -> None:
        """研究裡逐條警告過的坑：**不能只因為含有 `exhausted` 就判成額度耗盡。**

        Gemini CLI 的 `Resource exhausted` 帶著 `Retrying after 1s` 是暫時容量問題，
        重試幾秒就好；判成額度耗盡會讓接力白換一家。
        """
        for 講法 in (
            'error: code "rate_limit_exceeded", 429 Too Many Requests',
            "API error: 429 - Resource exhausted. Retrying after 1s",
            "Please retry in 39.844676573s.",
        ):
            assert 解析codex("", 1, 講法).失敗代碼 is not 失敗代碼.額度耗盡, 講法


class Test快取建立token:
    """claude 的 `cache_creation_input_tokens` 是**真的付費的 input**（1.25×）。

    少了這一欄，`claude_ok.json` 這種「輸入 10、快取讀取 0、快取建立 16,668」的
    呼叫在帳本裡只留下 10——**99.94% 的量憑空消失**，而所有成本比較都
    建立在那個數字上。快取建立**不是**快取讀取的子集，兩欄要分開記。
    """

    def test_claude的快取建立要記下來(self) -> None:
        assert 解析claude(讀("claude_ok.json"), 0).用量.快取建立token == 16668

    def test_快取建立與快取讀取是兩欄(self) -> None:
        用 = 解析claude(讀("claude_ok2.json"), 0).用量
        assert (用.快取建立token, 用.快取讀取token) == (8094, 8570)

    def test_不給快取建立的家是None不是0(self) -> None:
        """給不出來就別給。0 會被誤讀成「量過，是零」。"""
        assert 解析codex(讀("codex_ok2.jsonl"), 0).用量.快取建立token is None
