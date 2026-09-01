"""`nova.載體.線` composition adapter 的單元測試。

驗證 `線.py` 作為組合適配層（composition adapter）：
1. 整合程序觀測與工作樹觀測以產出 `線現況` 快照。
2. 委派排版呈現給呈現層。
3. 導出相容介面 `線資料`、`線現況`、`查並行現況`、`排版`、`執行線`。
"""

import argparse
from pathlib import Path
from unittest.mock import patch

from nova.契約.線觀測 import 線現況
from nova.載體.線 import 執行線, 線資料


def test_線資料為線現況之別名() -> None:
    """舊名 `線資料` 必須是 `線現況` 的別名以維持相容性。"""
    assert 線資料 is 線現況


def test_執行線會將排版結果輸出並回傳零() -> None:
    """`執行線` 讀取參數中的根目錄、查詢並行現況、排版後印出，並回傳 0。"""
    假現況 = 線現況(
        名字="主工作區",
        在跑嗎=False,
        跑多久=None,
        啟動時間=None,
        目前階段=None,
        上一次=None,
        護欄原因=None,
        未提交檔案數=0,
        基底落後數=0,
    )
    with (
        patch("nova.載體.線.查並行現況", return_value=(假現況,)) as 模擬查,
        patch("nova.載體.線.排版", return_value="排版結果\n") as 模擬排版,
        patch("sys.stdout.write") as 模擬輸出,
    ):
        參數 = argparse.Namespace(根目錄="/fake/dir")
        碼 = 執行線(參數)

        assert 碼 == 0
        模擬查.assert_called_once_with(Path("/fake/dir"))
        模擬排版.assert_called_once_with((假現況,))
        模擬輸出.assert_called_once_with("排版結果\n")
