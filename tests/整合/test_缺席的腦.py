"""鏈上少裝一家，不該讓整串垮掉。

原本 `_建腦` 一次把每一家都 `建立()` 出來，而 `建立()` 當場 `找執行檔()`——
少裝一家就 `FileNotFoundError`，**連裝好的那家都不會被叫到**。
接力鏈存在的理由就是「這顆不行換下一顆」，卻在建構期先自己垮了。

分界線：

| 情況 | 行為 | 理由 |
|---|---|---|
| 只指定一家、沒裝 | **當場炸** | 那是明確的設定錯誤，早點講比較好 |
| 一串裡少一家 | 那一顆算**確定失敗**，換下一顆 | 這正是接力要做的事 |
"""

from collections.abc import Callable
from pathlib import Path

import pytest

import nova
from nova.契約.模型回應 import 失敗代碼, 終局, 終局判定
from nova.載體.命令列 import 主程式

做假CLI型 = Callable[..., tuple[Path, Path]]


def test_一串裡少一家還是跑得起來(做假CLI: 做假CLI型) -> None:
    """codex 沒裝、agy 裝了 → 走 agy，而不是整串垮掉。"""
    好的, _ = 做假CLI("agy")
    # codex 不給執行檔 → 走 `找執行檔`，而 conftest 的 `不准摸到真的CLI`
    # 會讓它 FileNotFoundError。這正是「沒裝」在建構期的樣子。
    答 = nova.問("在嗎", 用="codex,agy", 執行檔={"agy": 好的})
    assert 答.終局 is 終局.成功
    assert 答.文字 == "ok\n"


def test_缺席的那顆要留下痕跡() -> None:
    """全掛的時候要看得出「是沒裝」而不是「跑了但失敗」。"""
    答 = nova.問("在嗎", 用="codex,agy")
    assert 答.終局 is 終局.確定失敗
    assert 失敗代碼.未安裝.value in 答.文字


def test_只指定一家沒裝要當場炸() -> None:
    """設定錯誤要早點講。降級成「確定失敗」會讓人以為問過了。"""
    with pytest.raises(FileNotFoundError):
        nova.問("在嗎", 用="codex")


def test_未安裝是確定失敗不是結果未知() -> None:
    """請求根本沒出門，沒有副作用——所以可以換下一顆。

    判成結果未知的話，可編輯模式下接力當場停，那就白白浪費了裝好的那幾家。
    """
    assert 終局判定(失敗代碼.未安裝) is 終局.確定失敗


def test_CLI也一樣(做假CLI: 做假CLI型, capsys: pytest.CaptureFixture[str]) -> None:
    """門面修好但 CLI 沒修的話，使用者實際走的那條路還是壞的。"""
    做假CLI("agy")
    # CLI 的 `--執行檔` 是整串共用一條路徑，所以這裡不給——兩家都走 `找執行檔`、
    # 兩家都缺席。重點是**不炸、走完接力、給出確定失敗**。
    碼 = 主程式(["問", "--用", "codex,agy", "--不記帳", "在嗎"])
    出 = capsys.readouterr()
    assert 碼 == 1, 出.err
    assert 失敗代碼.未安裝.value in 出.out
