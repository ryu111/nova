"""`gh pr merge` 回 0 不等於收尾成功：本地分支還在就是沒收乾淨。

`gh pr merge --delete-branch` 只保證得了 GitHub 那一端。本地那條 head branch
只要還被某棵 worktree 佔著，gh 刪不掉它卻照樣回 0——收尾如果直接把那個 0
當成整體結果，就會留下「PR 顯示已合併、機器上分支還在」的假綠，
而下一次扇出撞到「這個分支已經被別的 worktree 佔用」時，沒有人講得出它是哪一票留的。

這裡只讓暫存目錄裡的假 `git` 與假 `gh` 收到指令；任何測試都不碰真的遠端。
假 `gh` 一律回 0（含 `pr merge`），假 `git branch --list` 一律回報分支還在——
這就是要被抓出來的那個現場。
"""

import os
import stat
import sys
from pathlib import Path

import pytest

from nova.契約.退出碼 import 放行, 閘紅
from nova.載體.命令 import 收 as 收命令
from nova.載體.命令列 import 主程式
from tests.整合.test_收尾紅線 import _收尾參數, _斷言有指令, _讀呼叫

分支名 = "收-04-還沒刪掉的分支"


def _造假git與gh_分支刪不掉(專案: Path, 測具: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """造出「GitHub 合併了、本地分支沒刪掉」的假 CLI，並記下每一道 argv。

    合併後查證要問的那幾件事都給得出答案（PR 已 merged、有 mergeCommit、
    工作樹清單只剩主工作樹、工作樹是乾淨的），只有 `git branch --list`
    刻意回報分支還在——這樣測試紅的時候，紅的原因只會是「沒查本地分支」。
    """
    專案.mkdir()
    執行檔目錄 = 測具 / "假執行檔"
    執行檔目錄.mkdir(parents=True)
    紀錄 = 測具 / "收尾指令.jsonl"
    原文 = f"""#!{sys.executable}
import json
import os
import pathlib
import sys
名稱 = pathlib.Path(sys.argv[0]).name
參數 = sys.argv[1:]
分支 = os.environ['NOVA_收尾分支']
with pathlib.Path(os.environ['NOVA_收尾紀錄']).open('a', encoding='utf-8') as 檔:
    json.dump({{'程式': 名稱, 'argv': 參數}}, 檔, ensure_ascii=False)
    檔.write("\\n")
if 名稱 == 'git' and 參數[:1] == ['symbolic-ref']:
    print(分支)
elif 名稱 == 'git' and 參數[:2] == ['branch', '--show-current']:
    print(分支)
elif 名稱 == 'git' and 參數[:2] == ['branch', '--list']:
    print("  " + 分支)
elif 名稱 == 'git' and 參數[:1] == ['worktree']:
    print("worktree " + os.environ['NOVA_收尾專案'])
    print("HEAD 1111111111111111111111111111111111111111")
    print("branch refs/heads/main")
elif 名稱 == 'git' and 參數[:1] == ['rev-parse']:
    print("1111111111111111111111111111111111111111")
elif 名稱 == 'gh' and 參數[:2] == ['pr', 'view']:
    print(json.dumps({{
        'state': 'MERGED',
        'headRefName': 分支,
        'mergeCommit': {{'oid': '2222222222222222222222222222222222222222'}},
    }}))
elif 名稱 == 'gh' and 參數[:2] == ['pr', 'merge']:
    print("✓ Squashed and merged pull request")
sys.exit(0)
"""
    for 名稱 in ("git", "gh"):
        路徑 = 執行檔目錄 / 名稱
        路徑.write_text(原文, encoding="utf-8")
        路徑.chmod(路徑.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("NOVA_收尾紀錄", str(紀錄))
    monkeypatch.setenv("NOVA_收尾分支", 分支名)
    monkeypatch.setenv("NOVA_收尾專案", str(專案))
    monkeypatch.setenv("PATH", os.pathsep.join((str(執行檔目錄), os.environ.get("PATH", ""))))
    return 紀錄


def test_gh回零但本地分支還在要回一並且指名那條分支(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """假 `gh pr merge` 回 0、本地分支仍在時，收尾必須回 1 並講出是哪條分支沒刪掉。

    三件事一起守：
    1. 退出碼不准是 0——`gh` 的 0 只代表 GitHub 那端，不是完整成功的充分條件。
    2. 真的去問過 `git branch --list`——沒問過就宣告成功等於把查證省掉。
    3. 訊息要分得出「GitHub 合併了」與「本地分支沒刪乾淨」，
       不然人看到紅只會以為合併失敗，跑去重按一次 merge。
    """
    專案 = tmp_path / "專案"
    紀錄 = _造假git與gh_分支刪不掉(專案, tmp_path / "測具", monkeypatch)
    monkeypatch.setattr(收命令, "_收尾閘", lambda *_: 放行)

    碼 = 主程式(_收尾參數(專案))

    輸出 = capsys.readouterr()
    訊息 = 輸出.out + 輸出.err
    assert 碼 == 閘紅, f"gh 回 0 但本地分支還在，收尾卻回 {碼}：這就是假綠"
    呼叫紀錄 = _讀呼叫(紀錄)
    _斷言有指令(呼叫紀錄, "gh", "pr", "merge")
    _斷言有指令(呼叫紀錄, "git", "branch", "--list")
    assert 分支名 in 訊息, f"沒指名是哪條分支沒刪掉：{訊息!r}"
    assert "本地分支" in 訊息, f"沒把「GitHub 合併了」跟「本地分支沒刪乾淨」分開講：{訊息!r}"
