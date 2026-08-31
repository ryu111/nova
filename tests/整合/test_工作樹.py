"""工作樹隔離：並行的分支各自在自己的 git worktree 裡跑，互相看不到。

住整合層不住單元層：這裡真的會 fork git，開一個 worktree 是檔案系統操作。

這一支釘的是最核心的形狀——**開在指定的 commit 上、detached、不影響主工作區**。
起點是 commit 不是 HEAD，這樣它跟成果帳的 `rollback_point` 是同一個值；
分支跑完要回頭看「它從哪裡長出來的」時，兩邊對得起來。
"""

import subprocess
from pathlib import Path

import pytest

from nova.載體 import 工作樹 as 工作樹模組
from nova.載體.工作樹 import 收掉工作樹, 收集證據, 開一個工作樹


def _跑(根: Path, *參數: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *參數], cwd=根, capture_output=True, text=True, check=False)


def _造有兩個commit的repo(根: Path) -> str:
    """造一個 repo：第一版 → 第二版。回傳**第一版**的完整 sha。

    刻意讓 HEAD 停在第二版：起點若被實作寫死成 HEAD，測試會當場看到第二版的內容。
    """
    for 指令 in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "測試@例子"),
        ("config", "user.name", "測試"),
    ):
        assert _跑(根, *指令).returncode == 0

    (根 / "共用.txt").write_text("第一版\n", encoding="utf-8")
    assert _跑(根, "add", "-A").returncode == 0
    assert _跑(根, "commit", "-q", "-m", "第一版").returncode == 0
    起點 = _跑(根, "rev-parse", "HEAD").stdout.strip()

    (根 / "共用.txt").write_text("第二版\n", encoding="utf-8")
    assert _跑(根, "add", "-A").returncode == 0
    assert _跑(根, "commit", "-q", "-m", "第二版").returncode == 0
    return 起點


def test_開一個工作樹_停在起點commit且不動主工作區(tmp_path: Path) -> None:
    """開出來的工作樹是起點 commit 那一版、是 detached、而且寫它不會弄髒主工作區。"""
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造有兩個commit的repo(專案)
    落點 = tmp_path / "工作樹" / "分支甲"

    回傳 = 開一個工作樹(專案, 落點=落點, 起點commit=起點commit)

    assert 回傳 == 落點, "要回傳落點本身，呼叫端才知道那個分支該在哪裡跑"
    assert (落點 / "共用.txt").read_text(encoding="utf-8") == "第一版\n", (
        "工作樹要停在指定的起點 commit，不是 HEAD——起點跟成果帳的 rollback_point 是同一個值"
    )
    assert _跑(落點, "rev-parse", "HEAD").stdout.strip() == 起點commit

    # detached：不准建分支。有分支名就會撞到「這個分支已經被別的 worktree 佔用」。
    assert _跑(落點, "symbolic-ref", "-q", "HEAD").returncode != 0, (
        "工作樹必須是 detached HEAD，不准建分支"
    )

    # 隔離：在工作樹裡寫的東西，主工作區看不到。
    (落點 / "只有分支甲看得到.txt").write_text("甲的產出\n", encoding="utf-8")
    assert not (專案 / "只有分支甲看得到.txt").exists(), "工作樹的產出漏回主工作區了，等於沒隔離"
    assert (專案 / "共用.txt").read_text(encoding="utf-8") == "第二版\n", "主工作區被工作樹動到了"


def test_開工作樹一定要把detach參數交給git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """只看「結果是 detached」釘不住 `--detach`：傳完整 sha 時，拿掉它 git 照樣 detached。

    差別在省略 commit-ish 或給的是分支名的時候——那時 git 會自己建分支，
    就撞回「這個分支已經被別的 worktree 佔用」。所以直接釘參數本身。
    記錄器仍然委派給真的 git：這支測的是實作怎麼叫 git，不是拿假 git 自問自答。
    """
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造有兩個commit的repo(專案)
    真的跑git = 工作樹模組.跑git
    記錄: list[tuple[str, ...]] = []

    def 記錄器(根目錄: Path, *參數: str) -> subprocess.CompletedProcess[str]:
        記錄.append(參數)
        return 真的跑git(根目錄, *參數)

    monkeypatch.setattr(工作樹模組, "跑git", 記錄器)

    落點 = tmp_path / "工作樹" / "分支己"

    開一個工作樹(專案, 落點=落點, 起點commit=起點commit)

    assert ("worktree", "add", "--detach", str(落點), 起點commit) in 記錄, (
        f"沒有把 `--detach` 交給 git，工作樹會被建成有名字的分支：{記錄}"
    )


