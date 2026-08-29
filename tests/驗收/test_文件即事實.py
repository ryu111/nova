"""文件宣稱存在的東西，必須真的存在。

這支是被一次真實失誤逼出來的：我寫了一組測試、pytest 也綠，
但寫入檔案的 `str.replace` 錨點沒對上、**靜默不動**，那組測試從未進過 commit——
而 PR 說明與 CLAUDE.md 的固定負控表已經在宣稱它們存在了。

`test-count` 抓不到：它只擋「測試變少」，擋不了「我以為我加了」。

宿主反轉那份文件的說法是：**宣稱有把關卻沒有，比沒有規範更糟**——
讀的人會以為不用自己檢查。
"""

import json
import re
from pathlib import Path
from typing import Any

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
    """CLAUDE.md、設計文件、決策紀錄、負控紀錄。

    負控紀錄與決策紀錄一定要在這份清單裡：那 40 個測試名原本住 CLAUDE.md、
    受這支測試保護，**搬家不能把保護搬丟**。
    """
    return [
        專案根目錄 / "CLAUDE.md",
        專案根目錄 / "docs" / "負控紀錄.md",
        *sorted((專案根目錄 / "docs" / "設計").glob("*.md")),
        *sorted((專案根目錄 / "docs" / "決策").glob("*.md")),
    ]


#: CLAUDE.md 的行數上限。**這是 ratchet：它只准往下調。**
#:
#: 270 → 150 那次砍掉的是「方法論」與「設計文件的摘要」，留下的只有**坑**——
#: 看檔案看不出來、踩到會很貴、下次還會再踩的那些。判準來自
#: Anthropic 的〈The new rules of context engineering for Claude 5 generation
#: models〉：「Keep your CLAUDE.md lightweight」「spend most of the tokens on
#: gotchas inside of the codebase」「Avoid stating 'the obvious' things Claude
#: should know by looking at your file system」。同一篇說他們砍掉 Claude Code
#: 系統提示 80% 以上，coding eval 沒有可測量的損失。
#:
#: 代價是真的：「Bloated CLAUDE.md files cause Claude to ignore your actual
#: instructions」——規則檔變長不只是浪費，是**讓其他規則失效**。
#: 所以要加東西之前先問三題：Claude 看檔案就知道嗎（刪掉）？機械判準抓得到嗎
#: （寫成閘）？只有某些任務要嗎（寫成 skill）？三題都否才進這裡。
CLAUDE_MD行數上限 = 150


def test_CLAUDE_md不准無限長() -> None:
    """規則檔不准當流水帳。

    這是使用者立的規則的機械版：「不要把 CLAUDE.md 跟 rule 當流水帳，
    帳本是另外的」。沒有這個閘，那條規則就只是一句話——而只以文件形式
    存在的規範等於不存在（宿主反轉判準一）。
    """
    行數 = len((專案根目錄 / "CLAUDE.md").read_text(encoding="utf-8").splitlines())
    assert 行數 <= CLAUDE_MD行數上限, (
        f"CLAUDE.md 有 {行數} 行，超過上限 {CLAUDE_MD行數上限}。"
        "先問要加的那段該不該進閘或 skill，見 docs/決策/0001-規則要住哪一層.md"
    )


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


def _路線圖節點() -> list[dict[str, Any]]:
    """把路線圖裡內嵌的那份 JSON 讀出來。

    它不是 Markdown，反引號那套抓不到——路徑住在 `"檔": [...]` 陣列裡。
    """
    原文 = (專案根目錄 / "docs" / "路線圖.html").read_text(encoding="utf-8")
    找到 = re.search(r'<script[^>]*id="圖資料"[^>]*>(.*?)</script>', 原文, re.DOTALL)
    assert 找到 is not None, "路線圖的圖資料區塊不見了，這支檢查會變成永遠綠的假保護"
    節點 = json.loads(找到.group(1))["節點"]
    assert isinstance(節點, list)
    return 節點


def test_路線圖有節點可以檢查() -> None:
    assert len(_路線圖節點()) > 30, "抓不到路線圖節點，這支檢查會變成永遠綠的假保護"


def test_路線圖指到的檔案都真的存在() -> None:
    """路線圖每一格宣稱的實作檔必須存在。

    這一格是被這次改動逼出來的：路線圖有 39 格、指到二十幾個路徑，
    而 `test_文件提到的檔案都真的存在` 只掃 Markdown 的反引號，
    **一條都掃不到**。搬了檔案沒改路線圖，圖會繼續宣稱它在那裡。
    """
    缺的 = [
        f"{節點['id']} 指到 {路徑}"
        for 節點 in _路線圖節點()
        for 路徑 in 節點.get("檔", [])
        if not (專案根目錄 / str(路徑)).exists()
    ]
    assert not 缺的, "路線圖宣稱存在但找不到的檔案：\n  " + "\n  ".join(缺的)
