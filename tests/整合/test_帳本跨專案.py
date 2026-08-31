"""跨專案讀帳本：一次並行跑六條線，證據不准散在六個地方。

碰檔案，所以住整合層。

`預設帳本目錄` 把帳本按專案分（`$XDG_STATE_HOME/nova/專案/<識別>/帳本`），
那個分層是對的——歸屬是索引問題。但**每個 git worktree 都被算成不同專案**，
於是六條線並行跑完，六份證據互相看不見，而
`docs/設計/09-接下來往哪走.md` 第 4 階「從帳本推真依賴」要的正是這些資料。

這個檔背書的是 `跨專案列出執行` 與 `跨專案盤點`：把所有專案的帳本
（**加上分層之前的舊全域位置**）合成一條時間軸。
"""

import json
import re
from pathlib import Path

import pytest

from nova.載體.帳本讀取 import 全域帳本識別, 跨專案列出執行, 跨專案盤點

一次成功 = [
    {"run": "r1", "seq": 1, "ts": "t1", "event": "call_started", "call": 1, "family": "agy"},
    {
        "run": "r1",
        "seq": 2,
        "ts": "t2",
        "event": "call_finished",
        "call": 1,
        "family": "agy",
        "outcome": "success",
        "input_tokens": 12,
        "output_tokens": 3,
    },
]


def 寫一份(目錄: Path, 識別: str) -> Path:
    """在指定目錄放一本看得懂的帳。"""
    目錄.mkdir(parents=True, exist_ok=True)
    檔 = 目錄 / f"{識別}.jsonl"
    檔.write_text(
        "".join(json.dumps(事, ensure_ascii=False) + "\n" for 事 in 一次成功), encoding="utf-8"
    )
    return 檔


def 專案帳本目錄(狀態根: Path, 專案識別: str) -> Path:
    """`預設帳本目錄(專案)` 的落點形狀，測試這邊自己拼一次。"""
    return 狀態根 / "專案" / 專案識別 / "帳本"


def test_跨專案是時間序不是專案序(tmp_path: Path) -> None:
    """三條線交錯跑，排出來就要交錯——**那正是要回答的問題**。

    按專案分組再串起來也能「列出全部」，但看不出「那個時候同時在跑什麼」，
    而並行六條線之後唯一想知道的就是這件事。所以順序是硬性行為，不是呈現偏好。
    """
    寫一份(專案帳本目錄(tmp_path, "nova-wt-四欄-52dabea7"), "20260831T090000Z-甲")
    寫一份(專案帳本目錄(tmp_path, "nova-wt-假獨立-88c9d86e"), "20260831T090100Z-乙")
    寫一份(專案帳本目錄(tmp_path, "nova-wt-四欄-52dabea7"), "20260831T090200Z-丙")
    寫一份(專案帳本目錄(tmp_path, "nova-wt-路線-13ac9f02"), "20260831T090300Z-丁")

    assert [(識別, 檔.stem) for 識別, 檔 in 跨專案列出執行(tmp_path)] == [
        ("nova-wt-路線-13ac9f02", "20260831T090300Z-丁"),
        ("nova-wt-四欄-52dabea7", "20260831T090200Z-丙"),
        ("nova-wt-假獨立-88c9d86e", "20260831T090100Z-乙"),
        ("nova-wt-四欄-52dabea7", "20260831T090000Z-甲"),
    ]


def test_分層之前的舊全域帳本也收得進來(tmp_path: Path) -> None:
    """`$XDG_STATE_HOME/nova/帳本` 底下那 134 個檔不准漏。

    漏掉的話「以前的資料沒被索引」會長得跟「以前沒發生過」一模一樣，
    而那是最貴的一種說謊。舊的那批沒有專案可歸，所以掛在 `全域帳本識別` 底下——
    **標成某個專案的更糟**：那是憑空捏造歸屬。
    """
    寫一份(tmp_path / "帳本", "20260731T120000Z-舊的")
    寫一份(專案帳本目錄(tmp_path, "nova-wt-路線-13ac9f02"), "20260831T090300Z-新的")

    assert [(識別, 檔.stem) for 識別, 檔 in 跨專案列出執行(tmp_path)] == [
        ("nova-wt-路線-13ac9f02", "20260831T090300Z-新的"),
        (全域帳本識別, "20260731T120000Z-舊的"),
    ]


def test_全域帳本識別不會跟真專案撞名() -> None:
    """舊全域那批的標籤要一眼看得出「不是專案」。

    `帳本.專案識別()` 產的一律是 `<名字>-<8 位十六進位雜湊>`，所以標籤只要
    不長那個樣子就撞不到——撞到的話「舊的那批」會被算進某個真專案的帳裡。
    同時它不准是空字串：空的印出來像漏填，不像「沒有專案」。
    """
    assert 全域帳本識別
    assert re.fullmatch(r".+-[0-9a-f]{8}", 全域帳本識別) is None


def test_專案目錄不存在就是空list(tmp_path: Path) -> None:
    """**「還沒有帳」不是錯誤。**

    全新的機器上 `$XDG_STATE_HOME/nova/` 根本不存在，這條路是給
    「看看跑過什麼」用的，炸掉會讓第一次用的人以為裝壞了。
    """
    assert 跨專案列出執行(tmp_path / "根本沒這個目錄") == []
    assert 跨專案列出執行(tmp_path) == []


def test_壞掉的帳本檔跳過但數得出跳過幾個(tmp_path: Path) -> None:
    """跟 `摘要.壞掉的行` 同一條：**證據不完整不准長得像事情沒發生**。

    一個讀不動的檔不能讓整份列表消失（那是拿全部去賠一個），
    但也不能默默吞掉——數得出來，人才知道自己看到的是不是全部。
    """
    好的 = 寫一份(專案帳本目錄(tmp_path, "nova-wt-路線-13ac9f02"), "20260831T090300Z-好的")
    壞的目錄 = 專案帳本目錄(tmp_path, "nova-wt-四欄-52dabea7")
    壞的目錄.mkdir(parents=True, exist_ok=True)
    (壞的目錄 / "20260831T090400Z-壞的.jsonl").symlink_to(tmp_path / "指到不存在的地方")

    盤 = 跨專案盤點(tmp_path)
    assert [(識別, 檔) for 識別, 檔 in 盤.執行們] == [("nova-wt-路線-13ac9f02", 好的)]
    assert 盤.跳過的檔 == 1
    assert 跨專案列出執行(tmp_path) == [("nova-wt-路線-13ac9f02", 好的)]


@pytest.mark.parametrize("雜物", ["筆記.txt", "帳本.jsonl.tmp"])
def test_不是jsonl的東西不算執行也不算跳過(tmp_path: Path, 雜物: str) -> None:
    """只有 `*.jsonl` 是帳本。

    **把雜物算成「跳過」等於謊報證據有缺口**——那會讓人去找一份根本不存在的帳。
    """
    目錄 = 專案帳本目錄(tmp_path, "nova-wt-路線-13ac9f02")
    目錄.mkdir(parents=True, exist_ok=True)
    (目錄 / 雜物).write_text("不是帳本", encoding="utf-8")

    盤 = 跨專案盤點(tmp_path)
    assert 盤.執行們 == ()
    assert 盤.跳過的檔 == 0
