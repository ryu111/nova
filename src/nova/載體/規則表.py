"""規則表：閘的 context（規格 §2.2 第一問）。

一條規則登記在這裡，才會有任何執行點跑它。想加規則就加在這裡，
不要在 `.pre-commit-config.yaml`／`gates.yml`／hook 設定裡塞邏輯——
那些地方的程式碼沒辦法測試，等於沒有保證。
"""

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from nova.載體.機密 import 檢查機密
from nova.載體.測試數 import 檢查測試數
from nova.載體.語言 import 檢查繁體中文
from nova.載體.閘 import 型別, 測試, 規則, 靜態


def _外部指令(根目錄: Path, *指令: str) -> Callable[[], tuple[bool, str]]:
    """把一條外部指令包成檢查函式。

    執行檔從 `sys.executable` 旁邊找——nova 跑在哪個 venv，就用哪個 venv 的
    ruff／mypy／pytest，不看 PATH。PATH 會讓本地與 CI 跑到不同版本。
    """
    工具目錄 = Path(sys.executable).parent

    def 檢查() -> tuple[bool, str]:
        執行檔 = 工具目錄 / 指令[0]
        完整 = [str(執行檔) if 執行檔.exists() else 指令[0], *指令[1:]]
        結果 = subprocess.run(  # noqa: S603 —— 指令由本表寫死，不吃外部輸入
            完整, cwd=根目錄, capture_output=True, text=True, check=False
        )
        輸出 = (結果.stdout + 結果.stderr).strip()
        return 結果.returncode == 0, 輸出

    return 檢查


def 建規則表(根目錄: Path) -> list[規則]:
    """建出這個 repo 的完整規則表。建表本身不碰硬碟，跑的時候才碰。

    階段安排就是資源排程：靜態檢查（秒級）先跑，型別次之，測試最後。
    一次只跑一條，避免 ruff 與 pytest 同時吃滿 CPU 讓對時間敏感的檢查無故變紅。
    """
    全部 = frozenset({"提交", "ci"})
    return [
        規則(
            代碼="lang-traditional",
            名稱="繁體中文（不准簡體字與日文新字體）",
            閘點=全部,
            負責層="載體",
            檢查=lambda: 檢查繁體中文(根目錄),
            階段=靜態,
        ),
        規則(
            代碼="no-secrets",
            名稱="機密不進版控",
            閘點=全部,
            負責層="載體",
            檢查=lambda: 檢查機密(根目錄),
            階段=靜態,
        ),
        規則(
            代碼="test-count",
            名稱="測試數不准減少",
            閘點=全部,
            負責層="載體",
            檢查=lambda: 檢查測試數(根目錄),
            階段=靜態,
        ),
        規則(
            代碼="ruff-check",
            名稱="ruff 靜態檢查",
            閘點=全部,
            負責層="載體",
            檢查=_外部指令(根目錄, "ruff", "check", "."),
            階段=靜態,
        ),
        規則(
            代碼="ruff-format",
            名稱="ruff 格式",
            閘點=全部,
            負責層="載體",
            檢查=_外部指令(根目錄, "ruff", "format", "--check", "."),
            階段=靜態,
        ),
        規則(
            代碼="mypy",
            名稱="型別（strict）",
            閘點=全部,
            負責層="載體",
            檢查=_外部指令(根目錄, "mypy"),
            階段=型別,
        ),
        規則(
            代碼="pytest-unit",
            名稱="單元測試（序列、秒級）",
            閘點=frozenset({"提交"}),
            負責層="載體",
            檢查=_外部指令(根目錄, "pytest", "tests/單元", "-q"),
            階段=測試,
            涵蓋於="pytest-parallel",  # CI 跑全測試時會包含 tests/單元
        ),
        規則(
            代碼="pytest-parallel",
            名稱="全測試（平行，不含 serial）",
            閘點=frozenset({"ci"}),
            負責層="載體",
            檢查=_外部指令(
                根目錄, "pytest", "-m", "not serial", "-n", "auto", "--dist", "worksteal", "-q"
            ),
            階段=測試,
        ),
        規則(
            代碼="pytest-serial",
            名稱="序列測試（會搶資源、不可平行）",
            閘點=frozenset({"ci"}),
            負責層="載體",
            檢查=_外部指令(根目錄, "pytest", "-m", "serial", "-q", "-p", "no:randomly"),
            階段=測試,
        ),
    ]
