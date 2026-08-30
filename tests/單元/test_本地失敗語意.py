"""本地 HTTP 轉接層的失敗語意。

這裡只替身 `urlopen` 丟出的例外，不開 socket；真正碰本機推論伺服器的測試住
`tests/整合/`，而且掛在昂貴外部資源標記下。
"""

import urllib.error
import urllib.request
from collections.abc import Callable
from http.client import HTTPMessage
from typing import NoReturn

import pytest

from nova.契約.模型回應 import 失敗代碼, 終局
from nova.載體.模型.本地 import 本地腦

_只作佔位不會連線的網址 = "http://127.0.0.1:1/v1"


def _固定丟出(例外: BaseException) -> Callable[..., NoReturn]:
    """做一個永遠丟同一種錯的 `urlopen`，讓測試不需要真的連線。"""

    def 丟出(*參數: object, **關鍵字: object) -> NoReturn:
        del 參數, 關鍵字
        raise 例外

    return 丟出


def test_URLError連不上歸類為未安裝(monkeypatch: pytest.MonkeyPatch) -> None:
    """伺服器沒開是確定沒送出請求，接力可以安全換下一家。"""
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        _固定丟出(urllib.error.URLError("Connection refused")),
    )

    答 = 本地腦(網址=_只作佔位不會連線的網址).詢問("在嗎")

    assert 答.失敗代碼 is 失敗代碼.未安裝
    assert 答.終局 is 終局.確定失敗
    assert "連不上" in 答.文字


def test_逾時落在結果未知(monkeypatch: pytest.MonkeyPatch) -> None:
    """請求可能已經出門，腳本不准把這次當成安全失敗再跑一次。"""
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        _固定丟出(TimeoutError("假逾時")),
    )

    答 = 本地腦(網址=_只作佔位不會連線的網址).詢問("在嗎")

    assert 答.失敗代碼 is 失敗代碼.逾時
    assert 答.終局 is 終局.結果未知


def test_被URLError包住的逾時仍落在結果未知(monkeypatch: pytest.MonkeyPatch) -> None:
    """網路層可能把 socket 逾時包成 `URLError`，語意不能因此變成未安裝。"""
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        _固定丟出(urllib.error.URLError(TimeoutError("假逾時"))),
    )

    答 = 本地腦(網址=_只作佔位不會連線的網址).詢問("在嗎")

    assert 答.失敗代碼 is 失敗代碼.逾時
    assert 答.終局 is 終局.結果未知


@pytest.mark.parametrize("狀態碼", [404, 503], ids=["四百系", "五百系"])
def test_HTTP錯誤歸類為上游(狀態碼: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """已收到上游的 HTTP 錯誤，不可誤報成「本地伺服器沒裝」。"""
    錯誤 = urllib.error.HTTPError(
        f"{_只作佔位不會連線的網址}/models",
        狀態碼,
        "假 HTTP 錯誤",
        HTTPMessage(),
        None,
    )
    monkeypatch.setattr(urllib.request, "urlopen", _固定丟出(錯誤))

    答 = 本地腦(網址=_只作佔位不會連線的網址).詢問("在嗎")

    assert 答.失敗代碼 is 失敗代碼.上游
    assert 答.終局 is 終局.確定失敗
    assert 答.原始結束碼 == 狀態碼
