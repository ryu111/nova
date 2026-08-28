"""資料夾架構規範的可執行版本。

規範寫在 ~/.claude/rules/專案結構.md，但文件不會 fail；這支測試會。
任何人改壞骨架（把套件搬回根目錄、拿掉 __init__.py、弄丟架構文件），這裡會紅。
"""

from pathlib import Path

import pytest

子套件 = ["載體", "迴圈", "契約"]
測試層 = ["單元", "整合", "驗收"]


def test_採用_src_layout_而非_flat_layout(專案根: Path) -> None:
    """匯入用的套件只能住在 src/ 底下。

    根目錄若出現 nova/，就是 flat layout：測試會匯入到工作目錄那份原始碼，
    而不是安裝好的那份，打包壞掉不會被測出來。
    """
    套件 = 專案根 / "src" / "nova"
    assert 套件.is_dir(), "src/nova/ 不存在"
    assert (套件 / "__init__.py").is_file(), "src/nova/__init__.py 不存在"
    assert not (專案根 / "nova").exists(), "根目錄出現 nova/，src layout 被破壞"


@pytest.mark.parametrize("名稱", 子套件)
def test_三層子套件各自是真套件(專案根: Path, 名稱: str) -> None:
    """子套件必須有 __init__.py，否則打錯字會靜默變成 namespace package。"""
    目錄 = 專案根 / "src" / "nova" / 名稱
    assert 目錄.is_dir(), f"src/nova/{名稱}/ 不存在"
    assert (目錄 / "__init__.py").is_file(), f"src/nova/{名稱}/__init__.py 不存在"


@pytest.mark.parametrize("名稱", 測試層)
def test_測試分三層(專案根: Path, 名稱: str) -> None:
    """單元／整合／驗收三層都要在，否則驗收測試會被塞進單元測試裡混掉。"""
    assert (專案根 / "tests" / 名稱).is_dir(), f"tests/{名稱}/ 不存在"


def test_架構文件留在_repo_內(專案根: Path) -> None:
    """三層架構規範是 nova 的第一份規格，必須自帶，不能靠桌面上的外部檔案。"""
    文件 = 專案根 / "docs" / "AGENT_ARCHITECTURE.md"
    assert 文件.is_file(), "docs/AGENT_ARCHITECTURE.md 不存在"
    assert "Harness" in 文件.read_text(encoding="utf-8")


def test_設定集中在_pyproject(專案根: Path) -> None:
    """單一設定來源：pytest／ruff／mypy 都不准另開設定檔。"""
    內容 = (專案根 / "pyproject.toml").read_text(encoding="utf-8")
    for 區段 in ["[tool.pytest.ini_options]", "[tool.ruff]", "[tool.mypy]"]:
        assert 區段 in 內容, f"pyproject.toml 缺少 {區段}"
    for 散落 in ["pytest.ini", "setup.py", "setup.cfg", "tox.ini", ".ruff.toml"]:
        assert not (專案根 / 散落).exists(), f"設定散落到 {散落}"
