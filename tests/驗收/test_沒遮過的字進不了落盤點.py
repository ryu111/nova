"""決策 0002 的第一個實例：**「寫沒遮過的東西」要變成編不過。**

## 為什麼是這一條先做

2026-08-30 之前，遮罩靠四個落盤點各自記得呼叫 `遮罩()`：

```
命令列.py   成果帳的任務
收件.py     接續票的前情
收件.py     歸檔的原始請求
記帳.py     模型回應
```

**四個裡漏了一個**，而且是靠真的跑一次端到端才發現的——
PR #95 的標題就是那句話：「模型講的話被遮了，你自己打的那句話沒有」。

repo 是 public，**洩漏一次就是永久的**（GitHub 的快取與別人的 clone
收不回來）。所以這一條的代價最高，而它已經失敗過一次。

## 兩道網，缺一不可

1. **mypy**：落盤欄位收 `已遮罩文字`，餵原始 `str` 會紅。
   擋的是「忘了呼叫遮罩」——最常見的那種。
2. **測試**：`已遮罩文字(...)` 只准出現在 `遮罩.py` 裡。
   擋的是「知道有這個型別，然後硬轉」——`NewType` 擋不住的那種。

只有第 1 道的話，一句 `已遮罩文字(祕密)` 就繞過去了，而且它會編得過。
"""

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

專案根 = Path(__file__).resolve().parent.parent.parent


#: 每一個收遮過文字的**落盤欄位或落盤入口**都要在這裡登記一行。
#:
#: `{文字}` 是那一格要填的東西：測試會填一次沒遮過的、一次遮過的，
#: 前者要紅、後者要綠。**兩邊都驗**——只驗紅的話，一個永遠紅的
#: 樣板（例如打錯欄位名）也會讓這支測試綠。
_成果 = """from nova.契約.成果 import 成果
一筆 = 成果(
    執行識別碼="x",
    任務={文字},
    收場="done",
    退出碼=0,
    起="",
    迄="",
    走了幾階=1,
    總token=0,
)
"""

_帳本 = """from nova.契約.帳本 import 事件, 事件種類
一筆 = 事件(種類=事件種類.呼叫結束, 文字={文字})
"""

#: 下面兩個不是欄位是**函式參數**：`write_text` 與 f-string 都不會讓型別
#: 流過去，所以那兩處各包一層收得到型別的入口，讓忘了遮在 mypy 就紅。
_接續票 = """from nova.載體.收件 import _接續票內容
內容 = _接續票內容("題", 前情={文字}, 輪次=2, 上一輪="")
"""

_歸檔 = """from pathlib import Path
from nova.載體.收件 import _寫下遮過的
_寫下遮過的(Path("x"), {文字})
"""

_落盤點: tuple[tuple[str, str], ...] = (
    ("成果.任務", _成果),
    ("帳本.事件.文字", _帳本),
    ("收件._接續票內容 的前情", _接續票),
    ("收件._寫下遮過的 的文字", _歸檔),
)


def _片段(樣板: str, 那一格: str) -> str:
    """組一份會被 mypy 檢查的最小程式碼。

    **其他欄位照實際簽章給滿**：不然紅的會是「少了必填欄位」而不是
    「那一格型別不對」——那樣這支測試在好壞兩種狀態下都紅，分不出東西。
    """
    return "from nova.載體.遮罩 import 遮罩\n\n" + 樣板.replace("{文字}", 那一格)


def _跑mypy(檔: Path) -> subprocess.CompletedProcess[str]:
    """**要帶 MYPYPATH，而且不准吃快取。**

    `MYPYPATH`：nova 沒有 `py.typed`，不帶的話 mypy 會說「module is
    installed, but missing library stubs」然後兩種狀態都紅。

    `--no-incremental`：**mypy 的快取鍵是 `int(mtime) ＋ size`，不含內容**
    ——跟 ruff 那條是同一個坑（CLAUDE.md 有記）。跑負控時當場踩到：
    把 `_接續票內容` 與 `_寫下遮過的` 的型別各改回 `str`，兩次破壞
    **檔案長度完全一樣**（6685），又落在同一秒，於是第二次 mypy
    直接回報第一次的錯誤——**指名的那一格沒紅、別的格紅了**。
    人手改檔碰不到，腳本或 agent 連續改檔一定碰得到。
    """
    return subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", "--no-incremental", str(檔)],
        cwd=專案根,
        env={**os.environ, "MYPYPATH": str(專案根 / "src")},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(("名", "樣板"), _落盤點, ids=[名 for 名, _ in _落盤點])
