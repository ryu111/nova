"""撞號不准靜默：三個落盤點在同一個執行識別碼上都要出聲。

執行識別碼長 `20260830T023719Z-f7a04a`（UTC 時戳 ＋ 24 bit 亂數）。
**撞號不是只有機率問題**：`帳本.新執行識別碼` 讀 `NOVA_RUN_ID` 時
**只驗格式不驗歸屬**，而 `nova 問 --背景` 會把這個值交給子程序——
一個殘留在環境裡的值就讓每一次執行都用同一個號碼，那是必然路徑。

| 落盤點 | 撞號原本會怎樣 |
|---|---|
| `帳本/<識別>.jsonl` | 兩次執行的事件**交錯合併**進同一本帳 |
| `已處理/<識別>.json` | 後者**靜默覆寫**前者 |
| `背景/<識別>.md` | 後者**靜默截斷**前者 |

**退出碼是 1（確定失敗），不是 3 也不是 4。** 撞號是在開檔的當下發現的，
那時候一顆模型都還沒叫過、什麼副作用都還沒發生，所以它是「確定失敗」，
而且**重跑是安全的**——3 的語意剛好相反（不知道做了沒，不准重跑），
4 留給工作流的停止規則（預算、步數、卡住），落盤失敗不是護欄生效。

事件帳本的形狀在 `test_帳本落盤.py`；這裡驗的是**整條 CLI 的退出碼**
與另外兩個落盤點。會 fork、會碰檔案，所以住整合層。
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from nova.契約.成果 import 成果
from nova.契約.遮罩 import 已經遮過了
from nova.載體.剖析器 import 建剖析器
from nova.載體.命令列 import _丟到背景, 處理們
from nova.載體.已處理 import 歸檔
from nova.載體.帳本 import 指定識別碼的環境變數

#: `做假CLI` fixture 的形狀。**各檔自己寫一份**——跨檔 import 會撞上
#: mypy 的「同一個檔算成兩個模組」（測試目錄沒有 `__init__.py`）。
做假CLI型 = Callable[..., tuple[Path, Path]]

#: 撞在一起的那個號碼。格式要真的合法，不然 `NOVA_RUN_ID` 會被擋掉，
#: 兩次執行就各自拿到亂數號——那樣這幾支測試會**因為沒撞到而永遠綠**。
_撞號 = "20260830T023719Z-f7a04a"


def _成果(收場: str) -> 成果:
    return 成果(
        執行識別碼=_撞號,
        任務=已經遮過了("隨便一件事", 因為="測試資料，裡面沒有祕密"),
        收場=收場,
        退出碼=0,
        起="2026-08-30T09:15:00Z",
        迄="2026-08-30T09:31:00Z",
        走了幾階=5,
        總token=100,
    )


class Test事件帳本:
    def test_撞號的退出碼是確定失敗(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        """**1 不是 3**：開檔當下還沒叫過模型，所以「確定失敗、重跑安全」。

        用真的子程序跑，因為退出碼只有整條 CLI 走完才驗得出來
        （行程內呼叫 `主程式` 看到的是例外，不是退出碼）。
        假 CLI，不燒 token。
        """
        假, _ = 做假CLI("claude")
        帳本目錄 = tmp_path / "帳"
        帳本目錄.mkdir()
        先來的 = 帳本目錄 / f"{_撞號}.jsonl"
        先來的.write_text('{"run": "先來的"}\n', encoding="utf-8")

        跑完 = subprocess.run(  # noqa: S603 —— 就是 nova 自己，參數是這裡寫死的
            [
                sys.executable,
                "-m",
                "nova",
                "問",
                "--用",
                "claude",
                "--執行檔",
                str(假),
                "--帳本目錄",
                str(帳本目錄),
                "在嗎",
            ],
            env={**os.environ, 指定識別碼的環境變數: _撞號},
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )

        assert 跑完.returncode == 1, (
            f"撞號要當場炸成確定失敗（1）\nstdout={跑完.stdout}\nstderr={跑完.stderr}"
        )
        assert 先來的.read_text(encoding="utf-8") == '{"run": "先來的"}\n', "先來的那本帳被動到了"


class Test成果帳本:
    def test_同號歸檔第二次要當場炸(self, tmp_path: Path) -> None:
        """`write_text` 是靜默覆寫。成果是拿來當證據的東西，被蓋掉那次就啞了。"""
        歸檔(_成果("完成"), 目錄=tmp_path)

        with pytest.raises(FileExistsError, match=_撞號):
            歸檔(_成果("後來的"), 目錄=tmp_path)

    def test_第一份成果不准被蓋掉(self, tmp_path: Path) -> None:
        """炸了還把檔案改掉的話，等於既出了聲又弄丟了證據。"""
        歸檔(_成果("完成"), 目錄=tmp_path)

        with pytest.raises(FileExistsError, match=_撞號):
            歸檔(_成果("後來的"), 目錄=tmp_path)

        躺著的 = json.loads((tmp_path / f"{_撞號}.json").read_text(encoding="utf-8"))
        assert 躺著的["outcome"] == "完成"


class Test背景輸出:
    """`nova 問 --背景` 的輸出檔。**這一格最容易撞**——

    背景派工自己就是把 `NOVA_RUN_ID` 傳下去的那個人。
    """

    def _派一次(self, 專案: Path, monkeypatch: pytest.MonkeyPatch, 生出來的: list[object]) -> int:
        指令 = ["問", "--用", "claude", "--工作目錄", str(專案), "--背景", "在嗎"]
        # 重新發射走的是 `sys.argv`，所以那份也要擺對。
        monkeypatch.setattr(sys, "argv", ["nova", *指令])
        # **不准真的把子程序生出來**：這幾支要驗的是落盤，不是模型。
        # **用字串路徑 patch**：`from nova.載體 import 命令列` 之後去拿它的
        # `subprocess` 屬性會被 mypy 擋（模組沒有顯式匯出它），而那個擋是對的
        # ——測試不該依賴別的模組 import 了什麼。
        monkeypatch.setattr(
            "nova.載體.命令列.subprocess.Popen",
            lambda *參, **鍵: 生出來的.append((參, 鍵)),
        )
        return _丟到背景(建剖析器(處理們).parse_args(指令))

    def test_同號的背景輸出檔不准被截斷(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`open("w")` 會把上一次派工的輸出整個清成 0 byte，而且不出聲。

        落點**問 nova 自己要**（從它印出來的那行讀），不要在測試裡重算路徑——
        算錯的話這支會因為看錯地方而永遠綠。
        """
        專案 = tmp_path / "專案"
        專案.mkdir()
        monkeypatch.setenv(指定識別碼的環境變數, _撞號)
        生出來的: list[object] = []

        assert self._派一次(專案, monkeypatch, 生出來的) == 0
        落點 = Path(capsys.readouterr().out.split("輸出寫在：")[1].splitlines()[0].strip())
        落點.write_text("第一次的輸出", encoding="utf-8")

        with pytest.raises(FileExistsError, match=_撞號):
            self._派一次(專案, monkeypatch, 生出來的)

        assert 落點.read_text(encoding="utf-8") == "第一次的輸出"
        assert len(生出來的) == 1, "撞號了就不准把第二個子程序生出來"
