"""使用者說的那句話：**照 `nova 排程` 印出來的東西裝下去，它會動。**

CLAUDE.md 判準三：**墊片證明的是轉遞形狀，不是可達性。** 單元測試看得出
`ProgramArguments` 裡有沒有那幾個字串，看不出那行指令**跑不跑得起來**——
旗標名打錯一個字、`--預算幾小時` 沒加到 `巡` 的剖析器上，
plist 照樣長得一模一樣，而失敗會發生在 launchd 的 log 裡，沒有人會看到。

所以這一支**把 plist 裡的那行指令拿出來真的執行**。

（真的 `launchctl load` 不做：BTM 會留紀錄、unload 也清不乾淨，
那是使用者系統上的狀態。nova 產生，人安裝。）
"""

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from nova.載體.判準 import 預設判準指令

nova執行檔 = Path(sys.executable).parent / "nova"


def _跑(*參數: str, 狀態: Path, 在: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=在,
        env={**os.environ, "XDG_STATE_HOME": str(狀態)},
        capture_output=True,
        text=True,
        check=False,
    )


def _時鐘要裝的那份(*排程參數: str, 狀態: Path, 專案: Path) -> dict[str, object]:
    """`nova 排程` 印出來的那份 plist，整份讀回來。

    **不要在測試裡自己組那行指令、也不要自己挑工作目錄**——自己組的話，
    plist 怎麼寫都不會紅，而這一支要守的就是「印出來的東西跟跑得起來的
    東西是同一個」。launchd 是照 `ProgramArguments` **加上** `WorkingDirectory`
    起這個程序的，所以兩個都要從這份 plist 裡拿。
    """
    跑完 = _跑("排程", *排程參數, 狀態=狀態, 在=專案)
    印出來 = 跑完.stdout
    assert "</plist>" in 印出來, f"nova 排程 沒印出 plist：\n{印出來}\n{跑完.stderr}"
    設定: dict[str, object] = plistlib.loads(
        印出來.split("</plist>")[0].encode("utf-8") + b"</plist>"
    )
    return 設定


def _時鐘要跑的那行(*排程參數: str, 狀態: Path, 專案: Path) -> list[str]:
    """那份 plist 裡的 `ProgramArguments`。"""
    參數: list[str] = _時鐘要裝的那份(*排程參數, 狀態=狀態, 專案=專案)["ProgramArguments"]  # type: ignore[assignment]
    return 參數


def _沒有預算的時候(tmp_path: Path) -> tuple[Path, Path]:
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    專案.mkdir()
    return 狀態, 專案


def _daemon那份checkout(tmp_path: Path) -> Path:
    """排程醒來站的地方：**daemon 自己那份 checkout，不是要被巡的那棵樹。**

    launchd 是照 plist 的 `WorkingDirectory` 起這個程序的，所以測試也要站在
    那種地方跑——乾淨的 git 樹、不在 `專案` 底下。
    """
    落腳 = tmp_path / "daemon那份"
    落腳.mkdir()
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q"], cwd=落腳, check=True)
    subprocess.run([*git, "commit", "-qm", "起點", "--allow-empty"], cwd=落腳, check=True)
    return 落腳


def test_印出來的那行指令真的跑得起來(tmp_path: Path) -> None:
    """空專案回 0——**沒有東西可做是正常狀態**，排程多數時候醒來就是這樣。

    而且那一趟要**站在 plist 自己說的那個 `WorkingDirectory` 裡**跑：
    launchd 只認那一格，測試自己挑一個乾淨的 checkout 來跑的話，
    plist 裡寫 `.`（＝launchd 自己的 cwd，誰都說不準是哪裡）也照樣全綠。
    站進 `專案` 裡則要被擋下來——排程醒來就在要被巡的那棵樹裡的話，
    那棵樹壞掉的那天它跟著壞。
    """
    狀態, 專案 = _沒有預算的時候(tmp_path)
    設定 = _時鐘要裝的那份(狀態=狀態, 專案=專案)
    指令: list[str] = 設定["ProgramArguments"]  # type: ignore[assignment]
    環境 = {**os.environ, "XDG_STATE_HOME": str(狀態)}

    launchd會站的地方 = Path(str(設定["WorkingDirectory"]))

    assert launchd會站的地方.is_absolute(), (
        f"WorkingDirectory 不是絕對路徑：{設定['WorkingDirectory']!r}"
    )
    assert launchd會站的地方.is_dir(), f"WorkingDirectory 指到不存在的地方：{launchd會站的地方}"
    assert launchd會站的地方 != 專案, f"WorkingDirectory 就是要被巡的那棵樹：{launchd會站的地方}"
    assert 專案 not in launchd會站的地方.parents, (
        f"WorkingDirectory 落在 {專案} 底下：{launchd會站的地方}"
    )

    # 真的照 plist 說的那樣站過去跑一次：那個目錄要是一份 checkout（巡靠它
    # 印出「當時跑的是哪一版」），而且不能被巡的 cwd 自檢擋下來。
    在plist說的地方 = subprocess.run(
        指令, cwd=launchd會站的地方, env=環境, capture_output=True, text=True, check=False
    )

    assert "巡自己的 HEAD：查不到" not in 在plist說的地方.stdout, (
        f"WorkingDirectory 不是一份 checkout：{launchd會站的地方}"
    )
    assert "現在就站在" not in 在plist說的地方.stderr, 在plist說的地方.stderr

    # 「回 0」那一格另外站在一份**現造的乾淨 checkout** 上驗：巡對自己的樹
    # 要求乾淨，而開發機上那份真的 daemon checkout 乾不乾淨不是這一支的題目
    # ——那會讓「指令跑不跑得起來」隨著別人有沒有改到一半而變色。
    跑完 = subprocess.run(
        指令,
        cwd=_daemon那份checkout(tmp_path),
        env=環境,
        capture_output=True,
        text=True,
        check=False,
    )

    assert 跑完.returncode == 0, 跑完.stdout + 跑完.stderr
    assert "unrecognized arguments" not in 跑完.stderr
    assert "巡自己的 HEAD" in 跑完.stdout, f"跑起來的不是巡：{跑完.stdout}"

    站在專案裡 = subprocess.run(
        指令, cwd=專案, env=環境, capture_output=True, text=True, check=False
    )

    assert 站在專案裡.returncode != 0, f"站在 {專案} 裡竟然照跑：{站在專案裡.stdout}"
    assert str(專案) in 站在專案裡.stderr, 站在專案裡.stderr


