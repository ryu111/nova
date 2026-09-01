"""資料夾架構規範的可執行版本。

規範寫在 ~/.claude/rules/專案結構.md，但文件不會 fail；這支測試會。
任何人改壞骨架（把套件搬回根目錄、拿掉 __init__.py、弄丟架構文件），這裡會紅。
"""

from pathlib import Path

import pytest

子套件 = ["載體", "迴圈", "契約"]
測試層 = ["單元", "整合", "驗收"]
#: 三層之外只准這兩個，而且都不是「一層」：`負控` 是變異登記與執行器，
#: `資料` 是 fixture 用的樣本檔。兩個都不放測試函式。
測試目錄白名單 = {*測試層, "負控", "資料"}


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


def test_測試只准這三層(專案根: Path) -> None:
    """多開一層等於三層分類法失效。

    三層是**時間預算**不是分類學——多一個 `tests/架構/` 就沒人知道它該在提交閘跑
    還是 CI 跑，而提交閘只跑 `tests/單元`，所以新層預設不在任何一個閘裡。

    實測 2026-09-01：R02 那一格真的開了 `tests/架構/`，13 條閘全綠——
    上面那支只驗「三層都在」，沒驗「只有三層」。
    """
    多出來的 = sorted(
        目錄.name
        for 目錄 in (專案根 / "tests").iterdir()
        if 目錄.is_dir()
        and not 目錄.name.startswith((".", "__"))
        and 目錄.name not in 測試目錄白名單
    )
    assert not 多出來的, f"測試只准 {sorted(測試目錄白名單)}，多了：{多出來的}"


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


#: 「這支測試會 fork 子程序」的可靠信號。**只列真的會 fork 的**——
#: `執行檔=Path("/不存在")` 只是組參數，不 fork，所以不在這裡。
_會fork的痕跡 = ("import subprocess", "S_IEXEC", "跑cli(")


def test_單元層不准fork子程序(專案根: Path) -> None:
    """單元層的定義是「純函式、不碰 I/O」——fork 一支子程序不是純函式。

    這條不是潔癖，是拿實測換來的。原本 `test_門面.py` 與 `test_repo檢查.py`
    掛在單元層，前者每支 fork 一支現寫的假 CLI、後者每支建一個迷你 git repo：

    | | 秒 |
    |---|---|
    | 單元層（含那兩支） | 5.91 |
    | 兩支都搬到整合層之後 | **0.10** |
    | 提交閘（含那兩支） | 7.10 |
    | 提交閘（搬完） | **1.18** |

    `pytest tests/單元` 是提交閘唯一的測試規則，所以那 5.8 秒**每次 commit 都付一次**。
    commit 慢到某個程度，人就會開始想繞過閘門——而繞過一次，閘門就等於不存在。

    搬走不會少一層保護：`test_repo檢查.py` 測的那三條規則（機密、測試數、繁體中文）
    本來就在提交閘裡對真 repo 實跑，單元測試搬到哪一層都不影響那個。
    """
    髒的 = []
    for 檔 in sorted((專案根 / "tests" / "單元").rglob("test_*.py")):
        內容 = 檔.read_text(encoding="utf-8")
        命中 = [痕 for 痕 in _會fork的痕跡 if 痕 in 內容]
        if 命中:
            髒的.append(f"{檔.relative_to(專案根)}：{'、'.join(命中)}")
    assert not 髒的, "這幾支會 fork 子程序，屬於整合層不是單元層：\n" + "\n".join(髒的)
