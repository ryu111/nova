"""「這支測試會打到真的 CLI」的機械判準，要**指名**是哪一支。

被一個真缺陷逼出來的：`tests/驗收/test_委派給其他llm.py` 的 docstring 第 4 行寫著
全檔前提「用假 CLI 跑，所以不燒 token、CI 也能跑」，但檔案裡有兩支沒帶 `--執行檔`。
它們沒燒，只是因為參數檢查在門口就擋掉了；`#141` 放寬那條檢查之後，
它們一路跑到真的 `codex exec`，紅在 `[quota-exhausted] Reading additional input from stdin`。
**額度沒用完的話，它們會安安靜靜地綠著燒 token，而閘不會說任何話。**

判準要看「跑起來會不會 exec」而不是「argv 長什麼樣」：ast 掃過一輪，以 argv list
為單位、扣掉含 `--執行檔`／`--help` 的組別之後還剩 32 組嫌疑——因為 ast 看不到
fixture 與 monkeypatch，誤報率高到沒人會理它。

放整合層不放單元層：判準要真的 fork 一次 pytest，秒級。
"""

import stat
import sys
from pathlib import Path

from nova.載體.裸跑真cli import 檢查裸跑真cli


def test_拿掉執行檔的那支被指名而給了假cli的那支不被指名(tmp_path: Path) -> None:
    """驗收的形狀：一支測試少了 `--執行檔`，閘要指名**那一支**、而且只有那一支。

    兩邊一起驗，缺一不可——只驗其中一邊都有一個蠢實作可以綠：
    - 只驗「裸跑的被指名」：一個把所有測試都列出來的實作就綠了；
    - 只驗「給了假 CLI 的沒被指名」：一個永遠放行的實作就綠了。

    小專案裡的 `test_裸跑子命令` 在平常的 `PATH` 下**可能是綠的**（這台機器裝了
    codex），那正是要抓的情況：它綠著，而閘不說話。它裸跑的是 `--version`，
    所以這支測試自己在任何情況下都不會燒到 token；判準看的是 exec 得不得到，
    不是 argv 上掛了什麼旗標——**會不會花錢是 argv 說了不算的事**。

    `test_給了執行檔` 走絕對路徑的假 CLI，是「注入過執行檔／monkeypatch 換掉腦」
    那一類的最小形狀：它不靠 `PATH` 也跑得到，所以不該被指名。
    """
    假cli = tmp_path / "假codex"
    假cli.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(0)\n", encoding="utf-8")
    假cli.chmod(假cli.stat().st_mode | stat.S_IEXEC)

    測試目錄 = tmp_path / "tests"
    測試目錄.mkdir()
    (測試目錄 / "test_樣本.py").write_text(
        "import subprocess\n"
        "\n"
        "\n"
        "def test_給了執行檔() -> None:\n"
        f'    結果 = subprocess.run(["{假cli}", "exec", "在嗎"], check=False)\n'
        "    assert 結果.returncode == 0\n"
        "\n"
        "\n"
        "def test_裸跑子命令() -> None:\n"
        '    結果 = subprocess.run(["codex", "--version"], check=False)\n'
        "    assert 結果.returncode == 0\n",
        encoding="utf-8",
    )

    放行, 證據 = 檢查裸跑真cli(tmp_path)

    assert 放行 is False, 證據
    assert "test_裸跑子命令" in 證據, f"閘沒指名裸跑的那一支：{證據}"
    assert "test_樣本.py" in 證據, f"指名要精確到檔案，不然沒人找得到：{證據}"
    assert "test_給了執行檔" not in 證據, f"給了假 CLI 的那支被誤報了：{證據}"
