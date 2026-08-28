"""三家 CLI 的 envelope → nova 的 `回應`。

全部是純函式：吃字串與結束碼，吐 schema。純函式才能用實錄餵測試，
不必啟動任何程序、不燒任何 token。

三條共通規則（設計理由見 docs/設計/02-統一LLM介面.md）：

1. **不准拿結束碼 0 當成功**——三家實測，模型拒答／答錯一律 exit 0。
2. **要容忍認不得的行與事件**——codex 的第一行是純文字，cmux shim 還會插事件進來。
3. **整份解不動時 fail-closed 回 `unknown`**，不是靜默成功。
"""

import json
from typing import Any

from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局判定

_模型關鍵詞 = (
    "unrecognized_model",
    "invalid model",
    "not recognized",
    "model metadata",
    "issue with the selected model",
    "model is not supported",
    "no such model",
)
_認證關鍵詞 = ("authentication", "unauthorized", "invalid api key", "not logged in")

# HTTP 狀態與「旗標用錯」的結束碼。抽成常數是 ruff PLR2004 要求，
# 順便讓「哪個數字代表什麼」只寫一次。
_未授權, _禁止, _找不到, _太多請求, _伺服器錯誤起點 = 401, 403, 404, 429, 500
_旗標用錯的結束碼 = 2


def _逐行json(文字: str) -> list[dict[str, Any]]:
    """把輸出裡認得出來的 JSON 物件挑出來，其餘整行丟掉。

    不是寬鬆，是**必要**：codex 第一行是 `Reading additional input from stdin...`，
    claude 失敗時前面會有 `[claude-code:…]` 與 `Warning:` 純文字。
    """
    物件: list[dict[str, Any]] = []
    for 行 in 文字.splitlines():
        乾淨 = 行.strip()
        if not 乾淨.startswith("{"):
            continue
        try:
            解出 = json.loads(乾淨)
        except json.JSONDecodeError:
            continue
        if isinstance(解出, dict):
            物件.append(解出)
    return 物件


def _由http狀態分類(狀態: int) -> 失敗代碼:
    if 狀態 in (_未授權, _禁止):
        return 失敗代碼.認證
    if 狀態 == _找不到:
        return 失敗代碼.模型不存在
    if 狀態 == _太多請求 or 狀態 >= _伺服器錯誤起點:
        return 失敗代碼.上游
    return 失敗代碼.未知


def _分類(結束碼: int, http狀態: int | None, 訊息: str) -> 失敗代碼:
    """把三家長得完全不同的錯誤講法，收斂成一組 ASCII 代碼。

    這一步一定要在介面內做完。往下游丟原始訊息就是規格 §4.3 說的
    「自由段落逼下游重建上游語意」。
    """
    if 結束碼 == _旗標用錯的結束碼:
        return 失敗代碼.用法錯誤
    低 = 訊息.lower()
    if any(詞 in 低 for 詞 in _模型關鍵詞):
        return 失敗代碼.模型不存在
    if any(詞 in 低 for 詞 in _認證關鍵詞):
        return 失敗代碼.認證
    if http狀態 is not None:
        return _由http狀態分類(http狀態)
    return 失敗代碼.未知


def _壞掉(結束碼: int, 訊息: str, 原始: list[dict[str, Any]]) -> 回應:
    """解不出 envelope。**這是 fail-closed 的落點**，不是「大概沒事」。"""
    代碼 = _分類(結束碼, None, 訊息)
    return 回應(
        文字="",
        終局=終局判定(代碼),
        失敗代碼=代碼,
        原始結束碼=結束碼,
        對話識別碼=None,
        用量=用量(輸入token=0, 輸出token=0),
        原始輸出=tuple(原始),
    )


def 解析claude(標準輸出: str, 結束碼: int) -> 回應:
    """`claude -p --output-format json` 的輸出。"""
    候選 = [物件 for 物件 in _逐行json(標準輸出) if 物件.get("type") == "result"]
    if not 候選:
        return _壞掉(結束碼, 標準輸出, [])
    信封 = 候選[-1]
    文字 = str(信封.get("result") or "")
    # `subtype` 在失敗時仍然是 "success"（見實錄 claude_bad.txt）——只看 is_error。
    順利 = not bool(信封.get("is_error", True)) and 結束碼 == 0
    代碼 = 失敗代碼.無 if 順利 else _分類(結束碼, 信封.get("api_error_status"), 文字)
    用了: dict[str, Any] = 信封.get("usage") or {}
    return 回應(
        文字=文字,
        終局=終局判定(代碼),
        失敗代碼=代碼,
        原始結束碼=結束碼,
        對話識別碼=信封.get("session_id"),
        用量=用量(
            輸入token=int(用了.get("input_tokens", 0)),
            輸出token=int(用了.get("output_tokens", 0)),
            快取讀取token=用了.get("cache_read_input_tokens"),
            思考token=(用了.get("output_tokens_details") or {}).get("thinking_tokens"),
            成本美金=信封.get("total_cost_usd"),
        ),
        結構化輸出=信封.get("structured_output"),
        原始輸出=(信封,),
    )


