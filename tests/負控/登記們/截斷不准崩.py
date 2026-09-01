"""守「端點中途斷線要收成結果未知，不准往外拋」那兩把刀。

漏接一種例外的下場**不是失敗，是蒸發**：整個工作流程序當場死掉，
沒有退出碼語意、沒有帳本、沒有現場，`nova 線` 只看得到
「上一次怎麼收的：查不到」。實測 2026-09-01 22:35 就這樣掉了一條線。
"""

from pathlib import Path

from tests.負控.登記 import 替換一次, 變異

登記 = (
    #: 把 HTTPException 從清單裡拿掉＝IncompleteRead 又會往外拋，線又會蒸發。
    變異(
        識別="問得到的錯不再包含http層例外",
        目標檔=Path("src/nova/載體/模型/本地.py"),
        操作=替換一次("    http.client.HTTPException,\n", ""),
        該紅=(
            (
                "tests/單元/test_截斷回應不准崩.py::Test端點中途斷線"
                "::test_不准往外拋[\\u622a\\u65b7\\u7684chunked\\u56de\\u61c9]"
            ),
        ),
        最多秒=60.0,
    ),
    #: 把「出門了沒」倒過來＝中途斷線被當成沒出門，接力會放心換下一顆，
    #: 而那是把工具迴圈可能已經做過的檔案改動再做一次。
    變異(
        識別="出門了沒的判斷倒過來",
        目標檔=Path("src/nova/載體/模型/本地.py"),
        操作=替換一次(
            "    return not isinstance(錯誤, urllib.error.URLError)",
            "    return isinstance(錯誤, urllib.error.URLError)",
        ),
        該紅=(
            (
                "tests/單元/test_截斷回應不准崩.py::Test端點中途斷線"
                "::test_不准往外拋[\\u622a\\u65b7\\u7684chunked\\u56de\\u61c9]"
            ),
            "tests/單元/test_本地失敗語意.py::test_URLError連不上歸類為未安裝",
        ),
        最多秒=60.0,
    ),
)
