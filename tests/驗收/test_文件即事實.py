"""文件宣稱存在的東西，必須真的存在。

這支是被一次真實失誤逼出來的：我寫了一組測試、pytest 也綠，
但寫入檔案的 `str.replace` 錨點沒對上、**靜默不動**，那組測試從未進過 commit——
而 PR 說明與 CLAUDE.md 的固定負控表已經在宣稱它們存在了。

`test-count` 抓不到：它只擋「測試變少」，擋不了「我以為我加了」。

宿主反轉那份文件的說法是：**宣稱有把關卻沒有，比沒有規範更糟**——
讀的人會以為不用自己檢查。
"""

import re
from pathlib import Path

import pytest

專案根目錄 = Path(__file__).resolve().parents[2]
# 中文範圍用跳脫寫法：直接寫範圍邊界字元會被繁體閘當成非繁體字（它確實不是）。
_中文 = r"\u4e00-\u9fff"
_測試名 = re.compile(rf"`(test_[\w{_中文}]+)`")
_檔案路徑 = re.compile(rf"`((?:src|tests|docs)/[\w./{_中文}-]+\.(?:py|md|html|yml))`")


def _全部測試函式名() -> set[str]:
    名字: set[str] = set()
    for 檔 in (專案根目錄 / "tests").rglob("test_*.py"):
        名字 |= set(re.findall(rf"def (test_[\w{_中文}]+)", 檔.read_text(encoding="utf-8")))
    return 名字


def _要檢查的文件() -> list[Path]:
    return [專案根目錄 / "CLAUDE.md", *sorted((專案根目錄 / "docs" / "設計").glob("*.md"))]


@pytest.fixture(scope="module")
def 測試名們() -> set[str]:
    return _全部測試函式名()


def test_有測試可以檢查(測試名們: set[str]) -> None:
    assert len(測試名們) > 100, "抓不到測試函式名，這支檢查會變成永遠綠的假保護"


def test_文件提到的測試都真的存在(測試名們: set[str]) -> None:
    """固定負控表裡指名的測試，必須真的在測試套件裡。"""
    缺的 = [
        f"{文件.name} 提到 {名}"
        for 文件 in _要檢查的文件()
        for 名 in _測試名.findall(文件.read_text(encoding="utf-8"))
        if 名 not in 測試名們
    ]
    assert not 缺的, "文件宣稱存在但找不到的測試：\n  " + "\n  ".join(缺的)


def test_文件提到的檔案都真的存在() -> None:
    """文件指到的路徑必須存在。搬了檔案沒改文件，這支會紅。"""
    缺的 = [
        f"{文件.name} 提到 {路徑}"
        for 文件 in _要檢查的文件()
        for 路徑 in _檔案路徑.findall(文件.read_text(encoding="utf-8"))
        if not (專案根目錄 / 路徑).exists()
    ]
    assert not 缺的, "文件宣稱存在但找不到的檔案：\n  " + "\n  ".join(缺的)
