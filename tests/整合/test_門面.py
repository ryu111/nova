"""門面：外部呼叫端只 import 一次就能用 nova。

一支測試守一件事——混在一起的話，紅了不知道是哪個保證壞掉。
全部用假 CLI，不燒 token。
"""

import json
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

import nova

#: `做假CLI` fixture 的形狀。**各檔自己寫一份**——跨檔 import 會撞上
#: mypy 的「同一個檔算成兩個模組」（測試目錄沒有 `__init__.py`）。
#: 只有兩處重複，還沒到三次法則該抽的時候。
做假CLI型 = Callable[..., tuple[Path, Path]]


class Test問:
    def test_問得到答案(self, 做假CLI: 做假CLI型) -> None:
        假, _ = 做假CLI()
        答 = nova.問("在嗎", 用="claude", 執行檔=假)
        assert 答.終局 is nova.終局.成功
        assert 答.文字 == "ok"

    def test_預設唯讀(self, 做假CLI: 做假CLI型) -> None:
        """忘了給 可編輯 不會變成放行。

        驗的是**白名單裡沒有會改東西的工具**，不是「工具清單剛好等於某個字串」——
        後者會在唯讀白名單從 `""` 改成 `Read,Grep,Glob` 這種正確的改動上假紅。
        """
        假, 紀錄 = 做假CLI()
        nova.問("在嗎", 用="claude", 執行檔=假)
        參數 = json.loads(紀錄.read_text(encoding="utf-8"))["argv"]
        工具 = 參數[參數.index("--tools") + 1]
        assert not ({"Write", "Edit", "Bash"} & set(工具.split(","))), f"預設放行了：{工具}"
        assert "--permission-mode" not in 參數

    def test_可編輯要明講(self, 做假CLI: 做假CLI型) -> None:
        假, 紀錄 = 做假CLI()
        nova.問("在嗎", 用="claude", 執行檔=假, 可編輯=True)
        參數 = json.loads(紀錄.read_text(encoding="utf-8"))["argv"]
        assert "--permission-mode" in 參數

    def test_不認得的家要當場炸(self, 做假CLI: 做假CLI型) -> None:
        假, _ = 做假CLI()
        with pytest.raises(ValueError, match="不認得"):
            nova.問("在嗎", 用="不存在的家", 執行檔=假)


class Test派工:
    def test_自己審自己要擋(self) -> None:
        with pytest.raises(ValueError, match="換一顆腦"):
            nova.派工("做點事", 用="codex", 審查用="codex")

    def test_跑完一輪(self, tmp_path: Path, 做假CLI: 做假CLI型, 翻牌判準: Path) -> None:
        做事的, _ = 做假CLI("codex")
        # 審查員一定要給判定，不然這一輪會被判成「沒給結論」而中止——
        # 那正是 test_審查沒給判定一律中止 守的行為。
        審查的, _ = 做假CLI("agy", "agy_review_pass.json")
        果 = nova.派工(
            "做點事",
            用="codex",
            審查用="agy",
            工作目錄=tmp_path,
            判準指令=[str(翻牌判準)],
            執行檔=做事的,
            審查執行檔=審查的,
        )
        assert 果.結束.代碼.value == "done", 果.結束.原因
        assert [步.階段.value for 步 in 果.軌跡] == [
            "test",
            "verify-red",
            "impl",
            "verify-green",
            "refactor",
            "verify-refactor",
            "review",
        ]

    def test_預算用完就一步都不准跑(
        self, tmp_path: Path, 做假CLI: 做假CLI型, 翻牌判準: Path
    ) -> None:
        """`最多token` 擋在**發呼叫之前**——事後才發現超支，錢已經花掉了。

        給 0 是最乾淨的證明：連第一次呼叫都不該發出去，所以假 CLI 的紀錄檔不會存在。
        """
        做事的, 做事紀錄 = 做假CLI("codex")
        審查的, _ = 做假CLI("agy", "agy_review_pass.json")
        果 = nova.派工(
            "做點事",
            用="codex",
            審查用="agy",
            工作目錄=tmp_path,
            判準指令=[str(翻牌判準)],
            執行檔=做事的,
            審查執行檔=審查的,
            最多token=0,
        )
        assert 果.結束.代碼.value == "guardrail", 果.結束.原因  # 預算生效是護欄不是壞掉
        assert "token" in 果.結束.原因
        assert not 做事紀錄.exists(), "預算是 0 卻還是叫了模型"

    def test_執行檔不准誤用到審查那家(
        self, tmp_path: Path, 做假CLI: 做假CLI型, 翻牌判準: Path
    ) -> None:
        """`執行檔` 是給 `用` 那家的。拿它去跑 `審查用` 那家＝跑錯二進位。

        原本兩家共用同一個 `執行檔`，`派工(用="codex", 審查用="agy", 執行檔=codex路徑)`
        會讓 agy 跑 codex 的二進位——假 CLI 不會抱怨，真的跑才會爆。
        """
        做事的, 做事紀錄 = 做假CLI("codex")
        審查的, 審查紀錄 = 做假CLI("agy", "agy_review_pass.json")
        nova.派工(
            "做點事",
            用="codex",
            審查用="agy",
            工作目錄=tmp_path,
            判準指令=[str(翻牌判準)],
            執行檔=做事的,
            審查執行檔=審查的,
        )
        assert 審查紀錄.exists(), "審查那家根本沒被叫到"
        assert json.loads(審查紀錄.read_text(encoding="utf-8"))["who"] == str(審查的)
        assert json.loads(做事紀錄.read_text(encoding="utf-8"))["who"] == str(做事的)