def _codex的文字(事件們: list[dict[str, Any]]) -> str:
    說過的 = [
        str(項.get("text") or "")
        for 事件 in 事件們
        if 事件.get("type") == "item.completed"
        if (項 := 事件.get("item") or {}).get("type") == "agent_message"
    ]
    return 說過的[-1] if 說過的 else ""


def _codex的錯誤訊息(事件們: list[dict[str, Any]]) -> str:
    片段 = [
        str((事件.get("error") or {}).get("message") or 事件.get("message") or "")
        for 事件 in 事件們
        if 事件.get("type") in {"turn.failed", "error"}
    ]
    片段 += [
        str((事件.get("item") or {}).get("message") or "")
        for 事件 in 事件們
        if (事件.get("item") or {}).get("type") == "error"
    ]
    return "\n".join(片段)


def 解析codex(標準輸出: str, 結束碼: int) -> 回應:
    """`codex exec --json` 的 JSONL 事件流。"""
    事件們 = _逐行json(標準輸出)
    完成 = [事件 for 事件 in 事件們 if 事件.get("type") == "turn.completed"]
    if not 事件們 or not (完成 or any(事.get("type") == "turn.failed" for 事 in 事件們)):
        return _壞掉(結束碼, _codex的錯誤訊息(事件們) or 標準輸出, 事件們)
    順利 = bool(完成) and 結束碼 == 0
    代碼 = 失敗代碼.無 if 順利 else _分類(結束碼, None, _codex的錯誤訊息(事件們))
    用了: dict[str, Any] = (完成[-1].get("usage") if 完成 else {}) or {}
    開場 = next((事 for 事 in 事件們 if 事.get("type") == "thread.started"), {})
    return 回應(
        文字=_codex的文字(事件們),
        終局=終局判定(代碼),
        失敗代碼=代碼,
        原始結束碼=結束碼,
        對話識別碼=開場.get("thread_id"),
        用量=用量(
            輸入token=int(用了.get("input_tokens", 0)),
            輸出token=int(用了.get("output_tokens", 0)),
            快取讀取token=用了.get("cached_input_tokens"),
            思考token=用了.get("reasoning_output_tokens"),
        ),
        原始輸出=tuple(事件們),
    )


def _agy的信封(標準輸出: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """agy 有兩種輸出：整份一個 JSON，或 NDJSON 裡 `event == "result"` 那一則。"""
    物件們 = _逐行json(標準輸出)
    整份 = 標準輸出.strip()
    if 整份.startswith("{"):
        try:
            解出 = json.loads(整份)
        except json.JSONDecodeError:
            解出 = None
        if isinstance(解出, dict) and "status" in 解出:
            return 解出, [解出]
    結果 = [物件.get("result") for 物件 in 物件們 if 物件.get("event") == "result"]
    末筆 = 結果[-1] if 結果 else None
    return (末筆 if isinstance(末筆, dict) else None), 物件們


def 解析agy(標準輸出: str, 結束碼: int) -> 回應:
    """`agy -p --output-format json`（單一物件）或 `stream-json`（NDJSON）。"""
    信封, 原始 = _agy的信封(標準輸出)
    if 信封 is None:
        return _壞掉(結束碼, 標準輸出, 原始)
    順利 = 信封.get("status") == "SUCCESS" and 結束碼 == 0
    代碼 = 失敗代碼.無 if 順利 else _分類(結束碼, None, str(信封.get("error") or ""))
    用了: dict[str, Any] = 信封.get("usage") or {}
    return 回應(
        文字=str(信封.get("response") or ""),
        終局=終局判定(代碼),
        失敗代碼=代碼,
        原始結束碼=結束碼,
        對話識別碼=信封.get("conversation_id") or None,
        用量=用量(
            輸入token=int(用了.get("input_tokens", 0)),
            輸出token=int(用了.get("output_tokens", 0)),
            快取讀取token=用了.get("cache_read_tokens"),
            思考token=用了.get("thinking_tokens"),
        ),
        結構化輸出=信封.get("structured_output"),
        原始輸出=tuple(原始),
    )
