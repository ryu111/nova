"""儀表板資料層對 `ps etime` 的解碼邊界。"""

from nova.載體.儀表板.資料 import _幾秒


def test_帶天數的跑多久缺少小時欄應查不到() -> None:
    """`[[dd-]hh:]mm:ss` 有天數時，天數後仍必須帶小時。"""
    assert _幾秒("1-02:03") is None
