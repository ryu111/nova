"""檢查 shell 指令是否會寫入受管轄的檔案。

## 為什麼需要這支測試

PreToolUse 的 Bash hook 叫 `nova 檢查指令`，以往只擋三條硬禁令（--no-verify、--admin、
gh pr merge 缺少 --delete-branch），完全不檢查是否寫檔。

這導致透過 Bash（如重導、sed -i、tee、cp/mv、python heredoc）修改檔案一路綠燈，
而用 Edit/Write 工具修改同一個檔案卻會被 PreToolUse 護欄要求走 nova 或記下繞過理由。

護欄的判準必須基於「行為」而非「工具名稱」。

## 判準規則（機械化判斷，不依賴模型）

1. 重導：`>` 或 `>>` 後面第一個 token
2. 就地編輯：`sed -i` 之後的檔案參數
3. tee：`tee` 或 `tee -a` 後面的 token
4. 複製搬移：`cp`、`mv` 的最後一個 token
5. python heredoc：內容同時出現寫檔呼叫（`write_text`、`open(` 帶 `"w"`/`"a"`/`"x"`）
   與管轄範圍路徑字樣（`src/`、`tests/`、`docs/`）

## 放行原則（不准擋過頭）

- 寫到 `/tmp`、非管轄範圍路徑放行
- 唯讀指令（cat、grep、pytest、git status、git diff 等）放行
- 點開頭的工具地盤（`.remember/`、`.claude/`、`.git/`）或 scratchpad 放行
"""

from pathlib import Path

import pytest

from nova.載體.禁令 import 會寫到管轄範圍嗎, 檢查指令
from nova.載體.自己動手 import 記下繞過

根 = Path("/repo")


class Test重導寫入:
    """測試 `>` 與 `>>` 重導寫檔形式。"""

    @pytest.mark.parametrize(
        "命令",
        [
            "echo 'hello' > src/nova/載體/新模組.py",
            "printf 'code' >> tests/單元/test_新測試.py",
            "cat something > docs/決策/0003-新決策.md",
            "echo 123 > 'src/nova/空白 路徑.py'",
        ],
    )
    def test_重導寫入管轄檔案要命中(self, 命令: str) -> None:
        assert 會寫到管轄範圍嗎(命令, 根目錄=根) is True

    @pytest.mark.parametrize(
        "命令",
        [
            "echo 'test' > /tmp/temp.txt",
            "echo 'memo' > .remember/now.md",
            "echo 'note' > scratchpad/筆記.md",
            "echo 'config' > .claude/settings.json",
        ],
    )
    def test_重導寫入非管轄檔案要放行(self, 命令: str) -> None:
        assert 會寫到管轄範圍嗎(命令, 根目錄=根) is False


class Test就地編輯:
    """測試 `sed -i` 就地編輯形式。"""

    @pytest.mark.parametrize(
        "命令",
        [
            "sed -i '' 's/old/new/' src/nova/載體/禁令.py",
            "sed -i 's/foo/bar/g' docs/README.md",
            "sed -i.bak 's/a/b/' tests/單元/test_禁令指令.py",
        ],
    )
    def test_就地編輯管轄檔案要命中(self, 命令: str) -> None:
        assert 會寫到管轄範圍嗎(命令, 根目錄=根) is True

    @pytest.mark.parametrize(
        "命令",
        [
            "sed -i '' 's/old/new/' /tmp/temp.py",
            "sed -i 's/a/b/' .remember/notes.md",
            "sed -n '1,10p' src/nova/載體/禁令.py",
        ],
    )
    def test_就地編輯非管轄檔案或唯讀sed要放行(self, 命令: str) -> None:
        assert 會寫到管轄範圍嗎(命令, 根目錄=根) is False


class TestTee寫入:
    """測試 `tee` 與 `tee -a` 寫檔形式。"""

    @pytest.mark.parametrize(
        "命令",
        [
            "cat something | tee src/nova/載體/新模組.py",
            "echo 'abc' | tee -a tests/單元/test_abc.py",
            "echo 'doc' | tee docs/設計/08-新設計.md",
        ],
    )
    def test_tee寫入管轄檔案要命中(self, 命令: str) -> None:
        assert 會寫到管轄範圍嗎(命令, 根目錄=根) is True

    @pytest.mark.parametrize(
        "命令",
        [
            "cat something | tee /tmp/log.txt",
            "echo 'xyz' | tee .git/config",
            "cat something | tee scratchpad/out.txt",
        ],
    )
    def test_tee寫入非管轄檔案要放行(self, 命令: str) -> None:
        assert 會寫到管轄範圍嗎(命令, 根目錄=根) is False


class Test複製搬移:
    """測試 `cp` 與 `mv` 寫入目標檔案形式。"""

    @pytest.mark.parametrize(
        "命令",
        [
            "cp /tmp/patch.py src/nova/載體/禁令.py",
            "mv /tmp/temp_test.py tests/單元/test_temp.py",
            "cp something docs/決策/0003.md",
        ],
    )
    def test_複製搬移到管轄檔案要命中(self, 命令: str) -> None:
        assert 會寫到管轄範圍嗎(命令, 根目錄=根) is True

    @pytest.mark.parametrize(
        "命令",
        [
            "cp src/nova/載體/禁令.py /tmp/backup.py",
            "mv docs/README.md /tmp/old_readme.md",
            "cp /tmp/x .remember/now.md",
            "cp something scratchpad/temp.py",
        ],
    )
    def test_複製搬移到非管轄路徑要放行(self, 命令: str) -> None:
        assert 會寫到管轄範圍嗎(命令, 根目錄=根) is False


