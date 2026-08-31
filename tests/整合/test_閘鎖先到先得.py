"""排隊要有順序：**等最久的先拿到**。

## 這一支守什麼

`閘鎖._等到拿得到` 是非阻塞加固定間隔輪詢。鎖一放開，正在 `sleep` 的那幾條
誰先醒誰先拿——**醒的時機由各自的 sleep 相位決定，跟等了多久完全無關**。
於是等了 1:32:01 的可以一輪又一輪輸給等了 38:29 的，而沒有任何機制阻止它。

這裡守的是行為：三條依序進入排隊，持有者放手之後，**取得順序等於進場順序**。

## 為什麼進場順序是用事件排的、不是用 sleep 排的

每個等待者在呼叫 `佔住` 之前先落一個「到場」檔，父程序**等到那個檔出現**
才生下一個等待者。所以進場順序由事件決定，不是由「睡 0.5 秒應該夠了」決定——
後者在忙的機器上會變 flaky，而 flaky 的護欄測試遲早被人加 `skip`。

## 為什麼要跑三輪

現行實作正是**相位決定勝負**，單輪有三分之一的機率碰巧照順序出來，
那種綠證明不了任何事。三輪都要全對，碰巧的機率是 (1/6)^3。
等到排隊真的有順序之後，這三輪一律綠，不多不少。

住整合層是因為它真的 fork 子程序才測得出「跨程序排隊」。
"""

import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from nova.載體.閘鎖 import 佔住

#: 三個等待者的名字，**同時也是期望的取得順序**。
_等待者們 = ("甲", "乙", "丙")

#: 每個等待者進場前先睡多久。**刻意錯開輪詢相位**：三條的 `sleep` 節拍不一致，
#: 現行實作的勝負就由這個相位決定，測試不錯開的話有可能碰巧綠。
#: 這幾個數字都小於一個輪詢間隔，只用來打散節拍，不用來控制勝負。
_進場前先睡幾秒 = {"甲": 0.0, "乙": 0.07, "丙": 0.13}

#: 等一個事件（檔案出現、子程序結束）最多等多久才判定測試自己壞了。
#: **這不是被測行為的一部分**，只是不讓測試整台掛住的安全網。
_事件上限秒 = 60.0


def _等待者腳本(鎖目錄: Path, 到場檔: Path, 順序檔: Path, 名字: str) -> str:
    """一個等待者：報到 → 排隊 → 拿到鎖就把自己的名字寫進順序檔。

    順序檔的寫入本身被鎖圈住，所以它記的就是**取得鎖的先後**。
    """
    return textwrap.dedent(f"""
        import time
        from pathlib import Path
        from nova.載體.閘鎖 import 佔住

        time.sleep({_進場前先睡幾秒[名字]})
        Path({str(到場檔)!r}).write_text({名字!r}, encoding="utf-8")
        with 佔住("閘", 最多等幾秒=45, 鎖目錄=Path({str(鎖目錄)!r})):
            with Path({str(順序檔)!r}).open("a", encoding="utf-8") as 檔:
                檔.write({名字!r} + "\\n")
    """)


def _等到出現(檔: Path) -> None:
    截止 = time.monotonic() + _事件上限秒
    while not 檔.exists():
        if time.monotonic() > 截止:
            pytest.fail(f"等不到 {檔.name} 出現——等待者沒生出來，測試自己壞了")
        time.sleep(0.01)


def _跑一輪(工作目錄: Path) -> list[str]:
    """持有者佔著鎖，三條依序進場，放手之後回傳實際的取得順序。"""
    鎖目錄 = 工作目錄 / "鎖"
    順序檔 = 工作目錄 / "取得順序.txt"
    程序們: list[subprocess.Popen[str]] = []
    with 佔住("閘", 鎖目錄=鎖目錄):
        for 名字 in _等待者們:
            到場檔 = 工作目錄 / f"到場-{名字}"
            程序們.append(
                subprocess.Popen(  # noqa: S603
                    [sys.executable, "-c", _等待者腳本(鎖目錄, 到場檔, 順序檔, 名字)],
                    text=True,
                )
            )
            # **事件式的接力**：確定這一條已經進場，才放下一條進來。
            _等到出現(到場檔)
    for 程序 in 程序們:
        assert 程序.wait(timeout=_事件上限秒) == 0, "等待者沒拿到鎖就死了"
    return 順序檔.read_text(encoding="utf-8").split()


@pytest.mark.serial
@pytest.mark.parametrize("輪", [1, 2, 3])
def test_先進排隊的先拿到鎖(tmp_path: Path, 輪: int) -> None:
    """**這一支是「不會餓死」的形狀**：進場順序決定取得順序。

    現在會紅，因為輪詢誰先醒誰先拿——第一個進來的沒有任何優先權。
    """
    實際 = _跑一輪(tmp_path / f"第{輪}輪")
    assert 實際 == list(_等待者們), f"排隊亂序：進場是 {list(_等待者們)}，拿到是 {實際}"
