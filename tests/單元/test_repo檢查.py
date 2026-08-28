"""repo 層級的三條檢查：在隔離的迷你 repo 上驗，不碰真 repo。

每個測試都有自己的 tmp_path，所以平行跑不會互相汙染。
"""

import subprocess
from pathlib import Path

import pytest

from nova.載體.機密 import 檢查機密
from nova.載體.測試數 import 檢查測試數
from nova.載體.語言 import 檢查繁體中文

預設忽略 = ".env\n.env.*\n*.key\n*.pem\n"
兩支測試 = "def test_一() -> None:\n    pass\n\n\ndef test_二() -> None:\n    pass\n"
一支測試 = "def test_一() -> None:\n    pass\n"


def _造迷你repo(根: Path, 檔案: dict[str, str], gitignore: str = 預設忽略) -> Path:
    (根 / ".gitignore").write_text(gitignore, encoding="utf-8")
    for 相對, 內容 in 檔案.items():
        路徑 = 根 / 相對
        路徑.parent.mkdir(parents=True, exist_ok=True)
        路徑.write_text(內容, encoding="utf-8")
    for 指令 in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "測試@例子"],
        ["git", "config", "user.name", "測試"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "初始"],
    ):
        subprocess.run(指令, cwd=根, check=True, capture_output=True)
    return 根


@pytest.fixture
def 迷你repo(tmp_path: Path) -> Path:
    return _造迷你repo(
        tmp_path,
        {
            "src/甲.py": "def 你好() -> None:\n    pass\n",
            "tests/test_甲.py": 兩支測試,
        },
    )


class Test繁體中文:
    def test_乾淨的repo放行(self, 迷你repo: Path) -> None:
        通過, 證據 = 檢查繁體中文(迷你repo)
        assert 通過 is True, 證據

    def test_加入簡體字要擋(self, 迷你repo: Path) -> None:
        (迷你repo / "src" / "乙.py").write_text("# 这是简体\n", encoding="utf-8")  # nova:允許非繁體
        subprocess.run(["git", "add", "-A"], cwd=迷你repo, check=True, capture_output=True)
        通過, 證據 = 檢查繁體中文(迷你repo)
        assert 通過 is False
        assert "src/乙.py" in 證據, "要指出是哪個檔案才可行動"

    def test_沒被git追蹤的檔案不掃(self, 迷你repo: Path) -> None:
        """.venv、快取這些不該被掃。用 git ls-files 當範圍，不自己維護排除表。"""
        (迷你repo / "沒加進git.py").write_text("# 这是简体\n", encoding="utf-8")  # nova:允許非繁體
        assert 檢查繁體中文(迷你repo)[0] is True


class Test機密:
    def test_乾淨的repo放行(self, 迷你repo: Path) -> None:
        通過, 證據 = 檢查機密(迷你repo)
        assert 通過 is True, 證據

    def test_gitignore沒擋env要紅(self, tmp_path: Path) -> None:
        repo = _造迷你repo(tmp_path, {"甲.py": "x = 1\n"}, gitignore="*.log\n")
        通過, 證據 = 檢查機密(repo)
        assert 通過 is False
        assert ".env" in 證據

    def test_已被追蹤的機密檔要紅(self, tmp_path: Path) -> None:
        """已追蹤的檔案寫進 .gitignore 也擋不住，所以要單獨掃一次。"""
        repo = _造迷你repo(tmp_path, {".env": "KEY=1\n"}, gitignore="*.log\n")
        通過, 證據 = 檢查機密(repo)
        assert 通過 is False
        assert ".env" in 證據


class Test測試數:
    def test_沒變放行(self, 迷你repo: Path) -> None:
        assert 檢查測試數(迷你repo)[0] is True

    def test_變多放行(self, 迷你repo: Path) -> None:
        路徑 = 迷你repo / "tests" / "test_甲.py"
        新增 = "\n\ndef test_三() -> None:\n    pass\n"
        路徑.write_text(路徑.read_text(encoding="utf-8") + 新增, encoding="utf-8")
        assert 檢查測試數(迷你repo)[0] is True

    def test_刪測試要擋(self, 迷你repo: Path) -> None:
        (迷你repo / "tests" / "test_甲.py").write_text(一支測試, encoding="utf-8")
        通過, 證據 = 檢查測試數(迷你repo)
        assert 通過 is False
        assert "2" in 證據 and "1" in 證據

    def test_搬檔案不算刪測試(self, 迷你repo: Path) -> None:
        """比對全 repo 總數，不逐檔比——逐檔比會把改名和搬移誤判成刪測試。"""
        舊 = 迷你repo / "tests" / "test_甲.py"
        內容 = 舊.read_text(encoding="utf-8")
        舊.unlink()
        (迷你repo / "tests" / "test_搬過來.py").write_text(內容, encoding="utf-8")
        assert 檢查測試數(迷你repo)[0] is True