def test_型別真的擋得住沒遮過的字(名: str, 樣板: str, tmp_path: Path) -> None:
    """**這一支是重點。** 沒有它，「型別擋得住」只是宣稱。

    寫一份會犯那個錯的程式碼，真的跑一次 mypy，看它紅。
    """
    壞例子 = tmp_path / "壞例子.py"
    壞例子.write_text(_片段(樣板, '"這是沒遮過的原始字串"'), encoding="utf-8")

    跑完 = _跑mypy(壞例子)

    assert 跑完.returncode != 0, f"{名} 放行了沒遮過的字：\n{跑完.stdout}"
    assert "已遮罩文字" in 跑完.stdout, 跑完.stdout


@pytest.mark.parametrize(("名", "樣板"), _落盤點, ids=[名 for 名, _ in _落盤點])
def test_遮過的字就編得過(名: str, 樣板: str, tmp_path: Path) -> None:
    """**不能擋到正常用法**——擋過頭的閘會被繞過，繞過一次就等於不存在。"""
    好例子 = tmp_path / "好例子.py"
    好例子.write_text(_片段(樣板, '遮罩("原始的字").文字'), encoding="utf-8")

    跑完 = _跑mypy(好例子)

    assert 跑完.returncode == 0, f"{名} 擋到了正常用法：\n{跑完.stdout}"


def test_不准在遮罩以外的地方硬轉() -> None:
    """**NewType 擋不住硬轉**：`已遮罩文字(祕密)` 編得過。

    所以第二道網是這支測試：那個建構子只准出現在 `遮罩.py` 裡。
    沒有它，第一道網一行就繞過去了。
    """
    造出來的 = re.compile(r"已遮罩文字\s*\(")
    犯規 = [
        f"{路.relative_to(專案根)}:{號}"
        for 路 in (專案根 / "src").rglob("*.py")
        if 路.name != "遮罩.py"
        for 號, 行 in enumerate(路.read_text(encoding="utf-8").splitlines(), 1)
        if 造出來的.search(行)
    ]

    assert not 犯規, "只有 遮罩.py 可以造出 已遮罩文字：\n  " + "\n  ".join(犯規)


def test_收件的落盤只准走遮過的那個入口() -> None:
    """**型別擋得住參數，擋不住 `write_text`。**

    `收件.py` 有兩種寫檔，分得很開：

    | 寫什麼 | 遮不遮 | 為什麼 |
    |---|---|---|
    | 收件匣的票 | **不遮** | 那是**輸入**，要原封不動餵回模型；遮了模型看到的是 `[遮罩:…]` |
    | `已處理/` 的歸檔 | **要遮** | 那是**紀錄**，躺在磁碟上直到有人刪掉，而 repo 是 public |

    分錯邊的代價是不對稱的：把輸入遮掉只是模型看不懂，把紀錄漏遮是永久外洩。
    所以歸檔那條路收 `已遮罩文字`，而這支測試守著「沒有第二條路繞過去」。
    """
    檔 = 專案根 / "src/nova/載體/收件.py"
    准寫的 = {"_寫下遮過的", "_落一個檔"}
    樹 = ast.parse(檔.read_text(encoding="utf-8"))

    犯規 = [
        f"{住哪.name}:{節點.lineno}"
        for 住哪 in ast.walk(樹)
        if isinstance(住哪, ast.FunctionDef) and 住哪.name not in 准寫的
        for 節點 in ast.walk(住哪)
        if isinstance(節點, ast.Call)
        and isinstance(節點.func, ast.Attribute)
        and 節點.func.attr == "write_text"
    ]

    assert not 犯規, "落盤要走 " + "／".join(sorted(准寫的)) + f"，不要自己寫檔：{犯規}"