def test_門面很小() -> None:
    """門面要小。多匯出一個名字就是多一份對外承諾。

    這份清單**只能被刻意加長**：使用者要求開額度窗口時加了四個
    （`額度` 與它回傳的三個型別——呼叫端要標型別就得拿得到）。
    不准用「讓 `__all__` 對 `in` 說謊」那種方式繞過這支——
    用規避換來的綠是假綠。
    """
    assert set(nova.__all__) == {
        "__version__",
        "問",
        "派工",
        "回應",
        "工作流結果",
        "終局",
        "失敗代碼",
        "權限",
        "額度",
        "額度快照",
        "家族額度",
        "視窗",
    }


class Test接力:
    """`用` 給一串就是接力：前一顆失敗換下一顆。"""

    def test_一串裡第一顆掛了換第二顆(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        壞的 = tmp_path / "壞的"
        壞的.write_text("#!/bin/sh\nexit 2\n")  # 結束碼 2 = 用法錯誤 = 確定失敗
        壞的.chmod(壞的.stat().st_mode | stat.S_IEXEC)
        好的, _ = 做假CLI("agy")
        答 = nova.問("在嗎", 用=["codex", "agy"], 執行檔={"codex": 壞的, "agy": 好的})
        assert 答.終局 is nova.終局.成功
        assert 答.文字 == "ok\n"

    def test_逗號分隔也算一串(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        """從命令列傳進來的形狀。"""
        壞的 = tmp_path / "壞的"
        壞的.write_text("#!/bin/sh\nexit 2\n")
        壞的.chmod(壞的.stat().st_mode | stat.S_IEXEC)
        好的, _ = 做假CLI("agy")
        答 = nova.問("在嗎", 用="codex,agy", 執行檔={"codex": 壞的, "agy": 好的})
        assert 答.終局 is nova.終局.成功

    def test_全掛了要留下試過誰(self, tmp_path: Path) -> None:
        壞的 = tmp_path / "壞的"
        壞的.write_text("#!/bin/sh\nexit 2\n")
        壞的.chmod(壞的.stat().st_mode | stat.S_IEXEC)
        答 = nova.問("在嗎", 用="codex,agy", 執行檔=壞的)
        assert 答.終局 is nova.終局.確定失敗
        assert "codex:usage" in 答.文字 and "agy:usage" in 答.文字

    def test_做事與審查的鏈不准重疊(self) -> None:
        """`codex,agy` 對上 `agy` ——agy 同時做事又審自己。"""
        with pytest.raises(ValueError, match="換一顆腦"):
            nova.派工("做點事", 用="codex,agy", 審查用="agy")

    def test_空的鏈要當場炸(self) -> None:
        with pytest.raises(ValueError, match="至少要指定一家"):
            nova.問("在嗎", 用="")


class Test起點:
    """`起點` 讓「只走重構流程」跑得起來：重構 → 再驗一次綠 → 審查。

    Fowler 的微步循環本來就是**在已經全綠的 code 上**做的——
    不必每次都從「寫一支會紅的測試」開始。
    """

    def test_可以從重構階段起跑(self, tmp_path: Path, 做假CLI: 做假CLI型) -> None:
        做事的, _ = 做假CLI("codex")
        審查的, _ = 做假CLI("agy", "agy_review_pass.json")
        果 = nova.派工(
            "把角色收成一張表",
            用="codex",
            審查用="agy",
            工作目錄=tmp_path,
            判準指令=["true"],  # 重構流程的前提是本來就全綠
            執行檔=做事的,
            審查執行檔=審查的,
            起點="refactor",
        )
        assert 果.結束.代碼.value == "done", 果.結束.原因
        assert [步.階段.value for 步 in 果.軌跡] == ["refactor", "verify-refactor", "review"]

    def test_不認得的起點要當場炸(self) -> None:
        """打錯字要立刻知道，不要靜默從頭跑一輪。"""
        with pytest.raises(ValueError, match="起點"):
            nova.派工("做點事", 用="codex", 審查用="agy", 起點="隨便打的")
