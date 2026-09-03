"""`nova 收` 的遠端副作用紅線。

這裡只讓暫存目錄裡的假 `git` 與假 `gh` 收到指令；任何測試都不碰真的遠端。
"""

import json
import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from nova.契約.檢查結果 import 檢查結果
from nova.契約.退出碼 import 放行, 未知, 閘紅
from nova.載體.命令 import 收 as 命令列
from nova.載體.命令列 import 主程式

#: 假 git 在「拓撲問不出來」模式下吐的那句話。真的 git 這時吐的是英文 fatal，
#: 這裡換成一句認得出來的字：要釘的是**這句話有沒有被原樣端到人面前**。
問不出拓撲時git的抱怨 = "fatal: 假 git 今天答不出 worktree list"


def _造假git與gh(專案: Path, 測具: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """在專案外造會記錄 argv 的假 `git` 與假 `gh`。"""
    專案.mkdir()
    執行檔目錄 = 測具 / "假執行檔"
    執行檔目錄.mkdir(parents=True)
    紀錄 = 測具 / "收尾指令.jsonl"
    # 30 秒遠超測試的 0.05 秒，是逾時保護失效時的保險絲。
    原文 = f"""#!{sys.executable}
import json
import os
import pathlib
import sys
import time
路徑 = pathlib.Path(os.environ['NOVA_收尾紀錄'])
with 路徑.open('a', encoding='utf-8') as 檔:
    資料 = {{'程式': pathlib.Path(sys.argv[0]).name, 'argv': sys.argv[1:]}}
    json.dump(資料, 檔, ensure_ascii=False)
    檔.write("\\n")
# 派工開的樹掛在一條分支上，假 git 也要照著答——`收` 要靠它組出完整 refspec。
# 比對**前綴**：`--short HEAD` 與 `-q --short HEAD` 兩種寫法都要答得出來，
# 否則旗標一改這裡就靜靜地答不出分支，紅的原因就不是這幾支要測的那件事。
if pathlib.Path(sys.argv[0]).name == 'git' and sys.argv[1:2] == ['symbolic-ref']:
    print('nova/20260101T000000Z-abc123')
# 拓撲也要答得出來：`收` 在第一個 git 寫入之前會問「這棵樹的主工作區在哪」，
# 答不出來就當場停（那時 commit／push 一道都還沒發）。這幾支測的是別的紅線，
# 所以這裡照實答「這就是主工作區」，讓它們走主工作區那條路。
if pathlib.Path(sys.argv[0]).name == 'git' and sys.argv[1:2] == ['worktree']:
    # 開關擺在環境變數上，這樣「拓撲問不出來」那一支跟其餘幾支共用同一個假 git。
    if os.environ.get('NOVA_收尾拓撲') == '問不出':
        sys.stderr.write({問不出拓撲時git的抱怨!r} + '\\n')
        sys.exit(128)
    print('worktree ' + os.environ['NOVA_收尾專案'])
    print('branch refs/heads/main')
# `收` 在 push 之前會先問兩件事：這棵樹乾不乾淨、origin 上那條分支長什麼樣。
# 這幾支釘的是「完整那條路上不准出現什麼」，所以這裡照最單純的那一列答：
# 樹是髒的（有東西要提交）、origin 上還沒有這條分支（＝真的新分支，該推）。
if pathlib.Path(sys.argv[0]).name == 'git' and sys.argv[1:3] == ['status', '--porcelain']:
    print(' M 這一趟要提交的東西.txt')
# 遠端沒有這條分支時，真的 git 的 `fetch <不存在的 ref>` 回 128；後面那道
# `ls-remote` 印空才是「遠端真的沒有」的證據。兩道分開答，不讓「fetch 掛了」
# 跟「遠端沒有」在測具裡糊成同一種答案。
if pathlib.Path(sys.argv[0]).name == 'git' and sys.argv[1:2] == ['fetch']:
    sys.stderr.write("fatal: couldn't find remote ref\\n")
    sys.exit(128)
if pathlib.Path(sys.argv[0]).name == 'git' and sys.argv[1:2] == ['ls-remote']:
    sys.exit(0)
# 「這條分支上有沒有 PR」是用查的，不是拿 `gh pr create` 撞出來的：預設答**空清單**
# ＝沒有 PR，這幾支才走得到既有那條「建 PR → 等 CI → 合併」的路。空 stdout 不是
# 「沒有 PR」——那是「不知道」，`收` 會停在 3，紅的原因就不是這幾支要測的事。
if pathlib.Path(sys.argv[0]).name == 'gh' and sys.argv[1:3] == ['pr', 'list']:
    print('[]')
if pathlib.Path(sys.argv[0]).name == 'gh' and sys.argv[1:3] == ['pr', 'checks']:
    模式 = os.environ.get('NOVA_收尾CI', '')
    if 模式 == '紅':
        sys.exit(1)
    if 模式 == '逾時':
        time.sleep(30)
"""
    for 名稱 in ("git", "gh"):
        路徑 = 執行檔目錄 / 名稱
        路徑.write_text(原文, encoding="utf-8")
        路徑.chmod(路徑.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("NOVA_收尾紀錄", str(紀錄))
    monkeypatch.setenv("NOVA_收尾專案", str(專案))
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join((str(執行檔目錄), os.environ.get("PATH", ""))),
    )
    return 紀錄


def _準備收尾(暫存根: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """建立專案與專案外的假 CLI 測具。"""
    專案 = 暫存根 / "專案"
    紀錄 = _造假git與gh(專案, 暫存根 / "測具", monkeypatch)
    return 專案, 紀錄


def _收尾參數(專案: Path) -> list[str]:
    """回傳所有收尾指令共用的 CLI 參數。"""
    return [
        "收",
        "--工作目錄",
        str(專案),
        "--不記帳",
        "--訊息",
        "測試收尾",
    ]


def _讀呼叫(紀錄: Path) -> list[tuple[str, list[str]]]:
    """把假 CLI 的 JSONL 紀錄還原成（程式名、argv）。"""
    if not 紀錄.exists():
        return []
    呼叫紀錄: list[tuple[str, list[str]]] = []
    for 行 in 紀錄.read_text(encoding="utf-8").splitlines():
        資料 = cast(dict[str, object], json.loads(行))
        參數 = [str(值) for 值 in cast(list[object], 資料["argv"])]
        呼叫紀錄.append((str(資料["程式"]), 參數))
    return 呼叫紀錄


def _斷言有指令(呼叫紀錄: list[tuple[str, list[str]]], 程式: str, *開頭: str) -> list[str]:
    """斷言有一個以指定參數開頭的假 CLI 呼叫，並回傳其 argv。"""
    for 名稱, 參數 in 呼叫紀錄:
        if 名稱 == 程式 and 參數[: len(開頭)] == list(開頭):
            return 參數
    訊息 = f"找不到 {程式} {' '.join(開頭)}：{呼叫紀錄}"
    raise AssertionError(訊息)


def _斷言沒有指令(呼叫紀錄: list[tuple[str, list[str]]], 程式: str, *開頭: str) -> None:
    """斷言沒有以指定參數開頭的假 CLI 呼叫。"""
    assert not any(名稱 == 程式 and 參數[: len(開頭)] == list(開頭) for 名稱, 參數 in 呼叫紀錄), (
        f"不應有 {程式} {' '.join(開頭)}：{呼叫紀錄}"
    )


def _檔案快照(專案: Path) -> dict[Path, bytes]:
    """取得專案目錄內所有檔案的內容快照。"""
    return {路徑.relative_to(專案): 路徑.read_bytes() for 路徑 in 專案.rglob("*") if 路徑.is_file()}


@pytest.fixture
def 閘放行(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """回傳把閘設成放行的設定函式。"""

    def 設定() -> None:
        monkeypatch.setattr(命令列, "_收尾閘", lambda *_: 放行)

    return 設定


class Test收尾紅線:
    def test_提交指令不准帶繞過驗證旗標(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        閘放行: Callable[[], None],
    ) -> None:
        """收尾組出的 commit 不得關掉 hooks。"""
        專案, 紀錄 = _準備收尾(tmp_path, monkeypatch)
        閘放行()

        assert 主程式(_收尾參數(專案)) == 放行

        提交 = _斷言有指令(_讀呼叫(紀錄), "git", "commit")
        assert "--no-verify" not in 提交

    def test_合併指令不准帶管理員旗標(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        閘放行: Callable[[], None],
    ) -> None:
        """收尾不得用管理員權限繞過 required checks。"""
        專案, 紀錄 = _準備收尾(tmp_path, monkeypatch)
        閘放行()

        assert 主程式(_收尾參數(專案)) == 放行

        合併 = _斷言有指令(_讀呼叫(紀錄), "gh", "pr", "merge")
        assert "--admin" not in 合併

    def test_合併指令一定帶刪除分支旗標(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        閘放行: Callable[[], None],
    ) -> None:
        """合併成功後必須把遠端分支一起收掉。"""
        專案, 紀錄 = _準備收尾(tmp_path, monkeypatch)
        閘放行()

        assert 主程式(_收尾參數(專案)) == 放行

        合併 = _斷言有指令(_讀呼叫(紀錄), "gh", "pr", "merge")
        assert "--delete-branch" in 合併

    def test_主工作區那條路收完不准去收樹(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        閘放行: Callable[[], None],
    ) -> None:
        """`收` 跑在主工作區裡（根 == 主工作區）時，收完不准跑 `git worktree remove`。

        「收 0 要把樹收掉」只適用於派工樹。同一段收場沒有分辨主工作區就照收，收掉的
        會是人正在裡面工作的那棵樹——`git worktree remove` 對主工作區其實會被 git 擋
        下來，但那是 git 幫的忙，不是這個程式的判斷；而在假 CLI 之下（測試裡）以及任
        何未來改用別的收法的寫法之下，這一步就是靜靜地把現場毀掉。

        所以派工樹那條路的每一道收場動作，這裡都要反著釘一次：`worktree remove` 一道
        都不准發、stdout 不准出現「樹已收掉」那句只屬於派工樹的話，退出碼照舊是 0。
        """
        專案, 紀錄 = _準備收尾(tmp_path, monkeypatch)
        閘放行()

        assert 主程式(_收尾參數(專案)) == 放行

        呼叫紀錄 = _讀呼叫(紀錄)
        _斷言有指令(呼叫紀錄, "gh", "pr", "merge")
        _斷言沒有指令(呼叫紀錄, "git", "worktree", "remove")
        _斷言沒有指令(呼叫紀錄, "git", "branch", "-D")
        assert "樹已收掉" not in capsys.readouterr().out, (
            "主工作區那條路報了一句只屬於派工樹的收場，人會以為自己的工作區被收掉了"
        )

    def test_問不出主工作區時連一個git寫入都不准發生(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        閘放行: Callable[[], None],
    ) -> None:
        """`worktree list` 答不出來 → 停在 1，而且 commit／push／merge 一道都沒發。

        「這棵樹是不是派工樹」決定了後面兩件事：`gh pr merge` 帶不帶
        `--delete-branch`、收完要不要把樹收掉。問不出來還往下走，等於拿一個猜的
        拓撲去 merge——猜錯的下場是 `--delete-branch` 先 `git checkout <base>`，
        而 base 被主工作區佔著，那道 checkout 回 128 是在 **merge 已經做完之後**
        才發生的：PR 合併了、退出碼 1、樹與分支照樣留著（`docs/負控紀錄/0010`）。

        所以拓撲要在**第一個 git 寫入之前**問。這一支釘的就是那個順序：紅的時候
        現場乾淨得可以整趟重跑，不必有人去 GitHub 上收拾一個已經合併的 PR。

        `git fetch` 也算在「一道都不准發」裡：它是 push 之前問遠端的那一道，只准排在
        拓撲問清楚之後。順序倒過來的話，拓撲都還沒問，本地就已經多了一份
        `refs/remotes/origin/<分支>`，而人以為現場一動也沒動。
        """
        專案, 紀錄 = _準備收尾(tmp_path, monkeypatch)
        monkeypatch.setenv("NOVA_收尾拓撲", "問不出")
        閘放行()

        assert 主程式(_收尾參數(專案)) == 閘紅

        呼叫紀錄 = _讀呼叫(紀錄)
        _斷言有指令(呼叫紀錄, "git", "worktree", "list")
        _斷言沒有指令(呼叫紀錄, "git", "commit")
        _斷言沒有指令(呼叫紀錄, "git", "fetch")
        _斷言沒有指令(呼叫紀錄, "git", "push")
        _斷言沒有指令(呼叫紀錄, "gh", "pr", "list")
        _斷言沒有指令(呼叫紀錄, "gh", "pr", "create")
        _斷言沒有指令(呼叫紀錄, "gh", "pr", "merge")
        錯誤 = capsys.readouterr().err
        assert "主工作區" in 錯誤, f"沒講清楚是「問不出主工作區」停下來的：{錯誤!r}"
        assert 問不出拓撲時git的抱怨 in 錯誤, f"git 自己的抱怨沒端出來，人查不下去：{錯誤!r}"

    def test_CI紅時不會組出合併指令(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        閘放行: Callable[[], None],
    ) -> None:
        """required CI 非零時只能回報紅，不能再組出 merge。"""
        專案, 紀錄 = _準備收尾(tmp_path, monkeypatch)
        monkeypatch.setenv("NOVA_收尾CI", "紅")
        閘放行()

        assert 主程式(_收尾參數(專案)) == 閘紅

        呼叫紀錄 = _讀呼叫(紀錄)
        _斷言有指令(呼叫紀錄, "gh", "pr", "checks")
        _斷言沒有指令(呼叫紀錄, "gh", "pr", "merge")

    def test_閘紅時後續提交推送開PR都不發生(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """閘是紅的時候，commit、問遠端、push、開 PR 一道都不得啟動。

        斷言是「紀錄整份是空的」，所以問遠端那幾道（`git fetch`、`gh pr list`）
        天生也被它蓋住：閘紅時連「先問清楚遠端」都不准開始。
        """
        專案, 紀錄 = _準備收尾(tmp_path, monkeypatch)
        monkeypatch.setattr(命令列, "_收尾閘", lambda *_: 閘紅)

        assert 主程式(_收尾參數(專案)) == 閘紅

        assert _讀呼叫(紀錄) == []

    def test_等不到CI回結果未知三(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        閘放行: Callable[[], None],
    ) -> None:
        """CI 等不到結果不是確定失敗，退出碼必須是 3 且不得合併。"""
        專案, 紀錄 = _準備收尾(tmp_path, monkeypatch)
        monkeypatch.setenv("NOVA_收尾CI", "逾時")
        閘放行()

        assert 主程式([*_收尾參數(專案), "--等CI秒", "0.05"]) == 未知

        呼叫紀錄 = _讀呼叫(紀錄)
        _斷言有指令(呼叫紀錄, "gh", "pr", "checks")
        _斷言沒有指令(呼叫紀錄, "gh", "pr", "merge")

    def test_閘紅時只跑閘不修改任何檔案(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """閘紅只回報，不得自行改檔把閘修綠。"""
        專案, 紀錄 = _準備收尾(tmp_path, monkeypatch)
        (專案 / "待修檔案.txt").write_text("閘紅時保留原樣\n", encoding="utf-8")
        原快照 = _檔案快照(專案)
        閘有跑 = False

        def 假閘(*_: object, **__: object) -> list[檢查結果]:
            nonlocal 閘有跑
            閘有跑 = True
            return [檢查結果("測試閘紅", "測試用紅閘", False, "測試", "故意讓閘紅")]

        monkeypatch.setattr(命令列, "跑閘", 假閘)

        assert 主程式(_收尾參數(專案)) == 閘紅
        assert 閘有跑
        assert _檔案快照(專案) == 原快照
        assert _讀呼叫(紀錄) == []
