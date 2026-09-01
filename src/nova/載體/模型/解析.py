"""三家 CLI 的 envelope → nova 的 `回應`。

全部是純函式：吃字串與結束碼，吐 schema。純函式才能用實錄餵測試，
不必啟動任何程序、不燒任何 token。

三條共通規則（設計理由見 docs/設計/02-統一LLM介面.md）：

1. **不准拿結束碼 0 當成功**——三家實測，模型拒答／答錯一律 exit 0。
2. **要容忍認不得的行與事件**——codex 的第一行是純文字，cmux shim 還會插事件進來。
3. **整份解不動時 fail-closed 回 `unknown`**，不是靜默成功。
"""

import json
import re
from dataclasses import replace
from typing import Any

from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局, 終局判定

#: JSON 規格說字串裡的控制字元必須跳脫，但真實工具會直接吐原始字元
#: （實測 agy 的 `response` 欄位偶爾夾了未跳脫的控制字元，嚴格模式當場解不動）。
#: 解不動的下場是 fail-closed 回「結果未知」——那比寬鬆解析危險得多。
_寬鬆解析 = json.JSONDecoder(strict=False)


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

#: 額度／配額用完的字樣，三家都查證過（出處逐條寫在
#: `tests/單元/test_模型解析.py::Test額度字串三家都要涵蓋` 的 docstring）。
#:
#: **只挑穩定片段**——原文帶著「try again at Sep 13th, 2026 7:11 PM」、
#: 「Resets in 143h57m55s」這種動態時間，整句拿來比對永遠不會命中。
#:
#: `hit your \w+ limit` 為什麼是樣式不是字串：claude 那組的中間字是
#: **方案期間或型號名**（session／weekly／Opus／Sonnet），而型號會長出新的。
#: 寫死四個，出第五個就靜默失效——**靜默失效的分類器比沒有更糟**。
#:
#: `individual quota reached` 帶著 `429` 但**不是**暫時限流（agy 那條要等 143 小時），
#: 所以它必須排在 HTTP 狀態分類前面。
_額度樣式 = r"hit your \w+ limit|usage limit reached|quota exceeded|individual quota reached"

#: 權限／沙箱擋下來的字樣。**每一條都有實跑證據**，不是想像出來的：
#:
#: - `auto-denied`、`permission that headless mode` —— agy 的 headless 權限系統
#:   （原文：`a tool required the "read_url" permission that headless mode
#:   cannot prompt for, so it was auto-denied.`）
#: - `operation not permitted` —— codex 的 `workspace-write` 沙箱（設計文件 02 有貼原文）
#: - `permission denied` —— POSIX 的通用講法，走 shell 的工具都可能吐這句
#:
#: **不准憑想像加字串**：加一條永遠不會命中的規則，比沒有更糟——
#: 它讓分類器看起來有在守，而其實沒有。
_權限關鍵詞 = (
    "auto-denied",
    "permission that headless mode",
    "operation not permitted",
    "permission denied",
)


#: 關鍵詞 → 失敗代碼。**加一種分類＝加一列，不是回來改 if 鏈**（開放封閉）。
#:
#: **順序有意義**：先命中的先贏。認證擺在額度前面，因為「額度用完」的訊息
#: 有時候也帶著帳號字樣，而認證是更靠近源頭的判斷。
def _任一個(詞們: tuple[str, ...]) -> re.Pattern[str]:
    """一串固定字樣 → 一個樣式。用 `escape` 是因為裡面有 `(`、`.` 這種字元。"""
    return re.compile("|".join(re.escape(詞) for 詞 in 詞們))


#: 樣式 → 失敗代碼。**加一種分類＝加一列，不是回來改 if 鏈**（開放封閉）。
#:
#: **順序有意義**：先命中的先贏。認證擺在額度前面，因為「額度用完」的訊息
#: 有時候也帶著帳號字樣，而認證是更靠近源頭的判斷。
#:
#: 統一用樣式不用字串比對：多數分類其實只要固定字樣（`_任一個` 幫它們轉），
#: 但額度那組的變體是**會長出來的**，非樣式不可。兩種機制並存會讓下一個人
#: 加規則時得先問「這條該加哪一邊」——一種就好。
_樣式表: tuple[tuple[re.Pattern[str], 失敗代碼], ...] = (
    (_任一個(_模型關鍵詞), 失敗代碼.模型不存在),
    (_任一個(_認證關鍵詞), 失敗代碼.認證),
    (re.compile(_額度樣式), 失敗代碼.額度耗盡),
    (_任一個(_權限關鍵詞), 失敗代碼.權限被擋),
)

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
            解出 = _寬鬆解析.decode(乾淨)
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
    for 樣式, 代碼 in _樣式表:
        if 樣式.search(低):
            return 代碼
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


