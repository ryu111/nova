"""派工門面的資格防護。

門面過去沒有本地腦審查資格的測試；拿掉接線時，既有命令列測試仍會綠，
所以這裡直接守公開門面。整合測試的自己審自己是另一條交集規則。
"""

import pytest

import nova


def test_門面不准本地腦當審查員(monkeypatch: pytest.MonkeyPatch) -> None:
    """直接走公開門面時，本地腦也不能混進審查鏈。

    絆線是為了讓失敗訊息指出已經走過頭，不是為了擋 CLI。
    """
    monkeypatch.setattr(nova, "_建腦", lambda *_: pytest.fail("門面護欄沒擋住，已經走到建腦"))
    with pytest.raises(ValueError, match=r"local.*審查員"):
        nova.派工(
            "做點事",
            用="codex",
            審查用="local",
        )
