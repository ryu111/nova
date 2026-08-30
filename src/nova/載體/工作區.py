"""結果未知時，唯讀查工作區並交出可行動的證據。"""

import hashlib
from collections.abc import Mapping
from pathlib import Path

from nova.契約.工作流 import (
    任務,
    工作區判定,
    工作區狀態,
    階段代碼,
    階段定義,
)
from nova.載體.git查詢 import 跑git
from nova.載體.規則表 import 建規則表
from nova.載體.閘 import 跑閘

_略過目錄 = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def 拍工作區快照(根目錄: Path) -> dict[str, str]:
    """拍下工作區檔案雜湊；快取與版控資料不算工作內容。"""
    if not 根目錄.is_dir():
        return {}
    return {
        str(檔案.relative_to(根目錄)): hashlib.sha256(檔案.read_bytes()).hexdigest()
        for 檔案 in sorted(根目錄.rglob("*"))
        if 檔案.is_file() and not _略過目錄.intersection(檔案.parts)
    }


拍快照 = 拍工作區快照  # 相容別名


def 判定工作區(
    任: 任務,
    階段: 階段代碼,
    *,
    前快照: Mapping[str, str] | None = None,
    階段表: tuple[階段定義, ...] | None = None,
) -> 工作區判定:
    """只讀一次工作區，分出沒動、全綠與有名紅。"""
    if not 任.工作目錄.is_dir():
        訊息 = f"工作目錄不存在：{任.工作目錄}"
        raise OSError(訊息)
    if _工作區沒被動過(任.工作目錄, 前快照):
        return 工作區判定(
            工作區狀態.沒被動過,
            未跑的階段=_未跑階段(階段, 階段表, 包含目前=True),
        )

    結果們 = 跑閘("ci", 建規則表(任.工作目錄), 提前停止=False)
    綠的 = tuple(結果.代碼 for 結果 in 結果們 if 結果.通過)
    紅的 = tuple(結果.代碼 for 結果 in 結果們 if not 結果.通過)
    return 工作區判定(
        工作區狀態.綠 if not 紅的 else 工作區狀態.紅,
        綠的=綠的,
        紅的=紅的,
        未跑的階段=_未跑階段(階段, 階段表, 包含目前=False),
    )


def _工作區沒被動過(根目錄: Path, 前快照: Mapping[str, str] | None) -> bool:
    """判斷工作區是否維持原樣。

    兩套機制有明確的主備關係：
    - 主：`前快照`（雜湊比對）。工作流每步開跑前拍快照，唯有快照才能擋下
      「開跑前工作區就已經有未追蹤檔案或髒變更」的情況，避免誤把前人殘留當成本步成果。
    - 備：`_有變動`（git status）。未傳前快照時的單獨呼叫備援；
      不是 git repo 則交由上層 fail-closed。
    """
    if 前快照 is not None:
        return 前快照 == 拍工作區快照(根目錄)
    return not _有變動(根目錄)


def _有變動(根目錄: Path) -> bool:
    """用 git 狀態判斷工作區是否有變動；不是 repo 就交給上層 fail-closed。"""
    結果 = 跑git(根目錄, "status", "--porcelain", "--untracked-files=all")
    if 結果.returncode != 0:
        raise OSError(結果.stderr.strip() or "工作區不是可查詢的 git repo")
    return bool(結果.stdout.strip())


def _未跑階段(
    目前: 階段代碼,
    階段表: tuple[階段定義, ...] | None = None,
    *,
    包含目前: bool = False,
) -> tuple[階段代碼, ...]:
    """列出尚未進入或未跑的階段。沒被動過時包含目前階段，其餘只列後續階段。"""
    代碼清單 = tuple(定義.代碼 for 定義 in 階段表) if 階段表 is not None else tuple(階段代碼)
    for 位置, 代碼 in enumerate(代碼清單):
        if 代碼 is 目前:
            起點 = 位置 if 包含目前 else 位置 + 1
            return 代碼清單[起點:]
    return ()
