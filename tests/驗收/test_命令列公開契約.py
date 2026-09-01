"""CLI 公開介面與退出碼契約的驗收測試。

退出碼 0／1／2／3／4 是外圈重跑、修復與安全性檢查的契約保證。
契約層（nova.契約.退出碼）是唯一所有者，載體層（nova.載體.命令列）只負責使用，不准自行發明或持有退出碼定義。
"""

import tomllib
from pathlib import Path

from nova.契約.模型回應 import 終局
from nova.契約.退出碼 import (
    _終局的退出碼,
    放行,
    未知,
    護欄碼,
    閘紅,
    阻擋,
)
from nova.載體 import 命令列


def test_退出碼契約五值唯一來源() -> None:
    """退出碼五個常數必須嚴格符合約定且彼此互斥。

    - 放行 (0): 成功
    - 閘紅 (1): 確定失敗
    - 阻擋 (2): agent hook 約定
    - 未知 (3): 結果未知，外圈不准重跑
    - 護欄碼 (4): 護欄生效，按設計停下，外圈不准自動調高上限
    """
    assert 放行 == 0
    assert 閘紅 == 1
    assert 阻擋 == 2
    assert 未知 == 3
    assert 護欄碼 == 4

    五值 = [放行, 閘紅, 阻擋, 未知, 護欄碼]
    assert all(isinstance(值, int) for 值 in 五值)
    assert len(set(五值)) == 5, "五個退出碼數值必須互斥"


def test_終局到退出碼映射契約() -> None:
    """終局三值（成功、確定失敗、結果未知）精確映射到三種退出碼。

    阻擋 (2) 與護欄碼 (4) 不屬於模型終局判定。
    """
    assert _終局的退出碼[終局.成功] == 放行
    assert _終局的退出碼[終局.確定失敗] == 閘紅
    assert _終局的退出碼[終局.結果未知] == 未知
    assert len(_終局的退出碼) == 3


def test_命令列載體使用同源退出碼() -> None:
    """載體層命令列模組的退出碼必須與契約層同一來源。"""
    assert getattr(命令列, "放行", None) is 放行
    assert getattr(命令列, "閘紅", None) is 閘紅
    assert getattr(命令列, "阻擋", None) is 阻擋
    assert getattr(命令列, "未知", None) is 未知
    assert getattr(命令列, "護欄碼", None) is 護欄碼
    assert getattr(命令列, "_終局的退出碼", None) is _終局的退出碼


def test_pyproject中nova命令列入口契約(專案根: Path) -> None:
    """驗證 pyproject.toml 註冊的 console script 指向正確的主程式入口。"""
    設定檔 = 專案根 / "pyproject.toml"
    assert 設定檔.is_file(), "pyproject.toml 不存在"

    with 設定檔.open("rb") as f:
        設定 = tomllib.load(f)

    指令表 = 設定.get("project", {}).get("scripts", {})
    assert "nova" in 指令表, "pyproject.toml 缺少 nova 命令列 script 註冊"
    assert 指令表["nova"] == "nova.載體.命令列:主程式"
    assert callable(getattr(命令列, "主程式", None))
