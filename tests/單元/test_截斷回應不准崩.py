"""端點中途把連線砍掉時，本地腦要回「結果未知」，不是讓整條線崩掉。

實測 2026-09-01 22:35：oMLX 撞到記憶體 hard line（50.1 GB > hard 49.2 GB），
把一個進行中的請求砍掉，回了一個截斷的 chunked response。
`http.client.IncompleteRead` **不是 `OSError`**（它是 `HTTPException`），
所以 `詢問()` 那幾個 except 一個都接不到——**整個工作流程序當場死掉**：
沒有退出碼語意、沒有帳本、沒有現場，`nova 線` 只看得到「上一次怎麼收的：查不到」。

為什麼是**結果未知**而不是確定失敗：請求已經出門了，而本地腦的工具迴圈
**會真的改檔案**。回確定失敗會讓接力放心換下一顆，那就是把可能做過的
副作用再做一次。
"""

import http.client

import pytest

from nova.契約.模型回應 import 失敗代碼, 終局
from nova.契約.角色 import 呼叫選項
from nova.載體.模型 import 本地


class Test端點中途斷線:
    @pytest.mark.parametrize(
        "錯",
        [
            pytest.param(http.client.IncompleteRead(b"7 bytes"), id="截斷的chunked回應"),
            pytest.param(http.client.RemoteDisconnected("端點自己關了"), id="端點直接斷線"),
            pytest.param(http.client.HTTPException("其他 http 層的錯"), id="其他http層例外"),
        ],
    )
    def test_不准往外拋(self, 錯: Exception, monkeypatch: pytest.MonkeyPatch) -> None:
        """往外拋就是整條線崩掉——那比任何一種失敗都貴。"""

        def 爆(*位置: object, **具名: object) -> dict[str, object]:
            del 位置, 具名
            raise 錯

        腦 = 本地.本地腦(網址="http://127.0.0.1:9/v1")
        monkeypatch.setattr(本地.本地腦, "_第一個型號", lambda *_: "假型號")
        monkeypatch.setattr(本地.本地腦, "_發出請求", 爆)

        答 = 腦.詢問("做點事", 選項=呼叫選項(工作目錄=None))

        assert 答.終局 is 終局.結果未知, "斷線可能已經改過檔案，當成確定失敗會讓接力重做副作用"
        assert 答.失敗代碼 is 失敗代碼.上游
        assert "http" in 答.文字.lower() or "斷" in 答.文字 or "截斷" in 答.文字, 答.文字