class TestPythonHeredoc:
    """測試 python heredoc 寫檔形式。"""

    @pytest.mark.parametrize(
        "命令",
        [
            "python3 - <<'PY'\nPath('src/nova/a.py').write_text('hi')\nPY",
            'python3 - <<\'PY\'\nopen("tests/單元/test_x.py", "w").write("x")\nPY',
            'python3 - <<\'PY\'\nwith open("docs/指南.md", "a") as f:\n    f.write("doc")\nPY',
            'python3 - <<\'PY\'\nopen("src/nova/b.py", "x").write("new")\nPY',
        ],
    )
    def test_python_heredoc寫入管轄檔案要命中(self, 命令: str) -> None:
        assert 會寫到管轄範圍嗎(命令, 根目錄=根) is True

    @pytest.mark.parametrize(
        "命令",
        [
            "python3 - <<'PY'\nPath('/tmp/temp.py').write_text('hi')\nPY",
            "python3 - <<'PY'\nprint(Path('src/nova/a.py').read_text())\nPY",
            'python3 - <<\'PY\'\nopen("tests/單元/test_x.py", "r").read()\nPY',
            "python3 - <<'PY'\nPath('.remember/now.md').write_text('memo')\nPY",
            "python3 - <<'PY'\nPath('scratchpad/test.py').write_text('data')\nPY",
        ],
    )
    def test_python_heredoc寫入非管轄或唯讀要放行(self, 命令: str) -> None:
        assert 會寫到管轄範圍嗎(命令, 根目錄=根) is False


class Test唯讀指令放行:
    """測試一般唯讀指令不准誤擋。"""

    @pytest.mark.parametrize(
        "命令",
        [
            "cat src/nova/載體/禁令.py",
            "grep -rn 'def 檢查' src/",
            "pytest tests/單元/test_禁令指令.py",
            "git status",
            "git diff src/nova/",
            "git log -n 5",
            "ls -la docs/",
            "uv run nova 閘 ci",
        ],
    )
    def test_唯讀指令一律放行(self, 命令: str) -> None:
        assert 會寫到管轄範圍嗎(命令, 根目錄=根) is False


class Test檢查指令整合:
    """測試 `檢查指令` 函式整合管轄寫入檢查後的行為。"""

    def test_寫入管轄檔案要被擋下並提示繞過或走nova(self) -> None:
        通過, 原因 = 檢查指令("echo 'hello' > src/nova/載體/新模組.py", 根目錄=根)
        assert 通過 is False
        assert "nova 跑" in 原因 or "nova 繞過" in 原因, "擋下原因必須提示走 nova 或 nova 繞過"

    def test_寫入非管轄檔案要放行(self) -> None:
        通過, _ = 檢查指令("echo 'temp' > /tmp/temp.txt", 根目錄=根)
        assert 通過 is True

    def test_唯讀指令要放行(self) -> None:
        通過, _ = 檢查指令("pytest tests/單元", 根目錄=根)
        assert 通過 is True

    def test_原有禁令優先擋下(self) -> None:
        """原有三條硬禁令必須維持阻擋，且維持原有禁令原因。"""
        通過, 原因 = 檢查指令("git commit --no-verify -m 'skip'", 根目錄=根)
        assert 通過 is False
        assert "--no-verify" in 原因


class Test擋了要有出路:
    """**這三支是這道護欄第一次真的擋到人之後補的。**

    2026-08-30 護欄接上的那一刻就把作者鎖在外面：想記一次繞過理由，
    `nova 繞過` 那條指令自己被擋下——因為訊息裡的佔位符含角括號，
    照抄下來執行就命中重導樣式。**它印給人照做的那句話，照做就被自己擋。**

    擋過頭的閘會被繞過，繞過一次就等於不存在（CLAUDE.md）。
    所以出路必須真的存在、而且真的走得通。
    """

    def test_重導到不像路徑的東西要放行(self) -> None:
        """**判準過寬會擋掉一切。**

        原本的判準是「重導目標落在 repo 內、不以 `.` 開頭」——而
        `在管轄範圍嗎` 對任何相對路徑都成立，於是
        `echo 說明 > 一句話` 裡那句中文也被當成受管轄的路徑。

        收緊成「要真的落在 `src/`、`tests/`、`docs/` 底下」，
        跟 python heredoc 那條用同一份前綴表。
        """
        通過, _ = 檢查指令("echo 這是一句話 > 另一句話", 根目錄=根)

        assert 通過 is True, "重導目標不是受管轄的路徑，不該擋"

    def test_說得出理由就放行(self, tmp_path: Path) -> None:
        """**繞過必須對 Bash 這條路也有效。**

        `檢查編輯`（Edit／Write 那條）本來就會先問 `說得出理由了嗎`，
        `檢查指令`（Bash 那條）漏了——於是擋下來之後**沒有任何出路**，
        連 `nova 繞過` 自己都執行不了。
        """
        記下繞過("s-1", "測試用的理由", 專案=tmp_path)

        通過, _ = 檢查指令("echo x > src/nova/甲.py", 根目錄=根, 會話="s-1", 專案=tmp_path)

        assert 通過 is True, "已經記下理由了還擋，那個繞過機制等於不存在"

    def test_沒說理由就照擋(self, tmp_path: Path) -> None:
        """**不能擋不住**——放行的條件是「說得出理由」，不是「有傳會話參數」。"""
        通過, _ = 檢查指令("echo x > src/nova/甲.py", 根目錄=根, 會話="沒記過的", 專案=tmp_path)

        assert 通過 is False
