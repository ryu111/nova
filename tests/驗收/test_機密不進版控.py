"""機密不進 git —— 這條保證的可執行版本。

`.gitignore` 寫了什麼不等於 git 真的會忽略（順序、否定規則、已被追蹤的檔案都會翻盤）。
這支測試直接問 git 本人，並且掃一遍「已經被追蹤的檔案」。
"""

import subprocess
from pathlib import Path

import pytest

必須被忽略 = [".env", ".env.local", ".env.production", "api.key", "server.pem"]
機密特徵 = [".env", ".key", ".pem", ".p12", "credentials.json"]


def _是_git_repo(根: Path) -> bool:
    return (根 / ".git").exists()


def test_gitignore_列出機密樣式(專案根: Path) -> None:
    """沒有 git 也要成立的最低要求：樣式有寫進去。"""
    內容 = (專案根 / ".gitignore").read_text(encoding="utf-8")
    for 樣式 in [".env", "*.key", "*.pem", "secrets/"]:
        assert 樣式 in 內容, f".gitignore 沒有忽略 {樣式}"


@pytest.mark.parametrize("檔名", 必須被忽略)
def test_git_本人確認會忽略(專案根: Path, 檔名: str) -> None:
    """問 git：這個路徑你會不會忽略？回 0 才算會。"""
    if not _是_git_repo(專案根):
        pytest.skip("尚未 git init")
    結果 = subprocess.run(["git", "check-ignore", "-q", 檔名], cwd=專案根, check=False)
    assert 結果.returncode == 0, f"git 不會忽略 {檔名}"


def test_沒有機密檔案已經被追蹤(專案根: Path) -> None:
    """已被追蹤的檔案，寫進 .gitignore 也擋不住——所以要單獨掃一次。"""
    if not _是_git_repo(專案根):
        pytest.skip("尚未 git init")
    輸出 = subprocess.run(
        ["git", "ls-files"], cwd=專案根, capture_output=True, text=True, check=True
    ).stdout
    命中 = [
        路徑
        for 路徑 in 輸出.splitlines()
        if any(特徵 in Path(路徑).name for 特徵 in 機密特徵) and not 路徑.endswith(".env.example")
    ]
    assert not 命中, f"這些機密檔案已經被 git 追蹤：{命中}"
