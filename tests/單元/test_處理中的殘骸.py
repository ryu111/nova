"""`處理中/` 的殘骸要有人看得見，而且**只准看，不准動**。

`收件.py` 自己的 docstring 寫著「程序被殺掉的話會留在這裡，那是誠實」——
誠實只完成了一半：東西留著了，但沒有任何一條路把它講出來。
`待處理()` 只看收件根目錄，所以一件被殺掉的工作在 `nova 狀態` 上
長得跟「沒有這件事」一模一樣，而那正是本專案最貴的那種看不見。

會碰硬碟但不 fork 子程序，所以住單元層（CLAUDE.md 的分層判準是子程序，不是 I/O）。

**這一格是唯讀查詢。** 自動清理是危險操作——殘骸代表一件做到一半的工作，
副作用可能已經發生，要不要清是人的決定。所以本檔第一條測的不是「查得到」，
是「查完之後那格一個位元組都沒變」。
"""

import inspect
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nova.載體.收件 import 卡住的, 處理中目錄

#: 拿來當「久到一定算卡住」的年紀。比任何合理的預設都大。
_很久以前 = timedelta(days=7)


def _擺一件殘骸(
    收件: Path, 檔名: str, 內容: str = "把某件事做完\n", *, 多久以前: timedelta
) -> Path:
    """在 `處理中/` 放一個檔，並把 mtime 調到指定的年紀。

    年紀走 mtime 不走檔名時戳：檔名時戳是「這張票什麼時候被造出來」，
    而卡住要問的是「它什麼時候被收下」——排程票可能躺了三天才被撿起來。
    """
    處理中 = 處理中目錄(收件)
    處理中.mkdir(parents=True, exist_ok=True)
    路徑 = 處理中 / 檔名
    路徑.write_text(內容, encoding="utf-8")
    那時候 = time.time() - 多久以前.total_seconds()
    os.utime(路徑, (那時候, 那時候))
    return 路徑


def _拍快照(目錄: Path) -> dict[str, tuple[str, int]]:
    """(檔名 → 內容, mtime 奈秒)。呼叫前後各拍一張，用來證明沒有人動過。"""
    return {
        路.name: (路.read_text(encoding="utf-8"), 路.stat().st_mtime_ns)
        for 路 in sorted(目錄.iterdir())
    }


class Test唯讀:
    """**最重要的一條**：這一格不搬、不刪、不改，一個檔都不准。"""

    def test_查完之後處理中的內容一個字都沒變(self, tmp_path: Path) -> None:
        """自動清理是危險操作：那件工作可能已經做了一半，副作用已經發生。

        查詢順手清掉的話，人會失去「這件到底做到哪」的唯一線索，
        而且是在他還不知道發生過什麼的時候失去。
        """
        _擺一件殘骸(
            tmp_path, "111-20260101T000000Z-typed-甲-aaaaaa.md", "甲的題目\n", 多久以前=_很久以前
        )
        _擺一件殘骸(
            tmp_path, "222-20260101T000000Z-file-乙-bbbbbb.md", "乙的題目\n", 多久以前=_很久以前
        )
        處理中 = 處理中目錄(tmp_path)
        之前 = _拍快照(處理中)

        清單 = 卡住的(tmp_path, 多久算卡住=timedelta(0))

        assert len(清單) == 2
        assert _拍快照(處理中) == 之前


class Test每一筆帶得出什麼:
    def test_檔名收下時間卡了多久與原本的題目(self, tmp_path: Path) -> None:
        """四個欄位缺一個都不夠：沒有題目就只是一串檔名，人看不出該不該重跑。"""
        檔名 = "4242-20260101T000000Z-typed-把某件事做完-abc123.md"
        路徑 = _擺一件殘骸(tmp_path, 檔名, "把某件事做完\n", 多久以前=timedelta(minutes=90))

        一件 = 卡住的(tmp_path, 多久算卡住=timedelta(minutes=30))[0]

        assert 一件.檔名 == 檔名
        assert 一件.收下時間 == datetime.fromtimestamp(路徑.stat().st_mtime, UTC)
        assert 一件.收下時間.tzinfo is not None
        assert timedelta(minutes=89) < 一件.卡了多久 < timedelta(minutes=91)
        assert 一件.題目 == "把某件事做完"

    def test_接續票只帶原本的題目不帶前情(self, tmp_path: Path) -> None:
        """前情是模型上一輪講的話，混進題目裡人會以為那是他交代的事。"""
        內容 = (
            "把某件事做完\n\n"
            "<!--nova:接續 輪次=2 上一輪=abc-->\n"
            "上一輪撞到上限停下，這一輪接著做，不要從頭來。\n\n"
            "上一輪改了三個檔\n"
        )
        _擺一件殘骸(tmp_path, "7-20260101T000000Z-typed-某件事-ddd111.md", 內容, 多久以前=_很久以前)

        一件 = 卡住的(tmp_path, 多久算卡住=timedelta(0))[0]

        assert 一件.題目 == "把某件事做完"
        assert "上一輪改了三個檔" not in 一件.題目


