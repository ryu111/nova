"""巡：吃「專案 ＋ 現在」，算出哪些接續票該被叫醒、哪些是孤兒、哪些只給人看。

## 為什麼判定要跟發射分開

22a-2 之後接續票帶得動 `不早於`，收件匣在時刻之前不放行——**但沒有人定期
醒來去看它到期了沒**。票躺著，時鐘走過去，什麼都沒發生。

補上「醒來」這件事的第一半是**判定**：候選只從 git 登記正向推，四個集合
純算出來，一條線都不發射。判定是純函式才驗得動——「不早於還沒到」與
「到了」的差別只是參數上的一個 `datetime`，測試自己把時鐘翻面就好，
不必等十五分鐘、也不必去戳真的排程。

## 為什麼「查不到在不在跑」不等於「沒在跑」

`是否在跑` 是三態：True／False／`None`（清查不到）。`None` 當作沒在跑的話，
巡就會在一棵**可能正在跑**的樹上叫醒同一張票，兩個工作流搶同一棵樹。
拿 flock 當替代也不行：拿不到鎖那條路照樣會把 `狀態.json` 覆寫成 busy，
把剛寫進去的 `resume_not_before` 洗掉。所以三態裡只有 False 能放行。
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nova.契約.線觀測 import 程序清查
from nova.載體.巡 import 巡一輪
from nova.載體.已處理 import 列出成果
from nova.載體.帳本 import 預設帳本目錄
from nova.載體.收件 import 收件目錄, 標成孤兒

#: 檔名第一段那個 UTC 時戳的形狀（`收件._檔名時戳`）。
_檔名時戳形狀 = "%Y%m%dT%H%M%SZ"

#: 沒在跑：清查得到、這棵樹上沒有 nova、也沒有定位不到工作目錄的程序。
_沒在跑 = 程序清查(程序們=[], 有無法定位工作目錄的程序=False)


def _檔名時戳(當下: datetime) -> str:
    return 當下.strftime(_檔名時戳形狀)


def _不早於時戳(當下: datetime) -> str:
    """`不早於` 那一格的形狀：**帶時區的 ISO**，跟 22a-2 寫進票裡的一樣。

    22a-2 的 `時候到了嗎` 走 `datetime.fromisoformat`，而且不帶時區的時戳
    一律當「可以」。這裡要是改用檔名那種形狀，讀者解不動就變成「沒有不早於」
    ——時間門形同不存在，測試卻會綠。所以形狀要跟寫票的那一端對齊。
    """
    return 當下.isoformat()


@dataclass(frozen=True, slots=True)
class _接續標記:
    """票上那一行 `<!--nova:接續 ...-->`。`不早於` 沒給就是沒有時刻限制。"""

    輪次: int
    上一輪: str
    不早於: datetime | None = None


def _落一張票(
    匣: Path,
    *,
    落檔時刻: datetime,
    標籤: str,
    接續: _接續標記 | None = None,
) -> Path:
    """照 `丟一件`／`接著排` 的檔名與內容形狀，手工放一張票進收件匣。

    手工放是刻意的：`不早於` 那一格要餵得進「還沒到」與「到了」兩種值，
    而落票的 API 只寫得出「現在」。
    """
    匣.mkdir(parents=True, exist_ok=True)
    內文 = f"# {標籤}\n"
    if 接續 is not None:
        欄位 = f"輪次={接續.輪次} 上一輪={接續.上一輪}"
        if 接續.不早於 is not None:
            欄位 += f" 不早於={_不早於時戳(接續.不早於)}"
        內文 += f"\n<!--nova:接續 {欄位}-->\n上一輪撞到上限停下。\n"
    落點 = 匣 / f"{_檔名時戳(落檔時刻)}-時鐘-{標籤}-abc123.md"
    落點.write_text(內文, encoding="utf-8")
    return 落點


def _記一筆帳(樹: Path, 執行識別碼: str) -> None:
    """在那棵樹的帳本目錄放一本帳，讓「該樹最新那筆」有得比。"""
    目錄 = 預設帳本目錄(樹)
    目錄.mkdir(parents=True, exist_ok=True)
    (目錄 / f"{執行識別碼}.jsonl").write_text('{"事":"開工"}\n', encoding="utf-8")


@pytest.fixture
def 派工樹(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """一棵登記在 git 裡、路徑真的存在的派工樹，主工作區排在它前面。

    `工作樹們` 從 `巡` 的名字空間換掉：候選**只從 git 登記正向推**，
    這支 fixture 就是那份登記的替身（換得掉也順便釘住「不 glob 狀態根」）。
    """
    專案 = tmp_path / "專案"
    樹 = tmp_path / "樹-一"
    for 路 in (專案, 樹):
        路.mkdir()
    monkeypatch.setattr("nova.載體.巡.工作樹們", lambda _: [(專案, "main"), (樹, "線一")])
    return 樹


@pytest.fixture
def 專案(派工樹: Path) -> Path:
    """`巡一輪` 要吃的專案路徑。真的是誰不重要——樹是從登記推出來的。"""
    return 派工樹.parent / "專案"


def test_不早於還沒到不算到期到了才算(專案: Path, 派工樹: Path) -> None:
    """**時刻沒到就不放行，到了就放行。** 同一張票，差別只有「現在」。"""
    最新 = "20260903T020000Z-bbbbbb"
    _記一筆帳(派工樹, "20260903T010000Z-aaaaaa")
    _記一筆帳(派工樹, 最新)
    現在 = datetime(2026, 9, 3, 3, 0, tzinfo=UTC)
    票 = _落一張票(
        收件目錄(派工樹),
        落檔時刻=現在 - timedelta(minutes=15),
        標籤="等時刻的",
        接續=_接續標記(輪次=2, 上一輪=最新, 不早於=現在 + timedelta(minutes=10)),
    )

    還沒到 = 巡一輪(專案, 現在=現在, 清查=_沒在跑)
    到了 = 巡一輪(專案, 現在=現在 + timedelta(minutes=20), 清查=_沒在跑)

    assert 票 not in {候選.票 for 候選 in 還沒到.到期}, "不早於還沒到，這張不准算到期"
    assert 票 in {候選.票 for 候選 in 到了.到期}, "時刻過了就該算到期"
    assert {候選.樹 for 候選 in 到了.到期} == {派工樹}, "到期那筆要說得出是哪棵樹的"


def test_上一輪過期的算孤兒而沒有標記的只列不叫(專案: Path, 派工樹: Path) -> None:
    """**兩種都不准叫，但理由不同，所以分兩個集合。**

    上一輪不是該樹帳本最新那筆＝那條線後來又跑過別的，這張票接的是舊世界；
    沒有接續標記＝人手放的票，人手起。
    """
    _記一筆帳(派工樹, "20260903T020000Z-bbbbbb")
    現在 = datetime(2026, 9, 3, 3, 0, tzinfo=UTC)
    匣 = 收件目錄(派工樹)
    過期的 = _落一張票(
        匣,
        落檔時刻=現在 - timedelta(minutes=30),
        標籤="接舊世界的",
        接續=_接續標記(輪次=2, 上一輪="20260903T010000Z-aaaaaa"),
    )
    人手放的 = _落一張票(匣, 落檔時刻=現在 - timedelta(minutes=5), 標籤="人手放的")

    一份 = 巡一輪(專案, 現在=現在, 清查=_沒在跑)

    assert {候選.票 for 候選 in 一份.孤兒} == {過期的}, "上一輪不是最新那筆的算孤兒"
    assert {候選.票 for 候選 in 一份.首輪票} == {人手放的}, "沒有接續標記的只列不叫"
    assert {候選.票 for 候選 in 一份.到期} == set(), "這兩張都不准進到期"


def test_查不到在不在跑就不算到期(專案: Path, 派工樹: Path) -> None:
    """**三態裡只有 False 能放行。** 查不到就閉嘴，而且要讓人看見查不到。"""
    最新 = "20260903T020000Z-bbbbbb"
    _記一筆帳(派工樹, 最新)
    現在 = datetime(2026, 9, 3, 3, 0, tzinfo=UTC)
    票 = _落一張票(
        收件目錄(派工樹),
        落檔時刻=現在 - timedelta(minutes=15),
        標籤="時刻早就到的",
        接續=_接續標記(輪次=2, 上一輪=最新, 不早於=現在 - timedelta(minutes=5)),
    )

    查不到 = 巡一輪(專案, 現在=現在, 清查=None)
    清查得到 = 巡一輪(專案, 現在=現在, 清查=_沒在跑)

    assert 票 not in {候選.票 for 候選 in 查不到.到期}, "查不到在不在跑就不准算到期"
    assert "查不到" in "\n".join(查不到.訊息們), "查不到要印出來，不准安靜地不叫"
    assert 票 in {候選.票 for 候選 in 清查得到.到期}, "同一張票在清查得到時是到期的"


def test_標成孤兒是rename不是刪(tmp_path: Path) -> None:
    """**孤兒只搬不刪，而且搬完對成果的讀者隱形。**

    `.orphan` 落在 `已處理/` 底下：內容留著（人回頭看得到票長什麼樣），
    但 `列出成果` 只撿 `*.json`，所以它不會被當成一筆成果混進帳裡。
    """
    匣 = tmp_path / "收件"
    匣.mkdir()
    已處理 = tmp_path / "已處理"
    票 = 匣 / "20260903T024500Z-時鐘-孤的-abc123.md"
    票.write_text("# 孤的\n", encoding="utf-8")

    落點 = 標成孤兒(票, 已處理=已處理)

    assert 落點 == 已處理 / "20260903T024500Z-時鐘-孤的-abc123.md.orphan"
    assert 落點.read_text(encoding="utf-8") == "# 孤的\n", "不刪：內容要原封不動搬過去"
    assert not 票.exists(), "原處要搬走，不然下一輪又數它一次"
    assert 列出成果(已處理) == [], "`.orphan` 對成果的讀者隱形"
