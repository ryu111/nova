"""本地腦的工具迴圈：送 tools → 收 tool_calls → 執行 → 塞回 messages → 再問。

**走 HTTP，所以住整合層**——用一個照腳本回應的假端點，不打真模型。
真模型的能力量測在 `test_本地能力邊界.py`。
"""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from nova.契約.模型回應 import 終局
from nova.契約.角色 import 呼叫選項, 權限
from nova.載體.模型.本地 import 本地腦


class 假端點:
    """照腳本回應的 `/v1/chat/completions`。每次被問就吐下一份腳本。"""

    def __init__(self, 腳本: list[dict[str, Any]]) -> None:
        """`腳本` 用完了就一直重複最後一份——測「一直發工具呼叫」要靠這個。"""
        self.腳本 = 腳本
        self.收到: list[dict[str, Any]] = []
        self._伺服器: HTTPServer | None = None

    def __enter__(self) -> str:
        """起一個只聽 localhost 的 HTTP server，回它的網址。"""
        外層 = self

        class 處理器(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 —— BaseHTTPRequestHandler 的介面
                長度 = int(self.headers.get("Content-Length", 0))
                外層.收到.append(json.loads(self.rfile.read(長度)))
                回 = 外層.腳本[min(len(外層.收到) - 1, len(外層.腳本) - 1)]
                身體 = json.dumps(回).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(身體)))
                self.end_headers()
                self.wfile.write(身體)

            def log_message(self, *_: Any) -> None:
                """安靜。pytest 的輸出不該被 HTTP log 淹掉。"""

        self._伺服器 = HTTPServer(("127.0.0.1", 0), 處理器)
        threading.Thread(target=self._伺服器.serve_forever, daemon=True).start()
        埠 = self._伺服器.server_address[1]
        return f"http://127.0.0.1:{埠}/v1"

    def __exit__(self, *_: object) -> None:
        """收掉 server。不收的話 pytest 跑完會卡在那個 thread 上。"""
        if self._伺服器 is not None:
            self._伺服器.shutdown()


def 回文字(文字: str, *, 入: int = 10, 出: int = 5) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": 文字}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 入, "completion_tokens": 出},
    }


def 回工具(名稱: str, 參數: dict[str, str], *, 入: int = 10, 出: int = 5) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": 名稱, "arguments": json.dumps(參數)},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 入, "completion_tokens": 出},
    }


@pytest.fixture
def 工作區(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "檔.txt").write_text("裡面寫著答案", encoding="utf-8")
    yield tmp_path


def _問(網址: str, 工作區: Path, *, 可以做什麼: 權限 = 權限.唯讀) -> Any:
    return 本地腦(網址=網址).詢問(
        "讀那個檔案，告訴我裡面寫什麼",
        選項=呼叫選項(模型="假模型", 權限=可以做什麼, 工作目錄=工作區, 逾時秒=10),
    )


class Test一輪工具呼叫走得完:
    """模型要工具 → nova 執行 → 結果塞回 messages → 模型收尾。"""

    def test_工具結果會塞回去再問一次(self, 工作區: Path) -> None:
        端 = 假端點([回工具("read_file", {"path": "檔.txt"}), 回文字("檔案裡寫著答案")])
        with 端 as 網址:
            答 = _問(網址, 工作區)
        assert 答.終局 is 終局.成功
        assert 答.文字 == "檔案裡寫著答案"
        assert len(端.收到) == 2, "沒有第二回合＝工具結果沒塞回去"

    def test_第二回合帶著工具結果(self, 工作區: Path) -> None:
        """**塞回去的內容要是真的讀到的東西**，不是一句「已執行」。"""
        端 = 假端點([回工具("read_file", {"path": "檔.txt"}), 回文字("好")])
        with 端 as 網址:
            _問(網址, 工作區)
        訊息們 = 端.收到[1]["messages"]
        工具回覆 = [訊 for 訊 in 訊息們 if 訊.get("role") == "tool"]
        assert 工具回覆, "第二回合沒有 role=tool 的訊息"
        assert "裡面寫著答案" in 工具回覆[0]["content"]

    def test_工具規格有送出去(self, 工作區: Path) -> None:
        端 = 假端點([回文字("不用工具")])
        with 端 as 網址:
            _問(網址, 工作區)
        名字們 = {規["function"]["name"] for 規 in 端.收到[0].get("tools", [])}
        assert {"read_file", "grep"} <= 名字們

    def test_唯讀時不送寫入工具(self, 工作區: Path) -> None:
        端 = 假端點([回文字("好")])
        with 端 as 網址:
            _問(網址, 工作區, 可以做什麼=權限.唯讀)
        名字們 = {規["function"]["name"] for 規 in 端.收到[0].get("tools", [])}
        assert "write_file" not in 名字們

    def test_可編輯時送得出寫入工具(self, 工作區: Path) -> None:
        端 = 假端點([回文字("好")])
        with 端 as 網址:
            _問(網址, 工作區, 可以做什麼=權限.可編輯)
        名字們 = {規["function"]["name"] for 規 in 端.收到[0].get("tools", [])}
        assert "write_file" in 名字們


