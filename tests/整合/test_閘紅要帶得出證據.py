"""閘紅落成收件票的時候，證據要帶得出 pytest 的 FAILURES 段。

票裡那段「紅在哪」是下一輪的模型唯一看得到的現場。pytest 在 `-q` 之下，
**失敗細節（FAILURES 段、assert 的實際值、traceback）與最後那行摘要
分屬不同區塊**——只帶到「3 failed」的話，讀票的人不知道為什麼失敗，
只能猜；猜出來的修法會讓同一個閘再紅一次。

所以這一檔驗的是「證據夠不夠」，不是「有沒有東西」：

1. 沒有上限時，證據要含 FAILURES 段與 assert 的實際值（先量再改的那一格）。
2. 有上限時，**截斷要從尾巴截**——保留開頭的失敗細節，丟掉最沒資訊的摘要，
   而且要在證據裡明講截了（截斷註記），不准靜默截斷。
3. 呼叫端不給上限時，預設上限也要生效——真正走進票裡的是 `建規則表` 那條路，
   它一個上限參數都不會傳。

這裡真的 fork 一個小 pytest（在 `tmp_path` 裡），走 `_外部指令` 那條路：
**證據長什麼樣是程序邊界的事**，用字串墊片問不出來（見 `docs/設計/05`）。
"""

import re
import sys
from pathlib import Path

import pytest

from nova.載體 import 規則表

_pytest執行檔 = Path(sys.executable).parent / "pytest"

#: 一支會紅的小測試。`test_數字對不上` 帶的是我們要在證據裡找到的實際值；
#: `test_長長的失敗` 純粹是填充，把摘要區塊推遠一點，
#: 免得「保留開頭」這件事只差幾個字元就量不準。
_會紅的小測試 = """\
def test_數字對不上():
    預期 = 42
    實際 = 41
    assert 實際 == 預期


def test_長長的失敗():
    累計 = 0
    累計 += 1
    累計 += 2
    累計 += 3
    累計 += 4
    累計 += 5
    累計 += 6
    累計 += 7
    累計 += 8
    累計 += 9
    assert 累計 == 0
"""


def _擺好會紅的小測試(工地: Path) -> None:
    (工地 / "小測試.py").write_text(_會紅的小測試, encoding="utf-8")


#: 巢狀跑 pytest 會跟外層搶檔案系統與 CPU，照 `pyproject.toml` 的規矩標 serial。
#: `-p no:randomly` 是為了讓失敗的先後固定：量「保留的是開頭」時，順序不能是隨機的。
_小測試參數 = ("pytest", "小測試.py", "-q", "-p", "no:randomly")


@pytest.mark.serial
@pytest.mark.skipif(not _pytest執行檔.exists(), reason="這個 venv 裡沒有 pytest")
def test_閘紅的證據帶得出FAILURES段與assert的實際值(tmp_path: Path) -> None:
    """先量再改：沒有上限時，證據本來就該含失敗細節，不是只有摘要。"""
    _擺好會紅的小測試(tmp_path)

    綠, 證據 = 規則表._外部指令(tmp_path, *_小測試參數)()

    assert not 綠, f"這個工地本來就該紅：{證據}"
    assert "FAILURES" in 證據, f"證據裡沒有 FAILURES 段，讀票的人只看得到摘要：{證據}"
    assert "test_數字對不上" in 證據, f"證據沒說是哪一支紅：{證據}"
    assert "assert 41 == 42" in 證據, f"證據沒帶 assert 的實際值，讀票的人只能猜：{證據}"


@pytest.mark.serial
@pytest.mark.skipif(not _pytest執行檔.exists(), reason="這個 venv 裡沒有 pytest")
def test_證據截斷要保留開頭的失敗細節並且誠實標註(tmp_path: Path) -> None:
    """上限砍下去的時候，**砍的是尾巴的摘要，不是開頭的失敗細節**。

    摘要（`short test summary info` 與 `N failed in ...`）是整份輸出裡
    資訊量最低的一段：它只說了幾支紅，沒說為什麼紅。保留尾巴等於把證據砍成
    「3 failed」——那正是這一格要擋掉的事。
    """
    _擺好會紅的小測試(tmp_path)
    _, 全文 = 規則表._外部指令(tmp_path, *_小測試參數)()
    # 上限就切在摘要區塊的開頭：剛好把摘要擋在門外，失敗細節一個字都不必犧牲。
    上限 = 全文.index("short test summary info")

    綠, 證據 = 規則表._外部指令(tmp_path, *_小測試參數, 證據上限=上限)()

    assert not 綠, f"這個工地本來就該紅：{證據}"
    assert len(證據) <= 上限, f"上限是硬上限，誠實欄位也要算在裡面：{len(證據)} > {上限}"
    assert "FAILURES" in 證據, f"截斷把 FAILURES 段吃掉了：{證據}"
    assert "assert 41 == 42" in 證據, f"截斷把 assert 的實際值吃掉了：{證據}"
    assert "截斷" in 證據, f"靜默截斷等於騙人，證據裡要明講截了：{證據}"
    assert re.search(r"截斷[^\n]*\d{3,}", 證據), f"誠實欄位要說出原本有多長：{證據}"
    assert "failed in" not in 證據, f"留下來的是尾巴的摘要，不是開頭的失敗細節：{證據}"


@pytest.mark.serial
@pytest.mark.skipif(not _pytest執行檔.exists(), reason="這個 venv 裡沒有 pytest")
def test_沒人給上限時預設上限也要生效(tmp_path: Path) -> None:
    """`建規則表` 一個上限參數都不會傳，所以上限必須是預設就在的。

    沒有預設上限的話，一份幾萬行的 pytest 輸出會整包被塞進收件票裡。
    """
    上限 = 規則表.預設證據上限
    assert 上限 <= 40_000, f"預設上限太寬，票會被幾萬行灌爆：{上限}"

    很多支 = "\n\n".join(
        f"def test_第{序號:03d}格():\n    assert {序號} == -1\n" for 序號 in range(240)
    )
    (tmp_path / "小測試.py").write_text(很多支, encoding="utf-8")

    綠, 證據 = 規則表._外部指令(tmp_path, *_小測試參數)()

    assert not 綠, f"這個工地本來就該紅：{證據}"
    assert len(證據) <= 上限, f"沒人給上限時預設上限沒生效：{len(證據)} > {上限}"
    assert "FAILURES" in 證據, f"證據裡沒有 FAILURES 段：{證據[:2000]}"
    assert "assert 0 == -1" in 證據, f"開頭那支的失敗細節被截掉了：{證據[:2000]}"
    assert "截斷" in 證據, f"靜默截斷等於騙人，證據裡要明講截了：{證據[:2000]}"
