"""收尾的時候真的去跑驗收。**模型說做完了不算，驗收指令回 0 才算。**

## 這一格補的是哪一半

`#172` 讓自主票必須**宣告**驗收，`#175` 讓驗收指令**跑得動**——
但沒有人在收尾時去跑它。所以到上一格為止，收件匣迴圈的停止條件仍然是
「工作流回 0」，而那個 0 的意思是**模型沒有摔**，不是**事情做對了**。

CLAUDE.md 硬規則第 2 條不准以「模型說完成了」當停止條件。這一格是把判準換掉。

## 為什麼驗收紅回 4 而不是 1

4 的定義是「停止規則按設計生效」，本來就包含「重構改壞行為」那一類。
驗收紅是同一種東西：工作流跑完了，但**它沒做到**。

而且回 4 之後**不必新增任何流程**：`_也許接著排` 已經在看 `碼 == 護欄碼`，
`最多輪次 = 3` 已經是那個重試迴圈的停止規則。
使用者說的「做錯了讓他退了再做」就是這條現成的路。

回 1 的話它會停在那裡等人，回 3 更糟（3 是「不知道做了沒」，腳本不准重跑）。
"""

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from nova.載體.命令列 import _驗收說了算, 主程式, 護欄碼
from nova.載體.收件 import 丟一件, 你敲, 待處理, 收下一件, 收件目錄, 時鐘


def _跑收件匣(專案: Path, 狀態: Path, 判準: str = "true") -> subprocess.CompletedProcess[str]:
    """在 `專案` 上跑一輪 `工作流 --從收件匣`，不打任何一家 LLM。

    `--用 假腦` 會讓模型呼叫直接失敗，所以這裡只驗**收尾那一段**的判斷。
    """
    return subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "nova",
            "工作流",
            "--從收件匣",
            "--工作目錄",
            str(專案),
            "--判準",
            判準,
            "--不記帳",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "XDG_STATE_HOME": str(狀態)},
        timeout=180,
    )


def test_驗收紅的票不准當成做完(tmp_path: Path) -> None:
    """**這一支是這一格存在的理由。**

    票宣告的驗收指令回非 0，那一輪就不算做完——不管工作流自己回什麼。
    """
    收件 = tmp_path / "收件"
    丟一件("做某件事\n\n<!--nova:驗收 /usr/bin/false-->", 來源=時鐘, 目錄=收件)
    單 = 待處理(收件)
    assert 單

    收下的 = 收下一件(收件)
    assert 收下的 is not None
    assert 收下的.驗收 == ("/usr/bin/false",)
    assert _驗收說了算(收下的, 碼=0, 工作目錄=tmp_path) == 4


def test_驗收綠就照原本的碼走(tmp_path: Path) -> None:
    收件 = tmp_path / "收件"
    丟一件("做某件事\n\n<!--nova:驗收 /usr/bin/true-->", 來源=時鐘, 目錄=收件)
    單 = 收下一件(收件)
    assert 單 is not None
    assert _驗收說了算(單, 碼=0, 工作目錄=tmp_path) == 0


def test_沒宣告驗收的票不受影響(tmp_path: Path) -> None:
    """人給的票不必帶驗收（`#172`）。

    **不准因為沒宣告就判它沒做完**——那會讓每一張手丟的票都退回重做。
    """
    收件 = tmp_path / "收件"
    丟一件("看看這段為什麼慢", 來源=你敲, 目錄=收件)
    單 = 收下一件(收件)
    assert 單 is not None
    assert _驗收說了算(單, 碼=0, 工作目錄=tmp_path) == 0


def test_工作流本來就沒成功時不跑驗收(tmp_path: Path) -> None:
    """**碼不是 0 的時候一條驗收都不准跑。**

    危險的不是多燒一次時間，是**改寫退出碼的語意**：
    `3`（結果未知）被驗收紅改寫成 `4`（護欄）之後，`_也許接著排` 就會
    自動排一張接續票——而 3 的意思正是「不知道那件事做了沒」，
    **重跑會把可能已經做過的事再做一次**。

    所以這裡用**永遠紅**的驗收：綠的驗收測不出差別（綠就回原碼），
    只有紅的才看得出「有沒有真的去跑」。
    """
    收件 = tmp_path / "收件"
    # **永遠紅**：碼非 0 時如果去跑它，1 與 3 都會被改寫成 4。
    丟一件("做某件事\n\n<!--nova:驗收 /usr/bin/false-->", 來源=時鐘, 目錄=收件)
    單 = 收下一件(收件)
    assert 單 is not None
    for 原本的碼 in (1, 3, 4):
        assert _驗收說了算(單, 碼=原本的碼, 工作目錄=tmp_path) == 原本的碼


def test_沒有收件單的時候原樣回去(tmp_path: Path) -> None:
    """`nova 工作流 "一句話"` 那條路沒有收件單，不能因此炸掉。"""
    assert _驗收說了算(None, 碼=0, 工作目錄=tmp_path) == 0


@pytest.mark.serial
def test_端到端_驗收紅的票會退回收件匣而不是進已處理(
    tmp_path: Path,
    做假CLI: Callable[..., tuple[Path, Path]],
    翻牌判準: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**這一支才守得到接線本身。**

    上面那幾支測的是 `_驗收說了算` 這個函式；把 `_跑一件` 裡呼叫它那一行拿掉，
    它們全部照樣綠——那時候保證就只活在「我看過 code」上。

    這裡讓假 CLI 走完整個工作流（本來會回 0），票宣告一條永遠紅的驗收，
    然後斷言三件事：退出碼變成 4、原始請求進了已處理、收件匣裡多了一張接續票。
    """
    專案 = tmp_path / "專案"
    專案.mkdir()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "狀態"))
    #  是唯一帶 REVIEW: PASS 的實錄，所以審查那階走得完。
    假, _ = 做假CLI("agy", "agy_review_pass.json")

    匣 = 收件目錄(專案)
    丟一件("做某件事\n\n<!--nova:驗收 /usr/bin/false-->", 來源=時鐘, 目錄=匣)

    碼 = 主程式(
        [
            "工作流",
            "--從收件匣",
            # **從審查階段進去**：假 CLI 只吐實錄、不寫檔，前面每一階都會被
            # 「工作區沒被動過」判成結果未知（那是對的行為，只是不該在這裡發生）。
            # 審查階段不動工作區，走得完，而收尾那一段是所有起點共用的。
            "--起點",
            "review",
            "--用",
            "agy",
            "--審查用",
            "agy",
            "--執行檔",
            str(假),
            "--工作目錄",
            str(專案),
            "--判準",
            str(翻牌判準),
            "--不記帳",
        ]
    )

    assert 碼 == 護欄碼, f"驗收紅要收在護欄碼 4，實際 {碼}"
    assert 待處理(匣), "驗收紅之後要排一張接續票回收件匣"