class Test迴圈一定要有上限:
    """**沒有停止規則的迴圈是成本漏洞**（`AGENT_ARCHITECTURE` §3.2）。

    模型可以一直發同一個工具呼叫——不是因為壞了，是因為它覺得還沒讀夠。
    本地腦不燒額度但燒時間與電，而且卡住的樣子是「nova 沒有回應」。
    """

    def test_一直發工具呼叫會撞上限(self, 工作區: Path) -> None:
        端 = 假端點([回工具("read_file", {"path": "檔.txt"})])  # 永遠只回工具呼叫
        with 端 as 網址:
            答 = _問(網址, 工作區)
        assert 答.終局 is not 終局.成功, "無限發工具卻收在成功＝上限沒生效"
        assert len(端.收到) <= 12, f"發了 {len(端.收到)} 次還沒停"

    def test_撞上限要講得出原因(self, 工作區: Path) -> None:
        """收在一個看不出原因的失敗，等於要人去翻 log 才知道發生什麼事。"""
        端 = 假端點([回工具("read_file", {"path": "檔.txt"})])
        with 端 as 網址:
            答 = _問(網址, 工作區)
        assert "工具" in 答.文字 and ("上限" in 答.文字 or "回合" in 答.文字), 答.文字


class Test每一回合的用量都要算:
    """**算錯的上限也是成本漏洞**——`接力腦` 踩過一模一樣的坑。

    迴圈內圈跑三回合就是三次呼叫，只回最後一次的用量，
    前兩次燒掉的在 `單次最多token` 的檢查裡憑空消失。
    """

    def test_三回合的用量要加總(self, 工作區: Path) -> None:
        腳本 = [
            回工具("read_file", {"path": "檔.txt"}, 入=100, 出=10),
            回工具("grep", {"pattern": "答案"}, 入=200, 出=20),
            回文字("讀完了", 入=300, 出=30),
        ]
        端 = 假端點(腳本)
        with 端 as 網址:
            答 = _問(網址, 工作區)
        assert 答.用量.輸入token == 100 + 200 + 300
        assert 答.用量.輸出token == 10 + 20 + 30


class Test工具出錯不准讓整輪垮掉:
    """模型會叫不存在的檔案、會給越界的路徑——那是**正常的**，不是異常。

    把錯誤訊息回給它，它下一回合就能改。整輪垮掉的話那次呼叫全白費。
    """

    def test_讀不到的檔案把錯誤回給模型(self, 工作區: Path) -> None:
        腳本 = [回工具("read_file", {"path": "不存在.txt"}), 回文字("那我換一個")]
        端 = 假端點(腳本)
        with 端 as 網址:
            答 = _問(網址, 工作區)
        assert 答.終局 is 終局.成功
        工具回覆 = [訊 for 訊 in 端.收到[1]["messages"] if 訊.get("role") == "tool"]
        assert "不存在" in 工具回覆[0]["content"]

    def test_越界路徑把錯誤回給模型而不是靜默放行(self, 工作區: Path) -> None:
        腳本 = [回工具("read_file", {"path": "../../etc/passwd"}), 回文字("好吧")]
        端 = 假端點(腳本)
        with 端 as 網址:
            _問(網址, 工作區)
        工具回覆 = [訊 for 訊 in 端.收到[1]["messages"] if 訊.get("role") == "tool"]
        assert "工作目錄" in 工具回覆[0]["content"]
        assert "root:" not in 工具回覆[0]["content"], "真的讀到了 /etc/passwd"


