"""`nova 線` 的並行現況查詢：唯讀、離線、算不出來就留空。

**直接呼叫 `查並行現況`，不走命令列**：這一格只做 `線.py` 的核心邏輯，
印給人看是下一格（而且 `命令列.py` 別條線正在改，不准碰）。

底下的 `git` 子程序是**建測試資料**，不是被測對象。
唯讀那支例外：它用 PATH 裡的假 `git` **記下實際下過的每一道子命令**，
因為「有沒有偷偷 fetch」只看事後狀態是看不出來的——
本地 ref 沒變不代表沒連網，網路慢一秒也照樣是違規。
"""

import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nova.載體.線 import 查並行現況, 線現況
from nova.載體.重構護欄 import 不拍的目錄

_舊 = 1_700_000_000.0
_新 = 1_900_000_000.0
_更新 = 2_000_000_000.0

#: 這支查詢唯一准下的 git 子命令。用白名單而不是禁用清單：
#: 禁用清單漏掉一個新的寫入或連網子命令就默默放行，白名單漏掉只會讓測試紅。
_准下的子命令 = frozenset({"worktree", "rev-parse", "rev-list", "status"})


def _git(工作區: Path, *參數: str) -> str:
    結果 = subprocess.run(
        ["git", "-c", "user.name=測試", "-c", "user.email=test@example.com", *參數],
        cwd=工作區,
        capture_output=True,
        text=True,
        check=True,
    )
    return 結果.stdout


def _建主工作區(根: Path) -> Path:
    """建一個有兩個 commit、且本地已有 `origin/main` 的主工作區。"""
    專案 = 根 / "主線"
    專案.mkdir()
    _git(專案, "init", "-q", "-b", "main")
    (專案 / "README.md").write_text("第一版\n", encoding="utf-8")
    _git(專案, "add", "README.md")
    _git(專案, "commit", "-qm", "初始化")
    甲 = _git(專案, "rev-parse", "HEAD").strip()
    (專案 / "README.md").write_text("第二版\n", encoding="utf-8")
    _git(專案, "add", "README.md")
    _git(專案, "commit", "-qm", "第二筆")
    乙 = _git(專案, "rev-parse", "HEAD").strip()
    # 只寫本地 ref，不設 remote：查詢要能離線比對，也代表這份 ref 可能是舊的
    _git(專案, "update-ref", "refs/remotes/origin/main", 乙)
    _git(專案, "branch", "支線", 甲)
    return 專案


def _加一條worktree(專案: Path, 根: Path) -> Path:
    """從落後 origin/main 一個 commit 的分支開一條線，再往前疊一個 commit。"""
    工作樹 = 根 / "支線工作樹"
    _git(專案, "worktree", "add", "-q", str(工作樹), "支線")
    (工作樹 / "支線的檔.txt").write_text("支線改的\n", encoding="utf-8")
    _git(工作樹, "add", "支線的檔.txt")
    _git(工作樹, "commit", "-qm", "支線第一筆")
    return 工作樹


def _現況(現況們: tuple[線現況, ...], 路徑: Path) -> 線現況:
    return next(一條 for 一條 in 現況們 if 一條.路徑 == 路徑.resolve())


def _工作區指紋(工作區: Path) -> tuple[str, str]:
    return (
        _git(工作區, "status", "--porcelain=v1"),
        _git(工作區, "rev-parse", "HEAD"),
    )


