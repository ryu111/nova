"""本地腦工具呼叫的帳本記錄整合測試。

本地腦在跑工具迴圈（_跑工具迴圈）時，每一筆工具呼叫都要留下結構化證據進帳本。
走 HTTP，所以住整合層——用假端點模擬模型回應。
"""

import io
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from nova.契約.帳本 import 事件種類
from nova.契約.模型回應 import 終局
from nova.契約.角色 import 呼叫選項, 權限
from nova.載體.帳本 import 帳本, 建帳本
from nova.載體.模型.本地 import 本地腦
from nova.載體.模型.記帳 import 記帳腦


class 假端點:
    """照腳本回應的 `/v1/chat/completions`。每次被問就吐下一份腳本。"""

    def __init__(self, 腳本: list[dict[str, Any]]) -> None:
        """`腳本` 用完了就一直重複最後一份。"""
        self.腳本 = 腳本
        self.收到: list[dict[str, Any]] = []
        self._伺服器: HTTPServer | None = None

    def __enter__(self) -> str:
        """起一個只聽 localhost 的 HTTP server，回它的網址。"""
        外層 = self

        class 處理器(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
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
    """做一份回文字的 OpenAI completion response。"""
    return {
        "choices": [{"message": {"role": "assistant", "content": 文字}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 入, "completion_tokens": 出},
    }


def 回工具(名稱: str, 參數: dict[str, str], *, 入: int = 10, 出: int = 5) -> dict[str, Any]:
    """做一份回 tool_calls 的 OpenAI completion response。"""
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


def 建() -> tuple[io.StringIO, 帳本]:
    """建一本寫到 StringIO 的帳本。"""
    串流 = io.StringIO()
    return 串流, 建帳本(串流, 執行識別碼="r1", 現在=lambda: "2026-08-31T00:00:00Z")


def 讀事件(串流: io.StringIO) -> list[dict[str, Any]]:
    """把 StringIO 裡的每行 jsonl 讀成 dict。"""
    return [json.loads(行) for 行 in 串流.getvalue().splitlines()]


@pytest.fixture
def 工作區(tmp_path: Path) -> Iterator[Path]:
    """提供有測試檔案的工作區目錄。"""
    (tmp_path / "檔1.txt").write_text("第一份內容", encoding="utf-8")
    (tmp_path / "檔2.txt").write_text("第二份內容包含答案", encoding="utf-8")
    yield tmp_path


class Test本地工具呼叫進帳本:
    """本地腦執行工具時，每筆呼叫都要記進帳本留下證據。"""

    def test_工具迴圈跑完帳本有對應數量的工具呼叫事件(self, 工作區: Path) -> None:
        """跑完一輪工具迴圈之後，帳本裡有對應數量的 tool_call 事件。"""
        腳本 = [
            回工具("read_file", {"path": "檔1.txt"}),
            回工具("read_file", {"path": "檔2.txt"}),
            回文字("兩份檔案都讀完了"),
        ]
        端 = 假端點(腳本)
        串流, 帳 = 建()
        with 端 as 網址:
            腦 = 本地腦(網址=網址, 記=帳.記一筆)
            答 = 腦.詢問(
                "讀這兩個檔案",
                選項=呼叫選項(模型="假模型", 權限=權限.唯讀, 工作目錄=工作區, 逾時秒=10),
            )
        assert 答.終局 is 終局.成功
        assert 答.文字 == "兩份檔案都讀完了"

        事件們 = 讀事件(串流)
        工具事件們 = [事 for 事 in 事件們 if 事.get("event") == 事件種類.工具呼叫.value]
        assert len(工具事件們) == 2

    def test_每一筆工具呼叫帶有名稱與回合數(self, 工作區: Path) -> None:
        """每一筆 tool_call 帶得出工具名稱、第幾回合以及成功狀態。"""
        腳本 = [
            回工具("read_file", {"path": "檔1.txt"}),
            回工具("grep", {"pattern": "答案"}),
            回文字("搜尋完畢"),
        ]
        端 = 假端點(腳本)
        串流, 帳 = 建()
        with 端 as 網址:
            腦 = 本地腦(網址=網址, 記=帳.記一筆)
            答 = 腦.詢問(
                "查資料",
                選項=呼叫選項(模型="假模型", 權限=權限.唯讀, 工作目錄=工作區, 逾時秒=10),
            )
        assert 答.終局 is 終局.成功

        事件們 = 讀事件(串流)
        工具事件們 = [事 for 事 in 事件們 if 事.get("event") == 事件種類.工具呼叫.value]
        assert len(工具事件們) == 2

        assert 工具事件們[0]["tool_name"] == "read_file"
        assert 工具事件們[0]["tool_round"] == 1
        assert 工具事件們[0]["tool_ok"] is True

        assert 工具事件們[1]["tool_name"] == "grep"
        assert 工具事件們[1]["tool_round"] == 2
        assert 工具事件們[1]["tool_ok"] is True

    def test_工具出錯時記錄失敗且那一輪仍然成功收尾(self, 工作區: Path) -> None:
        """工具失敗（例如讀不存在的檔案）時 tool_ok 是 false，而且那一輪仍然成功收尾。"""
        腳本 = [
            回工具("read_file", {"path": "不存在的檔案.txt"}),
            回文字("檔案不存在，已處理完畢"),
        ]
        端 = 假端點(腳本)
        串流, 帳 = 建()
        with 端 as 網址:
            腦 = 本地腦(網址=網址, 記=帳.記一筆)
            答 = 腦.詢問(
                "讀檔案",
                選項=呼叫選項(模型="假模型", 權限=權限.唯讀, 工作目錄=工作區, 逾時秒=10),
            )
        assert 答.終局 is 終局.成功
        assert 答.文字 == "檔案不存在，已處理完畢"

        事件們 = 讀事件(串流)
        工具事件們 = [事 for 事 in 事件們 if 事.get("event") == 事件種類.工具呼叫.value]
        assert len(工具事件們) == 1
        assert 工具事件們[0]["tool_name"] == "read_file"
        assert 工具事件們[0]["tool_round"] == 1
        assert 工具事件們[0]["tool_ok"] is False

    def test_與記帳腦一起包裝時事件順序正確(self, 工作區: Path) -> None:
        """記帳腦包住本地腦時，工具呼叫事件夾在呼叫開始與呼叫結束之間。"""
        腳本 = [
            回工具("read_file", {"path": "檔1.txt"}),
            回文字("讀完了"),
        ]
        端 = 假端點(腳本)
        串流, 帳 = 建()
        with 端 as 網址:
            內層腦 = 本地腦(網址=網址, 記=帳.記一筆)
            外層腦 = 記帳腦(內層=內層腦, 帳=帳)
            答 = 外層腦.詢問(
                "讀檔案",
                選項=呼叫選項(模型="假模型", 權限=權限.唯讀, 工作目錄=工作區, 逾時秒=10),
            )
        assert 答.終局 is 終局.成功
        事件順序 = [事.get("event") for 事 in 讀事件(串流)]
        assert 事件順序 == [
            事件種類.呼叫開始.value,
            事件種類.工具呼叫.value,
            事件種類.呼叫結束.value,
        ]
