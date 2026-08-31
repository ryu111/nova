"""成果帳上的 `rollback_point`：這次工作是從哪個 commit 起跑的。

**會 fork 子程序（真的叫 git），所以住整合層不住單元層**——
`tests/單元` 是提交閘唯一的測試規則，混一支 fork 進去就是每次 commit 都付那個錢。
"""

import subprocess
from pathlib import Path

from nova.載體.git查詢 import 目前commit


def _建一個repo(在: Path) -> str:
    """建一個只有一筆 commit 的 repo，回傳那筆的 sha。"""
    跑 = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run([*跑, "init", "-q"], cwd=在, check=True)
    (在 / "甲.txt").write_text("內容", encoding="utf-8")
    subprocess.run([*跑, "add", "."], cwd=在, check=True)
    subprocess.run([*跑, "commit", "-qm", "第一筆"], cwd=在, check=True)
    出 = subprocess.run(
        [*跑, "rev-parse", "HEAD"], cwd=在, capture_output=True, text=True, check=True
    )
    return 出.stdout.strip()


def test_回得出HEAD的完整sha(tmp_path: Path) -> None:
    """短 sha 不行：repo 長大之後短 sha 會撞，而帳是要留很久的。"""
    預期 = _建一個repo(tmp_path)
    assert 目前commit(tmp_path) == 預期
    assert len(預期) == 40


def test_不是git就回None(tmp_path: Path) -> None:
    """**不准回空字串**。空字串跟「這裡不是 repo」長得一樣，

    而那正是要分開的兩件事——nova 在別人的目錄裡跑得起來，
    那時候「該退回哪個 commit」根本不成立，不是「答案是空的」。
    """
    assert 目前commit(tmp_path) is None
