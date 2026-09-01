"""「換一顆腦」的判準是對話識別碼，不是家族名。

獨立性來自 context 隔離，不是模型權重不同：
- 同一家開新對話（new session）做事與審查，沒有共享 context，是合法的審查者。
- 做事與審查續接到「同一個對話識別碼」，共享了 context，才是自寫自評，一定要擋。
"""

import inspect
from collections.abc import Callable
from pathlib import Path

import nova

做假CLI型 = Callable[..., tuple[Path, Path]]


class Test換腦判準:
    def test_同一家開新對話可做做事與審查(
        self, tmp_path: Path, 做假CLI: 做假CLI型, 翻牌判準: Path
    ) -> None:
        """同一個家族（例如 agy）在未續接同對話時，各自是新 session，應可順利跑完。"""
        做事的, _ = 做假CLI("agy")
        審查的, _ = 做假CLI("agy", "agy_review_pass.json")
        果 = nova.派工(
            "做點事",
            用="agy",
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

    def test_派工的公開簽章不准長出續接類參數(self) -> None:
        """**這一條是「還沒發生的洞」的把關器。**

        現在 `nova.派工` 收不到續接，所以做事與審查一定是兩個新對話——
        保證落在**結構上**，不是落在某個 if 裡（`tests/單元/test_換腦判準.py`
        的 `test_角色結構上不可能續接到同一個對話` 守角色那一層，
        這支守公開 API 這一層）。

        問題是：**那天有人給 `派工` 加上 `續接`，結構性保證就無聲消失了**——
        兩邊都續接到同一個識別碼就是自寫自評，而沒有任何測試會紅。

        所以這支釘的是簽章本身。要加續接不是不行，但**必須跟同對話檢查
        一起加**，而這支會逼那件事發生：它紅的時候訊息就寫著該怎麼做。
        """
        參數們 = set(inspect.signature(nova.派工).parameters)
        續接類 = sorted(名 for 名 in 參數們 if "續接" in 名 or "對話" in 名)

        assert not 續接類, (
            f"`nova.派工` 長出了 {續接類}——做事與審查續接到同一個對話就是自寫自評"
            "（CLAUDE.md 硬規則二）。要加這個參數，就要在同一格加上"
            "「做事與審查的對話識別碼不准相同」的檢查，並把這支測試改成驗那個檢查。"
        )

    def test_接力鏈包含同一家只要是新對話也可以(
        self, tmp_path: Path, 做假CLI: 做假CLI型, 翻牌判準: Path
    ) -> None:
        """做事鏈 `codex,agy` 與審查用 `agy`，在未續接同對話時不應被家族名攔截。"""
        做事的, _ = 做假CLI("codex")
        審查的, _ = 做假CLI("agy", "agy_review_pass.json")
        果 = nova.派工(
            "做點事",
            用="codex,agy",
            審查用="agy",
            工作目錄=tmp_path,
            判準指令=[str(翻牌判準)],
            執行檔=做事的,
            審查執行檔=審查的,
        )
        assert 果.結束.代碼.value == "done", 果.結束.原因