class Test多久算卡住:
    def test_剛收下的不算卡住(self, tmp_path: Path) -> None:
        """正在跑的那件天天出現在清單上，人就會學會忽略這個清單。

        而一個被忽略的警示清單，等於這個功能不存在——只是還多欠一份維護。
        """
        _擺一件殘骸(
            tmp_path, "9-20260101T000000Z-typed-剛收下-eee222.md", 多久以前=timedelta(seconds=1)
        )

        assert 卡住的(tmp_path) == []

    def test_預設有值而且門檻可以改(self, tmp_path: Path) -> None:
        """預設要擋得住正在跑的那件；同時要讓人依自己的工作長度調鬆或調緊。"""
        預設 = inspect.signature(卡住的).parameters["多久算卡住"].default
        assert isinstance(預設, timedelta)
        assert 預設 > timedelta(0)

        _擺一件殘骸(
            tmp_path, "5-20260101T000000Z-typed-十分鐘前-fff333.md", 多久以前=timedelta(minutes=10)
        )

        assert 卡住的(tmp_path, 多久算卡住=timedelta(minutes=5)) != []
        assert 卡住的(tmp_path, 多久算卡住=timedelta(minutes=20)) == []

    def test_預設值的理由寫在docstring裡(self) -> None:
        """一個沒寫理由的門檻，下一個人只會照自己的直覺改掉它。

        機械判準：docstring 要同時講到「預設」與一個因果詞——
        擋不住寫得爛的解釋，但擋得住完全沒解釋。
        """
        文件 = inspect.getdoc(卡住的) or ""

        assert "預設" in 文件
        assert any(因果 in 文件 for 因果 in ("因為", "理由", "不然", "否則", "為什麼"))


class Test讀不到的時候:
    def test_目錄不存在回空list(self, tmp_path: Path) -> None:
        """第一次跑的時候本來就還沒有 `處理中/`，那不是異常。"""
        沒動過的收件 = tmp_path / "還沒用過"
        沒動過的收件.mkdir()

        assert 卡住的(沒動過的收件) == []

    @pytest.mark.skipif(os.geteuid() == 0, reason="root 讀得動 0o000 的檔，這條驗不了")
    def test_讀不動的跳過但數得出跳過幾個(self, tmp_path: Path) -> None:
        """跳過是對的（權限、被刪到一半），**靜靜地跳過不是**。

        數字要出得來：清單上兩件、實際上三件的差距，
        正是「看起來沒事」與「真的沒事」之間唯一的線索。
        """
        _擺一件殘骸(tmp_path, "1-20260101T000000Z-typed-讀得動-ggg444.md", 多久以前=_很久以前)
        壞的 = _擺一件殘骸(
            tmp_path, "2-20260101T000000Z-typed-讀不動-hhh555.md", 多久以前=_很久以前
        )
        壞的.chmod(0o000)

        清單 = 卡住的(tmp_path, 多久算卡住=timedelta(0))

        assert [一件.檔名 for 一件 in 清單] == ["1-20260101T000000Z-typed-讀得動-ggg444.md"]
        assert 清單.跳過幾個 == 1

    def test_沒有跳過的時候是零(self, tmp_path: Path) -> None:
        """`跳過幾個` 永遠拿得到，不是「出事才有」的欄位——否則呼叫端要先問有沒有。"""
        _擺一件殘骸(tmp_path, "3-20260101T000000Z-typed-好好的-iii666.md", 多久以前=_很久以前)

        assert 卡住的(tmp_path, 多久算卡住=timedelta(0)).跳過幾個 == 0
