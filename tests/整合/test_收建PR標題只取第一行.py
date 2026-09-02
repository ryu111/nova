"""守住 `收` 依 git 訊息結構建立 PR，並在標題超長時及早停止。"""

from collections.abc import Callable
from pathlib import Path

import pytest

from nova.契約.退出碼 import 放行, 閘紅
from nova.載體.命令列 import 主程式
from nova.載體.工作樹 import 開一個工作樹
from tests.整合.test_收推派工開的分支 import (
    _讀呼叫,
    _跑git,
    _造假gh與記錄用git,
    _造專案與origin,
    分支名,
)
from tests.整合.test_收推派工開的分支 import 閘放行 as 閘放行  # noqa: PLC0414 —— 借那支的 fixture

#: GitHub 的 PR 標題上限，`createPullRequest` 超過就回 GraphQL 錯。
標題上限 = 256


def _收尾參數(工作目錄: Path, 訊息: str) -> list[str]:
    return ["收", "--工作目錄", str(工作目錄), "--不記帳", "--訊息", 訊息]


def _開一棵派工形狀的樹(tmp_path: Path) -> tuple[Path, Path]:
    """造好 origin 與專案，開一棵派工形狀的樹並在裡面留一份未提交的產出。"""
    專案, _origin, 起點commit = _造專案與origin(tmp_path)
    樹 = 開一個工作樹(
        專案,
        落點=tmp_path / f"nova-wt-{分支名.rsplit('/', maxsplit=1)[-1]}",
        起點commit=起點commit,
        分支=分支名,
    )
    (樹 / "分支的產出.txt").write_text("這一條線做完的事\n", encoding="utf-8")
    return 專案, 樹


def _那次PR建立(紀錄: Path) -> list[str] | None:
    for 名稱, 參數 in _讀呼叫(紀錄):
        if 名稱 == "gh" and 參數[:2] == ["pr", "create"]:
            return 參數
    return None


def _旗標後面那個(參數: list[str], 旗標: str) -> str:
    assert 旗標 in 參數, f"`gh pr create` 沒帶 {旗標}：{參數}"
    位置 = 參數.index(旗標)
    assert 位置 + 1 < len(參數), f"{旗標} 是最後一個 argv，後面沒有值：{參數}"
    return 參數[位置 + 1]


def _提交過的訊息(紀錄: Path) -> list[str]:
    return [
        參數[參數.index("-m") + 1]
        for 名稱, 參數 in _讀呼叫(紀錄)
        if 名稱 == "git" and 參數[:1] == ["commit"] and "-m" in 參數
    ]


def test_多行訊息建PR時標題是第一行本文是其餘(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    閘放行: Callable[[], None],
) -> None:
    """守住恰好 256 字的第一行成為 PR 標題，其餘內容成為不重複標題的本文。"""
    _專案, 樹 = _開一棵派工形狀的樹(tmp_path)
    紀錄 = _造假gh與記錄用git(tmp_path / "測具", monkeypatch)
    標題本文 = "長" * 標題上限
    第一行 = f"  {標題本文} \t"
    本文 = "  負控：把 --title 換回整段訊息，這一支要紅。"
    訊息 = f"{第一行}\n \t\n{本文}"
    閘放行()

    碼 = 主程式(_收尾參數(樹, 訊息))

    輸出 = capsys.readouterr()
    assert 碼 == 放行, f"閘綠、push 成功，這一趟該收 0：收到 {碼}\n{輸出.out}\n{輸出.err}"
    建PR = _那次PR建立(紀錄)
    assert 建PR is not None, f"`gh pr create` 根本沒被呼叫：{_讀呼叫(紀錄)}"

    標題 = _旗標後面那個(建PR, "--title")
    assert 標題 == 標題本文, (
        "PR 標題不是訊息第一行 strip 之後的樣子——整段多行訊息當標題就是撞 GitHub 256 "
        f"上限的那一格，尾巴留空白則是進了 PR 頁就看得到的髒標題：{標題!r}"
    )
    本體 = _旗標後面那個(建PR, "--body")
    assert 標題本文 not in 本體, f"PR 本文把標題那一行又抄了一遍，訊息沒被真的切成兩半：{本體!r}"
    # 比的是**原樣相等**，不是 strip 過的相等：標題與本文之間那個空行是 git 慣例的
    # 分隔符，不是本文的一部分。用 `本體.strip() == 本文` 比的話，「第一行切掉了但
    # 開頭空行沒去掉」（`本文 = 其餘`）照樣全綠，而 PR 內文會從一個空行開始。
    assert 本體 == 本文, f"PR 本文不是第一行之後那一段（開頭空行要去掉）：{本體!r}"

    # commit 收的是**原樣全文**（含第一行前後那點空白）：切訊息是給 PR 用的，
    # 不准回頭去動那份要進 git 歷史的訊息。
    assert _提交過的訊息(紀錄) == [訊息], (
        f"commit 訊息被一起切掉了：標題與本文都該原樣留在 git 歷史裡：{_提交過的訊息(紀錄)}"
    )


def test_第一行超過256字元在閘就擋(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    閘放行: Callable[[], None],
) -> None:
    """守住超過 256 字的 PR 標題在 commit、push 與建 PR 前回閘紅並說明上限。"""
    _專案, 樹 = _開一棵派工形狀的樹(tmp_path)
    起點commit = _跑git(樹, "rev-parse", "HEAD").stdout.strip()
    紀錄 = _造假gh與記錄用git(tmp_path / "測具", monkeypatch)
    第一行 = "長" * (標題上限 + 1)
    訊息 = f"{第一行}\n\n負控：這段本文不該有機會被送出去。"
    閘放行()

    碼 = 主程式(_收尾參數(樹, 訊息))

    輸出 = capsys.readouterr()
    說了什麼 = 輸出.out + 輸出.err
    assert 碼 == 閘紅, f"第一行 {len(第一行)} 字，超過 GitHub 的 {標題上限} 上限，不准回 {碼}"
    assert "標題" in 說了什麼, f"沒說是標題太長，人只會看到一句沒頭沒尾的失敗：{說了什麼!r}"
    assert str(標題上限) in 說了什麼, (
        f"沒把 {標題上限} 這個數字講出來，人不知道要砍到多短：{說了什麼!r}"
    )
    assert _那次PR建立(紀錄) is None, f"標題都太長了還去建 PR：{_那次PR建立(紀錄)}"
    assert _提交過的訊息(紀錄) == [], (
        f"擋在 commit 之後就等於留了一個做了一半的現場：{_提交過的訊息(紀錄)}"
    )
    assert _跑git(樹, "rev-parse", "HEAD").stdout.strip() == 起點commit, (
        "HEAD 動過了：這一趟該在任何 git 寫入之前就停住"
    )
    現場 = [條目 for 條目 in _跑git(樹, "status", "--porcelain", "-z").stdout.split("\0") if 條目]
    assert 現場 == ["?? 分支的產出.txt"], f"現場被動過了，人改完標題不能原地再跑一次：{現場}"