class Test回合快用完要催收尾:
    """帳本挖出來的病：讀完該讀的之後，模型不知道該收尾，開始用 grep 填時間。

    兩個 run 共 28 次工具呼叫、**`write_file` 零次**，最後全部撞上 8 回合上限
    （`docs/負控紀錄.md` 的「規則被上下文淹掉這個診斷是錯的」一節）。
    grep 的對象到後面甚至是模型自己幻想出來的函式名。

    **催收尾是迴圈的責任，不是提示的責任**——提示裡的是懇求，
    包住執行者的程式碼裡才是保證。
    """

    def test_回合快用完時要把剩幾回合講出來(self, 工作區: Path) -> None:
        """腳本只有一份＝模型永遠在要工具，一路撞到上限。"""
        端 = 假端點([回工具("grep", {"pattern": "找不到的東西"})])
        with 端 as 網址:
            _問(網址, 工作區)
        催過的 = [
            訊
            for 請求 in 端.收到
            for 訊 in 請求["messages"]
            if 訊.get("role") == "user" and "回合" in str(訊.get("content", ""))
        ]
        assert 催過的, "撞到上限都沒催過一次收尾"

    def test_一開始不催(self, 工作區: Path) -> None:
        """**前幾回合是正常探索**，催了只會佔 context 又打斷它。"""
        端 = 假端點([回工具("read_file", {"path": "檔.txt"}), 回文字("好")])
        with 端 as 網址:
            _問(網址, 工作區)
        第一次 = 端.收到[0]["messages"]
        assert len(第一次) == 1, f"第一回合就多塞了東西：{第一次}"

    def test_已經寫過檔就不催(self, 工作區: Path) -> None:
        """它在做正事，催是噪音。催的觸發條件是**一個檔都還沒寫**。"""
        端 = 假端點([回工具("write_file", {"path": "新的.txt", "content": "寫了"})])
        with 端 as 網址:
            _問(網址, 工作區, 可以做什麼=權限.可編輯)
        催過的 = [
            訊
            for 請求 in 端.收到
            for 訊 in 請求["messages"]
            if 訊.get("role") == "user" and "回合" in str(訊.get("content", ""))
        ]
        assert not 催過的, f"寫過檔還在催：{催過的}"


class Test最後幾回合只准寫:
    """催了還不寫，就把找東西的工具收掉。

    倒數提醒（`Test回合快用完要催收尾`）是**懇求**，模型可以不理；
    把 `grep` 與 `read_file` 從 tools 陣列拿掉才是**保證**——
    它連發出那個呼叫的形狀都沒有。

    唯讀角色最後幾回合會拿到空的 tools 陣列，那是對的：
    唯讀的產出本來就是文字報告，不是檔案。
    """

    def test_最後兩回合不給找東西的工具(self, 工作區: Path) -> None:
        端 = 假端點([回工具("grep", {"pattern": "找不到的東西"})])
        with 端 as 網址:
            _問(網址, 工作區, 可以做什麼=權限.可編輯)
        最後兩次 = 端.收到[-2:]
        for 第幾, 請求 in enumerate(最後兩次, start=len(端.收到) - 1):
            名字們 = {規["function"]["name"] for 規 in 請求.get("tools", [])}
            assert "grep" not in 名字們, f"第 {第幾} 回合還給 grep：{名字們}"
            assert "read_file" not in 名字們, f"第 {第幾} 回合還給 read_file：{名字們}"

    def test_最後兩回合還留著寫入(self, 工作區: Path) -> None:
        """**收掉的是找東西，不是做事情。**收光了它連收尾都做不到。"""
        端 = 假端點([回工具("grep", {"pattern": "找不到的東西"})])
        with 端 as 網址:
            _問(網址, 工作區, 可以做什麼=權限.可編輯)
        名字們 = {規["function"]["name"] for 規 in 端.收到[-1].get("tools", [])}
        assert 名字們 == {"write_file"}, f"最後一回合的工具不對：{名字們}"

    def test_前面幾回合照給(self, 工作區: Path) -> None:
        端 = 假端點([回工具("grep", {"pattern": "找不到的東西"})])
        with 端 as 網址:
            _問(網址, 工作區, 可以做什麼=權限.可編輯)
        名字們 = {規["function"]["name"] for 規 in 端.收到[0].get("tools", [])}
        assert {"read_file", "grep", "write_file"} <= 名字們
