"""閘紅落成收件票的行為契約。"""

from pathlib import Path

import pytest

from nova.契約.檢查結果 import 檢查結果
from nova.契約.觸發 import 喚醒來源
from nova.載體.收件 import 待處理, 處理中目錄, 讀出驗收
from nova.載體.閘紅成票 import 落成閘紅票


@pytest.fixture
def 範例閘紅結果() -> 檢查結果:
    return 檢查結果(
        代碼="pytest-parallel",
        名稱="全測試（平行，不含 serial）",
        通過=False,
        負責層="載體",
        證據=(
            "tests/單元/test_閘.py::test_證據原樣帶出來\n"
            "tests/單元/test_閘.py:31: AssertionError: 第 3 行有非繁體字"
        ),
    )


def test_main上排程觸發的閘紅會落成可追查收件票(tmp_path: Path, 範例閘紅結果: 檢查結果) -> None:
    """只有權威 repo 的 main、排程喚醒且閘紅，才進入「紅 → 票」流程。"""
    落點 = 落成閘紅票(
        結果=範例閘紅結果,
        閘點="ci",
        分支="main",
        權威repo=True,
        喚醒來源=喚醒來源.排程到期,
        commit="0123456789abcdef0123456789abcdef01234567",
        發生時間="2026-08-30T15:04:05.123Z",
        目錄=tmp_path,
    )

    assert 落點 is not None
    assert 待處理(tmp_path) == [落點]
    assert "-schedule-" in 落點.name
    assert 落點.read_text(encoding="utf-8") == (
        "# 閘紅：pytest-parallel\n\n"
        "- 閘點：ci\n"
        "- 分支：main\n"
        "- commit：0123456789abcdef0123456789abcdef01234567\n"
        "- 發生時間：2026-08-30T15:04:05.123Z\n\n"
        "<!--nova:驗收 uv run nova 閘 ci-->\n\n"
        "## 紅在哪\n\n"
        "tests/單元/test_閘.py::test_證據原樣帶出來\n"
        "tests/單元/test_閘.py:31: AssertionError: 第 3 行有非繁體字\n"
    )


@pytest.mark.parametrize(
    ("分支", "權威repo", "來源"),
    [
        ("feat-1", True, 喚醒來源.排程到期),  # 開發分支的紅是常態（TDD紅階段）
        ("main", False, 喚醒來源.排程到期),  # 非權威 repo（如 worktree）
        ("main", True, 喚醒來源.人手動敲),  # 人手動敲已有即時終端輸出
        ("main", True, 喚醒來源.收件檔出現),  # 收件檔觸發的工作流中跑閘不遞迴生票
    ],
)
def test_不符合現場條件的閘紅絕對不落成票(
    tmp_path: Path,
    範例閘紅結果: 檢查結果,
    分支: str,
    權威repo: bool,
    來源: 喚醒來源,
) -> None:
    """守住不被灌爆的風險：非 main、非權威 repo、非排程喚醒一律不落票。"""
    落點 = 落成閘紅票(
        結果=範例閘紅結果,
        閘點="ci",
        分支=分支,
        權威repo=權威repo,
        喚醒來源=來源,
        commit="0123456789abcdef0123456789abcdef01234567",
        發生時間="2026-08-30T15:04:05.123Z",
        目錄=tmp_path,
    )

    assert 落點 is None
    assert 待處理(tmp_path) == []


def test_閘綠通過的不落成票(tmp_path: Path) -> None:
    """閘規則綠了（通過）絕對不落票。"""
    綠 = 檢查結果(代碼="ruff-check", 名稱="格式與型別", 通過=True, 負責層="載體", 證據="")
    落點 = 落成閘紅票(
        結果=綠,
        閘點="ci",
        分支="main",
        權威repo=True,
        喚醒來源=喚醒來源.排程到期,
        commit="0123456789abcdef0123456789abcdef01234567",
        發生時間="2026-08-30T15:04:05.123Z",
        目錄=tmp_path,
    )

    assert 落點 is None
    assert 待處理(tmp_path) == []


def test_待處理已有同一條閘紅票不准重複落成(tmp_path: Path, 範例閘紅結果: 檢查結果) -> None:
    """收件匣裡已有同一個閘點同一條閘的票時，不重複落票避免灌爆。"""
    第一張 = 落成閘紅票(
        結果=範例閘紅結果,
        閘點="ci",
        分支="main",
        權威repo=True,
        喚醒來源=喚醒來源.排程到期,
        commit="0123456789abcdef0123456789abcdef01234567",
        發生時間="2026-08-30T15:04:05.123Z",
        目錄=tmp_path,
    )
    assert 第一張 is not None
    assert len(待處理(tmp_path)) == 1

    第二張 = 落成閘紅票(
        結果=範例閘紅結果,
        閘點="ci",
        分支="main",
        權威repo=True,
        喚醒來源=喚醒來源.排程到期,
        commit="0123456789abcdef0123456789abcdef01234567",
        發生時間="2026-08-30T15:19:05.123Z",
        目錄=tmp_path,
    )
    assert 第二張 is None
    assert len(待處理(tmp_path)) == 1


def test_處理中已有同一條閘紅票不准重複落成(tmp_path: Path, 範例閘紅結果: 檢查結果) -> None:
    """票已經被工作流撿走正在處理中時，排程再次跑閘也不重複落票。"""
    第一張 = 落成閘紅票(
        結果=範例閘紅結果,
        閘點="ci",
        分支="main",
        權威repo=True,
        喚醒來源=喚醒來源.排程到期,
        commit="0123456789abcdef0123456789abcdef01234567",
        發生時間="2026-08-30T15:04:05.123Z",
        目錄=tmp_path,
    )
    assert 第一張 is not None

    處理中 = 處理中目錄(tmp_path)
    處理中.mkdir(parents=True, exist_ok=True)
    移至 = 處理中 / f"12345-{第一張.name}"
    第一張.rename(移至)
    assert 待處理(tmp_path) == []

    第二張 = 落成閘紅票(
        結果=範例閘紅結果,
        閘點="ci",
        分支="main",
        權威repo=True,
        喚醒來源=喚醒來源.排程到期,
        commit="0123456789abcdef0123456789abcdef01234567",
        發生時間="2026-08-30T15:19:05.123Z",
        目錄=tmp_path,
    )
    assert 第二張 is None
    assert 待處理(tmp_path) == []


@pytest.mark.parametrize("閘點", ["提交", "ci"])
def test_閘紅票的驗收指向紅掉的那個閘(閘點: str, 範例閘紅結果: 檢查結果, tmp_path: Path) -> None:
    """票裡的驗收要指向**紅掉的那個閘**，不是寫死某一個。

    寫死的話 CI 紅掉會落成一張「跑提交閘」的票——那個閘本來就是綠的，
    於是這張票開跑當下就已經「驗收通過」，一件真的紅著的事被判成做完了。

    **兩個閘點都要測**：只測一個的話，寫死成那一個的實作照樣綠，
    這支測試就守不到任何東西（實測過，第一版就是這樣被變異刀活著穿過去的）。
    """
    落點 = 落成閘紅票(
        結果=範例閘紅結果,
        閘點=閘點,
        分支="main",
        權威repo=True,
        喚醒來源=喚醒來源.排程到期,
        commit="0123456789abcdef0123456789abcdef01234567",
        發生時間="2026-08-30T15:04:05.123Z",
        目錄=tmp_path,
    )

    assert 落點 is not None
    assert 讀出驗收(落點.read_text(encoding="utf-8")) == (f"uv run nova 閘 {閘點}",)