def _解析claude(標準輸出: str, 結束碼: int) -> 回應:
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
            快取建立token=用了.get("cache_creation_input_tokens"),
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


def _解析codex(標準輸出: str, 結束碼: int) -> 回應:
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
            解出 = _寬鬆解析.decode(整份)
        except json.JSONDecodeError:
            解出 = None
        if isinstance(解出, dict) and "status" in 解出:
            return 解出, [解出]
    結果 = [物件.get("result") for 物件 in 物件們 if 物件.get("event") == "result"]
    末筆 = 結果[-1] if 結果 else None
    return (末筆 if isinstance(末筆, dict) else None), 物件們


def _解析agy(標準輸出: str, 結束碼: int) -> 回應:
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


#: stderr 可能很長（堆疊、進度條）。截斷不是省空間，是**不要讓一段噪音把
#: 帳本與終端機洗掉**——真正的第一行通常就講完了。
診斷上限 = 2000


def _補上診斷(答: 回應, 標準錯誤: str) -> 回應:
    """失敗而且沒話可說時，把 stderr 當證據。

    不補的話，`usage`（旗標給錯）這種失敗會回一個**空字串**——
    使用者只看得到「確定失敗 usage」，看不到是哪個旗標錯了。
    診斷丟掉比結論丟掉更難查，因為它看起來完全正常。
    """
    if 答.終局 is 終局.成功 or 答.文字.strip():
        return 答
    診斷 = 標準錯誤.strip()
    if not 診斷:
        return 答
    # stderr 是**第一次**有真的文字可以分類——`_分類` 先前只看得到 stdout，
    # 而失敗的時候 stdout 常常是空的。所以這裡要再分一次。
    #
    # **只從 `未知` 往上升。** 已經分出 `逾時`／`認證` 的不准被覆蓋：
    # 那些是更靠近源頭的判斷（runner 自己的 deadline、HTTP 狀態），
    # 拿一段 stderr 的字串比對去蓋掉它們是往下降不是往上升。
    代碼 = 答.失敗代碼
    if 代碼 is 失敗代碼.未知:
        代碼 = _分類(答.原始結束碼, None, 診斷)
    if 代碼 is 答.失敗代碼:
        return replace(答, 文字=診斷[:診斷上限])
    # 代碼變了，終局就要跟著重算——**由 `終局表` 決定，不是在這裡臨場判**。
    # 這會把某些「結果未知」升成「確定失敗」（例如額度用完：請求被拒、
    # 模型一個字都沒跑），而那個方向正是 at-most-once 最敏感的方向。
    # 所以它必須由表決定：表裡每一列旁邊都寫著「為什麼這樣算」，
    # 臨場判會讓那個理由散落在各處而且沒人守。
    return replace(答, 文字=診斷[:診斷上限], 失敗代碼=代碼, 終局=終局判定(代碼))