def test_開不出工作樹就raise_不准退回主工作區(tmp_path: Path) -> None:
    """起點指不到 commit 時要當場 raise。把這個拒絕改成 fallback，這支就紅。"""
    專案 = tmp_path / "專案"
    專案.mkdir()
    _造有兩個commit的repo(專案)
    落點 = tmp_path / "工作樹" / "開不起來"

    with pytest.raises(OSError, match="開不出工作樹"):
        開一個工作樹(專案, 落點=落點, 起點commit="不存在的commit")

    assert not 落點.exists(), "開不出來就不該留下半個工作樹"
    # 靜默 fallback 成共用主工作區是假隔離，比沒隔離更糟——它看起來像有。
    assert not (專案 / "工作樹").exists()


def test_主工作區沒提交的檔案在工作樹裡看不到(tmp_path: Path) -> None:
    """這是隔離在做事，不是 bug：分支只看得到已提交的狀態。

    釘住它是因為「任務依賴未提交的檔案」會神祕失敗，要讓人一眼看到原因。
    """
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造有兩個commit的repo(專案)
    (專案 / "還沒提交.txt").write_text("主工作區的草稿\n", encoding="utf-8")

    落點 = 開一個工作樹(專案, 落點=tmp_path / "工作樹" / "分支乙", 起點commit=起點commit)

    assert not (落點 / "還沒提交.txt").exists(), (
        "主工作區沒提交的檔案跑進工作樹了，那就不是從 commit 長出來的"
    )


def test_收集證據要含未追蹤的新檔(tmp_path: Path) -> None:
    """TDD 的產出整包都是新增檔案，`git diff` 看不到——漏了等於成果憑空消失。"""
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造有兩個commit的repo(專案)
    落點 = 開一個工作樹(專案, 落點=tmp_path / "工作樹" / "分支丙", 起點commit=起點commit)

    (落點 / "新增的測試.py").write_text("def test_甲(): pass\n", encoding="utf-8")
    (落點 / "共用.txt").write_text("分支丙改的\n", encoding="utf-8")

    證據 = 收集證據(落點)

    assert "新增的測試.py" in 證據, "未追蹤的新檔沒進證據，那個分支的產出會整包不見"
    assert "def test_甲(): pass" in 證據
    assert "分支丙改的" in 證據, "改動過的舊檔也要在證據裡"


def test_收掉乾淨的工作樹(tmp_path: Path) -> None:
    """跑完而且乾淨的工作樹要收得掉，不然磁碟上會越積越多。"""
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造有兩個commit的repo(專案)
    落點 = 開一個工作樹(專案, 落點=tmp_path / "工作樹" / "分支丁", 起點commit=起點commit)

    收掉工作樹(落點)

    assert not 落點.exists()
    assert "分支丁" not in _跑(專案, "worktree", "list").stdout


def test_失敗的工作樹不准收掉_路徑留在例外裡(tmp_path: Path) -> None:
    """髒的工作樹收不掉是特性不是障礙：現場要留著給人看，不准 `--force` 硬過。"""
    專案 = tmp_path / "專案"
    專案.mkdir()
    起點commit = _造有兩個commit的repo(專案)
    落點 = 開一個工作樹(專案, 落點=tmp_path / "工作樹" / "分支戊", 起點commit=起點commit)
    (落點 / "失敗現場.txt").write_text("跑到一半死掉\n", encoding="utf-8")

    with pytest.raises(OSError, match="失敗現場|收不掉工作樹") as 例外:
        收掉工作樹(落點)

    assert str(落點) in str(例外.value), "收不掉時要把路徑講出來，不然沒人找得到現場"
    assert (落點 / "失敗現場.txt").exists(), "失敗現場被 --force 銷毀了"
