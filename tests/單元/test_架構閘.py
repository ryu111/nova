"""三層落點閘的純判定：把違規的原始碼餵進去，它要指名得出誰越界。

**不測「現在的 repo 是綠的」**——那種測試在違規出現的那天才第一次有用，
而那天沒有人知道它這段期間到底有沒有在看。這裡直接餵一段越界的原始碼，
斷言閘紅、而且訊息說得出哪個檔、哪一行、違反哪一條。
"""

from pathlib import Path

from nova.載體.架構閘 import 判定架構落點
from nova.載體.規則表 import 建規則表

_越界的迴圈模組 = (
    "from nova.契約.角色 import 角色\nfrom nova.載體.工作區 import 判定工作區, 拍工作區快照\n"
)


def test_迴圈import載體時指名檔案行號與違反的那條() -> None:
    綠, 訊息 = 判定架構落點({"src/nova/迴圈/工作流.py": _越界的迴圈模組})

    assert 綠 is False
    # 哪個檔、哪一行：載體那行是第 2 行。
    assert "src/nova/迴圈/工作流.py:2" in 訊息
    # 違反哪一條，以及越界到哪個模組。
    assert "nova.載體.工作區" in 訊息
    assert "迴圈不准 import 載體" in 訊息
    # 同一個檔裡合法的那行不准被算進去：往下看的是層級，不是「有 import nova」。
    assert "nova.契約.角色" not in 訊息


_型別檢查底下的越界 = (
    "from typing import TYPE_CHECKING\n"
    "\n"
    "if TYPE_CHECKING:\n"
    "    from nova.載體.額度 import 額度來源\n"
)
_執行期的同一份越界 = "from nova.載體.額度 import 額度來源\n"


def test_型別檢查底下的import放行但搬到執行期就紅() -> None:
    """放行 `if TYPE_CHECKING:`（理由見閘的 docstring），搬出去的那一刻要紅。

    兩個斷言綁在一起：只測放行的話，閘退化成「都放行」也會綠。
    """
    綠, _ = 判定架構落點({"src/nova/契約/額度.py": _型別檢查底下的越界})
    assert 綠 is True

    通過, 訊息 = 判定架構落點({"src/nova/契約/額度.py": _執行期的同一份越界})
    assert 通過 is False
    assert "src/nova/契約/額度.py:1" in 訊息
    assert "契約不准 import 載體或迴圈" in 訊息


_型別檢查的else裡的越界 = (
    "from typing import TYPE_CHECKING\n"
    "\n"
    "if TYPE_CHECKING:\n"
    "    from nova.契約.額度 import 額度\n"
    "else:\n"
    "    from nova.載體.額度 import 額度來源\n"
)


def test_型別檢查的else那半邊執行期真的會跑所以不放行() -> None:
    """放行的是 `if` 主體，不是整個 `if` 節點——`else` 正是執行期跑的那一半。"""
    綠, 訊息 = 判定架構落點({"src/nova/契約/額度.py": _型別檢查的else裡的越界})

    assert 綠 is False
    assert "src/nova/契約/額度.py:6" in 訊息
    assert "nova.載體.額度" in 訊息


_長得像型別檢查的執行期旗標 = (
    "import 設定\n\nif 設定.TYPE_CHECKING:\n    from nova.載體.額度 import 額度來源\n"
)


def test_自己取名叫TYPE_CHECKING的執行期旗標不算型別檢查() -> None:
    """放行的只有明寫的 `TYPE_CHECKING` 與 `typing.TYPE_CHECKING`。

    `設定.TYPE_CHECKING` 是執行期才決定真假的東西，底下那行**真的會 import**。
    認任何 `<某物>.TYPE_CHECKING` 的話，繞過這道閘只要自己定一個同名屬性。
    """
    通過, 訊息 = 判定架構落點({"src/nova/契約/額度.py": _長得像型別檢查的執行期旗標})

    assert 通過 is False
    assert "src/nova/契約/額度.py:4" in 訊息
    assert "nova.載體.額度" in 訊息


_typing點寫法的型別檢查 = (
    "import typing\n\nif typing.TYPE_CHECKING:\n    from nova.載體.額度 import 額度來源\n"
)


def test_typing點TYPE_CHECKING一樣放行() -> None:
    """收緊到「明寫的兩種」不能誤傷 `typing.TYPE_CHECKING` 這個標準寫法。"""
    通過, _ = 判定架構落點({"src/nova/契約/額度.py": _typing點寫法的型別檢查})

    assert 通過 is True


_相對寫法的越界 = "from ..載體.工作區 import 判定工作區, 拍工作區快照\n"


def test_相對import換個寫法也繞不過去() -> None:
    """`from ..載體.x import y` 指到的就是 `nova.載體.x`，照來源路徑解析後一樣紅。"""
    綠, 訊息 = 判定架構落點({"src/nova/迴圈/工作流.py": _相對寫法的越界})

    assert 綠 is False
    assert "src/nova/迴圈/工作流.py:1" in 訊息
    assert "nova.載體.工作區" in 訊息
    assert "迴圈不准 import 載體" in 訊息


def test_三層落點登記在提交閘也登記在ci閘() -> None:
    """純判定綠不算數：沒有被規則表登記到兩個閘點，它一次都不會跑。"""
    表 = {條.代碼: 條 for 條 in 建規則表(Path("/不存在也沒關係/建表時不該碰硬碟"))}

    assert "layer-boundaries" in 表
    assert {"提交", "ci"} <= set(表["layer-boundaries"].閘點)