def _成功但沒話說算未知(答: 回應, 標準錯誤: str) -> 回應:
    """CLI 說成功、卻一個字都沒回，那不是成功，是不知道發生什麼事。

    實測（agy 生圖那一路）：模型先呼叫 `generate_image`（**成功**，圖產在
    `~/.gemini/antigravity-cli/brain/<sid>/*.jpg`），再呼叫 `run_command` 想用
    `sips` 轉檔搬出來，這一步被權限擋下——`{"error":{"type":"TOOL_ERROR",
    "message":"permission check failed ... user denied"}}`。
    而 envelope 仍然是 `status: SUCCESS`、`error: null`、`response: ""`。
    診斷被整個吞掉，只剩一個空字串。

    （2026-08-29 補正：原本這裡寫「`generate_image` 的 `state: ERROR`」，
    抓原始串流之後確認錯的是後續那道 shell，不是生圖本身。**守則沒變**，
    變的只是錯誤的歸屬——這種誤記會讓下一個人去修錯的地方。）

    這種情況只能是**結果未知**：工具動過了，做到哪不知道。
    當成功會讓上游以為事情辦完了；當確定失敗又會讓接力去重做副作用。
    三值就是為了這一格。
    """
    if 答.終局 is not 終局.成功 or 答.文字.strip():
        return 答
    # **stderr 優先於罐頭句。** 順序寫反過（先填罐頭再看 stderr）就等於
    # 用自己的填充句把真的證據擋在門外——那正是這條 bug 原本的樣子。
    診斷 = 標準錯誤.strip()
    # 空回應這條路**不走 `_壞掉`**，所以分類要在這裡自己做一次。
    # 少了這一行，agy 的 auto-deny 會永遠是 `unknown`——
    # 而那正是「換腦沒用卻一直換」的那一格。
    低 = 診斷.lower()
    代碼 = 失敗代碼.權限被擋 if any(詞 in 低 for 詞 in _權限關鍵詞) else 失敗代碼.未知
    if 代碼 is 失敗代碼.權限被擋:
        環境說明 = "\n（環境提示：--add-dir 給的是檔案存取、不涵蓋 command）"
        文字 = f"{診斷[:診斷上限]}{環境說明}" if 診斷 else "CLI 回報成功但權限被拒"
        首筆 = 答.原始輸出[0] if 答.原始輸出 and isinstance(答.原始輸出[0], dict) else {}
        有跑過輪次 = int(首筆.get("num_turns") or 0) > 0
        return replace(
            答,
            終局=終局.結果未知 if 有跑過輪次 else 終局判定(代碼),
            失敗代碼=代碼,
            文字=文字,
        )
    return replace(
        答,
        終局=終局.結果未知,
        # **代碼指名道姓是 `空輸出`，不是沿用 `未知`。** 下游的重試判斷要靠它
        # 認出這一種（`轉接.空輸出該重試`），帳本也要靠它數得出「這輪空了幾次」。
        失敗代碼=失敗代碼.空輸出,
        文字=診斷[:診斷上限] if 診斷 else "CLI 回報成功但一個字都沒說——工具可能失敗了而錯誤被吞掉",
    )


def 解析claude(標準輸出: str, 結束碼: int, 標準錯誤: str = "") -> 回應:
    """`claude -p --output-format json` 的輸出。"""
    return _補上診斷(_成功但沒話說算未知(_解析claude(標準輸出, 結束碼), 標準錯誤), 標準錯誤)


def 解析codex(標準輸出: str, 結束碼: int, 標準錯誤: str = "") -> 回應:
    """`codex exec --json` 的 JSONL 事件流。"""
    return _補上診斷(_成功但沒話說算未知(_解析codex(標準輸出, 結束碼), 標準錯誤), 標準錯誤)


def 解析agy(標準輸出: str, 結束碼: int, 標準錯誤: str = "") -> 回應:
    """`agy -p --output-format json`（單一物件）或 `stream-json`（NDJSON）。"""
    return _補上診斷(_成功但沒話說算未知(_解析agy(標準輸出, 結束碼), 標準錯誤), 標準錯誤)


#: 三家對「這段對話」的叫法。同一個東西三個名字，所以掃鍵不挑家。
_對話識別碼的鍵 = ("thread_id", "conversation_id", "session_id")


def 撿對話識別碼(標準輸出: str) -> str | None:
    """從（可能被截斷的）輸出裡撿出對話識別碼。

    **給逾時那條路用的。** 正常跑完的時候各家的解析器自己會給；
    但被殺掉的時候走不到那條路（沒有 `turn.completed`），
    而 sid 就在第一行。

    取**第一個**不是最後一個：一次執行只有一段對話，
    後面再出現多半是雜訊，開場那個才是真的。
    """
    for 物 in _逐行json(標準輸出):
        for 鍵 in _對話識別碼的鍵:
            值 = 物.get(鍵)
            if isinstance(值, str) and 值:
                return 值
        巢 = 物.get("init")
        if isinstance(巢, dict):
            值 = 巢.get("conversation_id")
            if isinstance(值, str) and 值:
                return 值
    return None