def test_帶了預算旗標之後那行指令還是跑得起來(tmp_path: Path) -> None:
    """**這一支才是重點。**

    `--預算token` 有沒有加到 `巡` 的剖析器上，只有真的跑一次才知道。
    沒加的話 argparse 回「unrecognized arguments」、退出碼 2，
    而排程從此每 15 分鐘失敗一次——在 launchd 的 log 裡，沒有人會看到。
    """
    狀態, 專案 = _沒有預算的時候(tmp_path)
    指令 = _時鐘要跑的那行(
        "--預算token", "500000", "--預算美金", "3.5", "--預算幾小時", "6", 狀態=狀態, 專案=專案
    )

    assert "--預算token" in 指令, 指令
    跑完 = subprocess.run(
        指令,
        cwd=_daemon那份checkout(tmp_path),
        env={**os.environ, "XDG_STATE_HOME": str(狀態)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert "unrecognized arguments" not in 跑完.stderr, 跑完.stderr
    assert 跑完.returncode == 0, 跑完.stdout + 跑完.stderr


def test_每一格都是獨立的字串(tmp_path: Path) -> None:
    """`ProgramArguments` **不經過 shell**。

    `"--預算token 500000"` 塞成一格的話，argparse 會拿到一個叫
    「--預算token 500000」的旗標。**這一支在 plist 這一層就擋下來**，
    不必等到 launchd 才發現。
    """
    狀態, 專案 = _沒有預算的時候(tmp_path)

    指令 = _時鐘要跑的那行("--預算token", "500000", 狀態=狀態, 專案=專案)

    assert all(" " not in 格 for 格 in 指令[1:]), 指令


def test_印出來的檔名跟plist裡的Label是同一個(tmp_path: Path) -> None:
    """印出來的那行安裝指令自己說「**檔名要跟 Label 一致**」——那就要真的一致。

    Label 走的是 `_標籤()`（小寫 ASCII kebab，空的退回 `project`），
    印出來的那行卻自己算了一次 `專案.name.lower()`。專案名只要不是
    現成的小寫 ASCII（有空格、有大寫、有中文），兩邊就對不上，
    而使用者照著做會得到一個 `launchctl load` 不動的檔案——
    **兩份對照表就是這條 bug 的形狀。**
    """
    狀態 = tmp_path / "state"
    專案 = tmp_path / "Nova Repo 專案"
    專案.mkdir()

    跑完 = _跑("排程", 狀態=狀態, 在=專案)
    設定 = plistlib.loads(跑完.stdout.encode("utf-8"))

    標籤 = 設定["Label"]
    # 說明走 stderr，plist 走 stdout——`nova 排程 > x.plist` 才會是一份乾淨的 plist。
    說明 = 跑完.stderr
    assert f"{標籤}.plist" in 說明, f"Label 是 {標籤!r}，但安裝指令裡沒有這個檔名：\n{說明}"
    檔名們 = [段 for 段 in 說明.split() if 段.endswith(".plist")]
    assert 檔名們, 說明
    assert all(段.endswith(f"{標籤}.plist") for 段 in 檔名們), f"檔名跟 Label 對不上：\n{說明}"


def test_排程的環境跑得起預設判準(tmp_path: Path) -> None:
    """**判準三：墊片證明的是轉遞形狀，不是可達性。**

    launchd 不跑登入 shell，程序拿到的 `PATH` 是
    `/usr/bin:/bin:/usr/sbin:/sbin`——而 `uv` 住在 `~/.local/bin`。
    所以預設判準 `uv run pytest -q` 在排程底下**根本跑不起來**。

    2026-08-30 實測的代價：判準跑不起來被回報成「紅」，工作流回去
    「再實作一次」，一次醒來燒掉 997,031 token，三次共 1,720,140。

    這一支用 plist 裡宣告的環境（而且**只有**那些）去跑判準的執行檔。
    plist 沒帶 `PATH` 的話，這裡當場 `FileNotFoundError`。
    """
    狀態, 專案 = _沒有預算的時候(tmp_path)
    印出來 = _跑("排程", 狀態=狀態, 在=專案).stdout
    設定 = plistlib.loads(印出來.split("</plist>")[0].encode("utf-8") + b"</plist>")
    環境 = 設定["EnvironmentVariables"]

    跑完 = subprocess.run(
        [預設判準指令[0], "--version"],
        cwd=專案,
        env=環境,
        capture_output=True,
        text=True,
        check=False,
    )

    assert 跑完.returncode == 0, (
        f"排程的環境跑不起 {預設判準指令[0]}：{跑完.stderr}\nPATH={環境.get('PATH')!r}"
    )
