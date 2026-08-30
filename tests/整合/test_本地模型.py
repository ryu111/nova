"""本地模型的整合測試。

假伺服器驗轉遞形狀，`真端點` 驗真的可達性；兩者都會碰 socket，所以住整合層。
設計理由見 `src/nova/載體/模型/本地.py`。
"""

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from nova.契約.模型回應 import 失敗代碼, 終局
from nova.契約.角色 import 呼叫選項, 權限
from nova.載體.模型.本地 import 本地腦, 預設本地網址

_回一句 = {
    "id": "chatcmpl-abc123",
    "choices": [{"message": {"content": "收到"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 3},
}
_型號表 = {"data": [{"id": "Ornith-1.5-9B-MLX"}, {"id": "Ornith-1.5-9B-MLX-4bit"}]}


class _假伺服器(BaseHTTPRequestHandler):
    """OpenAI 相容端點的最小替身。`狀態碼` 只控制對話回應，測試改它來模擬上游錯誤。"""

    狀態碼 = 200
    #: 裝慢幾秒。**假伺服器太快的話逾時那條路根本測不到**——
    #: 第一版用 `逾時秒=0.001` 就以為測到了，實際上伺服器在 1 毫秒內就回完了。
    慢幾秒 = 0.0
    收到的請求: dict[str, Any] = {}  # noqa: RUF012 —— 測試替身共用，不是資料模型

    def log_message(self, *_: object) -> None:
        """別把每個請求印到 pytest 的輸出裡。"""

    def do_GET(self) -> None:  # noqa: N802 —— BaseHTTPRequestHandler 規定的名字
        self._回(200, _型號表)

    def do_POST(self) -> None:  # noqa: N802 —— 同上
        time.sleep(type(self).慢幾秒)
        長度 = int(self.headers.get("Content-Length", "0"))
        type(self).收到的請求 = json.loads(self.rfile.read(長度))
        if type(self).狀態碼 != 200:  # noqa: PLR2004 —— 200 就是 200
            self._回(type(self).狀態碼, {"error": "壞了"})
            return
        self._回(200, _回一句)

    def _回(self, 碼: int, 內容: dict[str, Any]) -> None:
        身體 = json.dumps(內容).encode("utf-8")
        self.send_response(碼)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(身體)))
        self.end_headers()
        self.wfile.write(身體)


