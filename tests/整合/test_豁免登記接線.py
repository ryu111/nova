"""確認 CI 的 ruff 豁免閘是從規則表跑出來的。"""

from pathlib import Path

from nova.載體.規則表 import 建規則表
from nova.載體.閘 import 跑閘


def test_ci閘經建規則表真的會跑ruff豁免() -> None:
    """這支故意不直接呼叫 `檢查ruff豁免`，守的是規則表的可達性。"""
    根目錄 = Path(__file__).resolve().parents[2]
    表 = 建規則表(根目錄)
    結果 = 跑閘("ci", [條 for 條 in 表 if 條.代碼 == "ruff-exemptions"])

    assert [條.代碼 for 條 in 結果] == ["ruff-exemptions"], "ruff-exemptions 沒有從規則表跑到"
    assert 結果[0].通過 is True, 結果[0].證據
