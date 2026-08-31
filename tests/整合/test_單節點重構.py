"""`nova 重構`：把一個 TDD 階段拆出來單獨叫。

## 為什麼要有這個子命令

使用者的原話：「worker 內的每一個節點都應該也是可以單拆出來使用，
就不會像現在這樣子了，而且也都能隨時組裝。」

在它存在之前，要重構只有兩條路：跑整條 TDD 七階段（30–60 分鐘、
表達不了「只改這個模組」），或者自己動手。**第二條比第一條便宜一個數量級**，
所以護欄擋不擋得住不重要——沒有人會走那條貴的。
給路跟補洞是同一件事的兩半。

## 這個節點的護欄：不准動測試

重構員的提示第一條就是「不准改任何測試檔」，但那是懇求。
這裡的判準是**跑之前拍一張快照、跑之後再拍一張**，差在哪一個檔就是誰被動了
（`載體/重構護欄.py`）。動了就回**退出碼 4**——護欄生效，不是壞了。

`CLAUDE.md`：外圈看到 4 不准去「修」。護欄最省事的修法是把上限調高，
那是自己拆執法點。

會 fork 子程序、會碰檔案，所以住整合層。
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from nova.載體.命令列 import 主程式, 護欄碼

nova執行檔 = Path(sys.executable).parent / "nova"
做假CLI型 = Callable[..., tuple[Path, Path]]


@pytest.fixture
def 工地(tmp_path: Path) -> Path:
    """一個長得像專案的目錄：有 src/ 也有 tests/。"""
    專案 = tmp_path / "專案"
    (專案 / "src").mkdir(parents=True)
    (專案 / "tests").mkdir(parents=True)
    (專案 / "src" / "甲.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (專案 / "tests" / "test_甲.py").write_text("def test_f():\n    assert True\n", encoding="utf-8")
    return 專案


def _會偷改測試的CLI(工地: Path, 真的假CLI: Path, tmp_path: Path) -> Path:
    """包一層：先去動測試檔，再把工作交給真正的假 CLI。

    **假 CLI 是重播 transcript 的，它不會真的寫檔**，所以「模型改了測試」
    這件事沒辦法靠它模擬。這個包裝就是那個缺口——它做的正是重構員
    被禁止做的事。
    """
    腳本 = tmp_path / "會偷改測試的假CLI"
    腳本.write_text(
        "#!/bin/sh\n"
        f'echo "# 我偷偷加了一行" >> "{工地 / "tests" / "test_甲.py"}"\n'
        f'exec "{真的假CLI}" "$@"\n',
        encoding="utf-8",
    )
    腳本.chmod(0o755)
    return 腳本


def _跑(*參數: str, 在: Path, 狀態: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=在,
        env={**os.environ, "XDG_STATE_HOME": str(狀態)},
        capture_output=True,
        text=True,
        check=False,
    )


class Test單獨叫得動:
    def test_乖乖重構就成功(self, 工地: Path, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        """**不能擋到正常用法**——擋過頭的閘會被繞過，繞過一次就等於不存在。"""
        假, _ = 做假CLI("claude")

        跑完 = _跑(
            "重構",
            "--用",
            "claude",
            "--執行檔",
            str(假),
            "--可編輯",
            "把甲整理乾淨",
            在=工地,
            狀態=tmp_path / "state",
        )

        assert 跑完.returncode == 0, 跑完.stdout + 跑完.stderr

    def test_只叫一次模型不是跑七階段(self, 工地: Path, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        """**單節點的意思就是一次呼叫。**

        走七階段的話這裡會看到四次以上（測試、實作、判準、審查…），
        而那正是「太貴所以沒人用」的原因。

        **數帳本不數假 CLI 的紀錄檔**：那個檔只留最後一次呼叫的 argv，
        數不出次數。而且帳本才是使用者真的看得到的東西——
        「叫了幾次」這個問題他也是去那裡問的。
        """
        假, _ = 做假CLI("claude")
        帳本目錄 = tmp_path / "帳"

        _跑(
            "重構",
            "--用",
            "claude",
            "--執行檔",
            str(假),
            "--帳本目錄",
            str(帳本目錄),
            "--可編輯",
            "把甲整理乾淨",
            在=工地,
            狀態=tmp_path / "state",
        )

        叫了幾次 = sum(
            行.count('"call_started"')
            for 檔 in 帳本目錄.glob("*.jsonl")
            for 行 in 檔.read_text(encoding="utf-8").splitlines()
        )
        assert 叫了幾次 == 1, f"單節點只准叫一次模型，帳本上有 {叫了幾次} 次"


class Test護欄:
    def test_動到測試檔就回護欄(self, 工地: Path, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        """**退出碼 4 不是壞了**，是停止規則按設計生效。"""
        假, _ = 做假CLI("claude")
        偷改的 = _會偷改測試的CLI(工地, 假, tmp_path)

        跑完 = _跑(
            "重構",
            "--用",
            "claude",
            "--執行檔",
            str(偷改的),
            "--可編輯",
            "把甲整理乾淨",
            在=工地,
            狀態=tmp_path / "state",
        )

        assert 跑完.returncode == 4, (
            f"動了測試檔要回護欄（4），實際 {跑完.returncode}\n{跑完.stdout}{跑完.stderr}"
        )

    def test_護欄要說得出動到哪一個檔(self, 工地: Path, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        """**只說「違規了」等於沒說。** 人要知道去哪裡看、還原哪一個檔。"""
        假, _ = 做假CLI("claude")
        偷改的 = _會偷改測試的CLI(工地, 假, tmp_path)

        跑完 = _跑(
            "重構",
            "--用",
            "claude",
            "--執行檔",
            str(偷改的),
            "--可編輯",
            "把甲整理乾淨",
            在=工地,
            狀態=tmp_path / "state",
        )

        全部 = 跑完.stdout + 跑完.stderr
        assert "tests/test_甲.py" in 全部, f"沒說是哪個檔被動了：{全部}"

    def test_重構要把重構員的規矩交出去(
        self, 工地: Path, tmp_path: Path, 做假CLI: 做假CLI型
    ) -> None:
        """**光有護欄不夠，也要先跟它說。**

        護欄是事後攔截：模型改了測試才發現，那一次的 token 已經花掉了。
        角色提示是事前告知，兩層都要有——只有護欄的話它每次都會踩，
        只有提示的話它踩了沒人知道。

        同時驗題目也在：只傳角色不傳題目的話，模型會去重構「某個東西」。
        """
        假, 紀錄 = 做假CLI("claude")

        _跑(
            "重構",
            "--用",
            "claude",
            "--執行檔",
            str(假),
            "--可編輯",
            "把甲整理乾淨",
            在=工地,
            狀態=tmp_path / "state",
        )

        送出去的 = " ".join(json.loads(紀錄.read_text(encoding="utf-8"))["argv"])
        assert "不准改任何測試檔" in 送出去的, "重構員的第一條規矩沒送出去"
        assert "把甲整理乾淨" in 送出去的, "題目沒送出去，那它要重構什麼？"


class Test範圍護欄也要接到命令列:
    """`跑出範圍了嗎` 是純函式，**但純函式沒有呼叫端就等於沒有保證**。

    `--範圍` 讓呼叫端指名這次只准動哪些路徑；動到範圍外就回護欄碼 4。
    不給 `--範圍` 時維持原本的行為（只擋測試），既有呼叫端不會壞掉。

    **走 in-process `主程式` 不開子程序**：coverage 追不到子程序的行，
    變異閘會判 `WRONG_TEST`（同一個坑今天踩過兩次）。
    """

    @staticmethod
    def _會伸出範圍的CLI(工地: Path, 真的假CLI: Path, tmp_path: Path) -> Path:
        """先去動一個範圍外的檔，再把工作交給真正的假 CLI。"""
        腳本 = tmp_path / "會伸出範圍的假CLI"
        腳本.write_text(
            "#!/bin/sh\n"
            f'echo "# 手伸到範圍外了" >> "{工地 / "src" / "乙.py"}"\n'
            f'exec "{真的假CLI}" "$@"\n',
            encoding="utf-8",
        )
        腳本.chmod(0o755)
        return 腳本

    def _叫重構(self, *參數: str, 在: Path, 狀態: Path, monkeypatch: pytest.MonkeyPatch) -> int:
        monkeypatch.setenv("XDG_STATE_HOME", str(狀態))
        monkeypatch.chdir(在)
        return 主程式(["重構", *參數])

    def test_動到範圍外要回護欄碼(
        self, 工地: Path, tmp_path: Path, 做假CLI: 做假CLI型, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (工地 / "src" / "乙.py").write_text("def g():\n    return 2\n", encoding="utf-8")
        假, _ = 做假CLI("claude")
        壞的 = self._會伸出範圍的CLI(工地, 假, tmp_path)

        碼 = self._叫重構(
            "--用",
            "claude",
            "--執行檔",
            str(壞的),
            "--可編輯",
            "--範圍",
            "src/甲.py",
            "把甲整理乾淨",
            在=工地,
            狀態=tmp_path / "state",
            monkeypatch=monkeypatch,
        )

        assert 碼 == 護欄碼, "動到 src/乙.py 卻沒回護欄碼"

    def test_只動範圍內就放行(
        self, 工地: Path, tmp_path: Path, 做假CLI: 做假CLI型, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**不能擋到正常用法**——擋過頭的閘會被繞過，繞過一次就等於不存在。"""
        假, _ = 做假CLI("claude")

        碼 = self._叫重構(
            "--用",
            "claude",
            "--執行檔",
            str(假),
            "--可編輯",
            "--範圍",
            "src",
            "把甲整理乾淨",
            在=工地,
            狀態=tmp_path / "state",
            monkeypatch=monkeypatch,
        )

        assert 碼 == 0

    def test_不給範圍時維持原本的行為(
        self, 工地: Path, tmp_path: Path, 做假CLI: 做假CLI型, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """既有呼叫端一個都不准壞掉。"""
        (工地 / "src" / "乙.py").write_text("def g():\n    return 2\n", encoding="utf-8")
        假, _ = 做假CLI("claude")
        壞的 = self._會伸出範圍的CLI(工地, 假, tmp_path)

        碼 = self._叫重構(
            "--用",
            "claude",
            "--執行檔",
            str(壞的),
            "--可編輯",
            "把甲整理乾淨",
            在=工地,
            狀態=tmp_path / "state",
            monkeypatch=monkeypatch,
        )

        assert 碼 == 0, "沒給 --範圍 卻擋了，既有呼叫端會壞"