@pytest.fixture
def 假端點() -> Iterator[str]:
    _假伺服器.狀態碼 = 200
    _假伺服器.慢幾秒 = 0.0
    _假伺服器.收到的請求 = {}
    伺服器 = HTTPServer(("127.0.0.1", 0), _假伺服器)
    threading.Thread(target=伺服器.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{伺服器.server_port}/v1"
    finally:
        伺服器.shutdown()
        伺服器.server_close()


def test_問一次拿得到文字(假端點: str) -> None:
    答 = 本地腦(網址=假端點).詢問("在嗎")

    assert 答.文字 == "收到"
    assert 答.終局 is 終局.成功


def test_token數從usage讀出來(假端點: str) -> None:
    答 = 本地腦(網址=假端點).詢問("在嗎")

    assert (答.用量.輸入token, 答.用量.輸出token) == (12, 3)


def test_成本是零不是None(假端點: str) -> None:
    """**這不是估算，是事實**：本地跑沒有 API 帳單。

    回 None 的話，一次混著本地與 claude 的執行會整個算不出成本
    （「有一顆給不出來就整個不給」）——而那次其實算得出來。
    """
    答 = 本地腦(網址=假端點).詢問("在嗎")

    assert 答.用量.成本美金 == 0.0


def test_對話識別碼從回應的id來(假端點: str) -> None:
    答 = 本地腦(網址=假端點).詢問("在嗎")

    assert 答.對話識別碼 == "chatcmpl-abc123"


def test_沒指定型號就問伺服器有哪些(假端點: str) -> None:
    """**不寫死型號。** 寫死的話換一顆模型就要改 nova 的原始碼。"""
    本地腦(網址=假端點).詢問("在嗎")

    assert _假伺服器.收到的請求["model"] == "Ornith-1.5-9B-MLX"


def test_指定型號就用指定的(假端點: str) -> None:
    本地腦(網址=假端點).詢問("在嗎", 選項=呼叫選項(模型="Ornith-1.5-9B-MLX-4bit"))

    assert _假伺服器.收到的請求["model"] == "Ornith-1.5-9B-MLX-4bit"


class Test做不到就明講:
    """**這一組是這個檔案的重點。**

    本地模型只有腦，沒有工具、沒有 session。默默忽略那些選項的話，
    工作流會以為檔案改好了，然後在驗證階段才發現什麼都沒發生——
    而那時候看起來像是「模型做錯了」，不是「這顆腦根本做不到」。
    """

    def test_要求可編輯就明講做不到(self, 假端點: str) -> None:
        答 = 本地腦(網址=假端點).詢問("改個檔", 選項=呼叫選項(權限=權限.可編輯))

        assert 答.終局 is 終局.確定失敗
        assert 答.失敗代碼 is 失敗代碼.用法錯誤
        assert "工具" in 答.文字 or "編輯" in 答.文字

    def test_要求全開也一樣(self, 假端點: str) -> None:
        答 = 本地腦(網址=假端點).詢問("改個檔", 選項=呼叫選項(權限=權限.全開))

        assert 答.終局 is 終局.確定失敗

    def test_要求續接就明講做不到(self, 假端點: str) -> None:
        """沒有 session 就接不下去。假裝接得下去會讓前情整段消失。"""
        答 = 本地腦(網址=假端點).詢問("接著講", 選項=呼叫選項(續接="chatcmpl-abc123"))

        assert 答.終局 is 終局.確定失敗
        assert 答.失敗代碼 is 失敗代碼.用法錯誤

    def test_唯讀是可以的(self, 假端點: str) -> None:
        """**這支防的是擋過頭。** 全部擋掉的話這顆腦一次都用不到。"""
        答 = 本地腦(網址=假端點).詢問("在嗎", 選項=呼叫選項(權限=權限.唯讀))

        assert 答.終局 is 終局.成功


class Test壞掉的時候:
    """這裡驗真的 socket 行為；例外分類的窮舉在單元層。"""

    def test_伺服器回500是上游確定失敗(self, 假端點: str) -> None:
        _假伺服器.狀態碼 = 500

        答 = 本地腦(網址=假端點).詢問("在嗎")

        assert 答.終局 is 終局.確定失敗
        assert 答.失敗代碼 is 失敗代碼.上游

    def test_連不上是未安裝(self) -> None:
        """**「伺服器沒開」跟「CLI 沒裝」是同一件事**：那個東西根本不在。

        分成兩種代碼的話，接力鏈的降級規則就要寫兩份。
        """
        答 = 本地腦(網址="http://127.0.0.1:1/v1").詢問("在嗎")

        assert 答.終局 is 終局.確定失敗
        assert 答.失敗代碼 is 失敗代碼.未安裝

    def test_逾時是結果未知不是確定失敗(self, 假端點: str) -> None:
        """請求可能已經出門了。**確定失敗會讓上層放心重跑**，而那會重做副作用。

        伺服器要真的裝慢——第一版只把逾時設成 0.001 秒，但假伺服器
        在 1 毫秒內就回完了，那條路根本沒走到。
        """
        _假伺服器.慢幾秒 = 0.3

        答 = 本地腦(網址=假端點).詢問("在嗎", 選項=呼叫選項(逾時秒=0.15))

        assert 答.終局 is 終局.結果未知
        assert 答.失敗代碼 is 失敗代碼.逾時


def test_名稱是ASCII的local() -> None:
    """家族名會流進帳本的 `family` 欄位被 grep，屬於跨程序 semantic id。"""
    assert 本地腦(網址="http://127.0.0.1:1/v1").名稱 == "local"


def test_工作目錄被忽略但不會炸(假端點: str, tmp_path: Path) -> None:
    """沒有工具就沒有工作目錄可言。忽略是對的，**炸掉不是**。"""
    答 = 本地腦(網址=假端點).詢問("在嗎", 選項=呼叫選項(工作目錄=tmp_path))

    assert 答.終局 is 終局.成功


@pytest.fixture
def 真端點網址() -> str:
    """探真端點；本機沒開服務就跳過。"""
    網址 = 預設本地網址()
    try:
        with urllib.request.urlopen(f"{網址}/models", timeout=2):  # noqa: S310
            pass
    except urllib.error.HTTPError:
        # HTTPError 代表已經連到端點，不能把上游錯誤當成服務沒開而跳過。
        raise
    except OSError:
        pytest.skip(f"本機沒有推論伺服器（{網址}）")

    return 網址


@pytest.mark.真端點
def test_真端點列得出模型清單(真端點網址: str) -> None:
    with urllib.request.urlopen(f"{真端點網址}/models", timeout=2) as 回:  # noqa: S310
        型號表 = json.loads(回.read().decode("utf-8"))

    型號們 = 型號表.get("data")
    assert isinstance(型號們, list) and 型號們, "真伺服器的模型清單不能是空的"
    assert all(
        isinstance(型號, dict) and isinstance(型號.get("id"), str) and 型號["id"] for 型號 in 型號們
    ), "模型清單的每一項都要有型號識別碼"


@pytest.mark.真端點
def test_真的打一次本機推論伺服器(真端點網址: str) -> None:
    """**假伺服器證明的是轉遞形狀，不是可達性**（CLAUDE.md 判準三）。

    假的 `http.server` 測得出「參數有沒有組對、錯誤有沒有分類對」，
    測不出「真的模型伺服器吃不吃這個請求」——欄位名差一個字就整個不動，
    而假伺服器不會抱怨。

    這一支要本機真的跑著 omlx-server／llama.cpp／ollama。
    連不上就跳過，不會讓套件變紅。
    """
    答 = 本地腦(網址=真端點網址).詢問("只回四個字：本地通了")

    assert 答.終局 is 終局.成功, 答.文字
    assert 答.文字.strip()
    assert 答.用量.輸入token > 0, "真伺服器一定會回輸入用量，回 0 代表欄位讀錯了"
    assert 答.用量.輸出token > 0, "真伺服器一定會回輸出用量，回 0 代表欄位讀錯了"
    assert 答.用量.成本美金 == 0.0