def _裝一個會記帳的假git(記錄: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把 PATH 最前面換成一個會把 argv 記下來、再轉呼真 git 的殼。"""
    真git = shutil.which("git")
    assert 真git is not None, "測試環境沒有 git"
    殼目錄 = 記錄.parent / "假git"
    殼目錄.mkdir()
    殼 = 殼目錄 / "git"
    殼.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> {記錄}\nexec {真git} "$@"\n',
        encoding="utf-8",
    )
    殼.chmod(0o755)
    monkeypatch.setenv("PATH", f"{殼目錄}{os.pathsep}{os.environ['PATH']}")


def test_查並行現況不准動任何一條線的工作區也不准連網(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """查詢是唯讀的：工作區指紋前後一模一樣，且不下任何會寫或會連網的子命令。"""
    專案 = _建主工作區(tmp_path)
    工作樹 = _加一條worktree(專案, tmp_path)
    (工作樹 / "還沒提交.txt").write_text("髒的\n", encoding="utf-8")
    查詢前 = {路徑: _工作區指紋(路徑) for 路徑 in (專案, 工作樹)}

    記錄 = tmp_path / "下過的git.log"
    _裝一個會記帳的假git(記錄, monkeypatch)
    查並行現況(專案)

    下過的 = [行 for 行 in 記錄.read_text(encoding="utf-8").splitlines() if 行]
    assert 下過的, "假 git 一次都沒被呼叫到，這支測試等於沒驗到東西"
    for 一道 in 下過的:
        子命令 = next((詞 for 詞 in 一道.split() if not 詞.startswith("-")), "")
        assert 子命令 in _准下的子命令, f"查詢下了白名單外的子命令：{一道}"
    for 路徑, 指紋 in 查詢前.items():
        assert _工作區指紋(路徑) == 指紋, f"查詢動到了 {路徑} 的工作區"


def test_主工作區與worktree都要出現而且各自帶得出commit與落後數(
    tmp_path: Path,
) -> None:
    """主工作區不是 worktree，但它也是一條線，不准從清單裡漏掉。"""
    專案 = _建主工作區(tmp_path)
    工作樹 = _加一條worktree(專案, tmp_path)

    現況們 = 查並行現況(專案)

    assert {一條.路徑 for 一條 in 現況們} == {專案.resolve(), 工作樹.resolve()}
    主 = _現況(現況們, 專案)
    支 = _現況(現況們, 工作樹)
    assert 主.是主工作區 is True
    assert 支.是主工作區 is False
    assert 主.目前commit == _git(專案, "rev-parse", "HEAD").strip()
    assert 支.目前commit == _git(工作樹, "rev-parse", "HEAD").strip()
    # 主線就停在本地 origin/main 上；支線從落後一個的地方多疊了一個 commit
    assert (主.領先基底數, 主.落後基底數) == (0, 0)
    assert (支.領先基底數, 支.落後基底數) == (1, 1)
    assert 支.基底參照 == "origin/main"
    assert "本地" in 支.基底說明, 支.基底說明
    assert "origin/main" in 支.基底說明, 支.基底說明


def test_工作區髒不髒要帶得出未提交的檔案數(tmp_path: Path) -> None:
    """乾淨與髒是兩種狀態，而且要說得出幾個檔，不然人不知道值不值得去看。"""
    專案 = _建主工作區(tmp_path)
    工作樹 = _加一條worktree(專案, tmp_path)
    (工作樹 / "改一半.txt").write_text("半成品\n", encoding="utf-8")
    (工作樹 / "支線的檔.txt").write_text("又改了\n", encoding="utf-8")

    現況們 = 查並行現況(專案)

    assert _現況(現況們, 專案).工作區乾淨嗎 is True
    assert _現況(現況們, 專案).未提交檔案數 == 0
    assert _現況(現況們, 工作樹).工作區乾淨嗎 is False
    assert _現況(現況們, 工作樹).未提交檔案數 == 2


def test_沒有origin_main這個ref時落後數要留空不准填零(tmp_path: Path) -> None:
    """「查不到基底」跟「已經同步」是兩件事，填 0 會讓人以為不用 rebase。"""
    專案 = tmp_path / "沒有基底的線"
    專案.mkdir()
    _git(專案, "init", "-q", "-b", "main")
    (專案 / "README.md").write_text("孤島\n", encoding="utf-8")
    _git(專案, "add", "README.md")
    _git(專案, "commit", "-qm", "初始化")

    (一條,) = 查並行現況(專案)

    assert 一條.領先基底數 is None, "算不出來要留空"
    assert 一條.落後基底數 is None, "算不出來要留空"
    assert 一條.基底參照 is None
    assert "查不到" in 一條.基底說明, 一條.基底說明
    assert "origin/main" in 一條.基底說明, 一條.基底說明
    assert "0" not in 一條.基底說明, f"不准把查不到講成 0：{一條.基底說明}"


def test_最後改動時間要跳過不拍的目錄(tmp_path: Path) -> None:
    """`.git`／`.venv`／`__pycache__` 底下的產物不是人改的，不准拿來當最後改動時間。"""
    專案 = _建主工作區(tmp_path)
    os.utime(專案 / "README.md", (_舊, _舊))
    人改的 = 專案 / "我剛改的.txt"
    人改的.write_text("最新的人為改動\n", encoding="utf-8")
    os.utime(人改的, (_新, _新))
    for 目錄名 in 不拍的目錄:
        目錄 = 專案 / 目錄名
        目錄.mkdir(exist_ok=True)
        工具產物 = 目錄 / "工具產的.txt"
        工具產物.write_text("工具寫的，不算人改的\n", encoding="utf-8")
        os.utime(工具產物, (_更新, _更新))

    (一條,) = 查並行現況(專案)

    assert 一條.最後改動時間 == datetime.fromtimestamp(_新, tz=UTC)
