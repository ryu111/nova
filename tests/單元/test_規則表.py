"""規則表本身的防護。

規則表是閘的 context（規格 §2.2 第一問）。它壞掉的方式很安靜：
代碼撞名、閘點打錯、提交閘漏了某條 CI 有的規則——都不會有人當場發現。
"""

from pathlib import Path

from nova.載體.規則表 import 建規則表
from nova.載體.閘 import 型別, 測試, 規則, 閘點清單, 靜態


def _規則表() -> list[規則]:
    return 建規則表(Path("/不存在也沒關係/建表時不該碰硬碟"))


def test_代碼不重複() -> None:
    代碼 = [條.代碼 for 條 in _規則表()]
    assert len(代碼) == len(set(代碼)), f"代碼撞名：{代碼}"


def test_代碼是ASCII() -> None:
    """代碼是跨程序 failure code，要能出現在 CI log、hook 輸出、別的工具裡。"""
    for 條 in _規則表():
        assert 條.代碼.isascii(), f"{條.代碼} 不是 ASCII"


def test_閘點都合法() -> None:
    for 條 in _規則表():
        assert 條.閘點 <= 閘點清單, f"{條.代碼} 掛到未知閘點 {條.閘點 - 閘點清單}"


def test_階段都合法() -> None:
    for 條 in _規則表():
        assert 條.階段 in (靜態, 型別, 測試), f"{條.代碼} 階段 {條.階段} 不合法"


def test_提交閘是ci閘的子集() -> None:
    """提交閘擋掉的，CI 一定也要擋——否則本地綠、推上去紅，或更糟：反過來。"""
    表 = _規則表()
    ci代碼 = {條.代碼 for 條 in 表 if "ci" in 條.閘點}
    只在提交 = {條 for 條 in 表 if "提交" in 條.閘點 and 條.代碼 not in ci代碼}
    for 條 in 只在提交:
        assert 條.涵蓋於, f"{條.代碼} 只在提交閘，CI 抓不到，也沒宣告涵蓋者"
        assert 條.涵蓋於 in ci代碼, f"{條.代碼} 宣告涵蓋於 {條.涵蓋於}，但 CI 沒有這條"


def test_每條規則都有掛閘點() -> None:
    """掛零個閘點＝永遠不會跑，比沒寫還糟——看起來有防護。"""
    for 條 in _規則表():
        assert 條.閘點, f"{條.代碼} 沒掛任何閘點"


def test_四道閘都在ci裡() -> None:
    ci代碼 = {條.代碼 for 條 in _規則表() if "ci" in 條.閘點}
    for 必要 in ("ruff-check", "ruff-format", "mypy"):
        assert 必要 in ci代碼, f"CI 缺少 {必要}"
    assert any(代碼.startswith("pytest") for 代碼 in ci代碼), "CI 沒有跑測試"


def test_三條新規則都上了() -> None:
    表 = 建規則表(Path.cwd())
    代碼 = {條.代碼 for 條 in 表}
    for 必要 in ("lang-traditional", "no-secrets", "test-count"):
        assert 必要 in 代碼, f"缺少 {必要}"


def test_涵蓋宣告不能指向自己() -> None:
    for 條 in _規則表():
        assert 條.涵蓋於 != 條.代碼, f"{條.代碼} 宣告自己涵蓋自己，等於沒宣告"


def test_兩個閘都排除真cli() -> None:
    """真 CLI 測試會燒 token、需要認證——不准溜進任何一個閘。

    忘了排除的話 CI 會在沒有認證的機器上紅，而且是紅在跟改動無關的地方。
    """
    根目錄 = Path(__file__).resolve().parents[2]
    for 條 in 建規則表(根目錄):
        if not 條.代碼.startswith("pytest"):
            continue
        指令 = getattr(條.檢查, "__closure__", None)
        assert 指令 is not None, f"{條.代碼} 不是包出來的外部指令，這支測試要改寫"
    原始碼 = (根目錄 / "src" / "nova" / "載體" / "規則表.py").read_text(encoding="utf-8")
    pytest行 = [
        行 for 行 in 原始碼.splitlines() if '"pytest"' in 行 or "pytest" in 行 and '"-m"' in 行
    ]
    帶標記的 = [行 for 行 in pytest行 if '"-m"' in 行]
    assert 帶標記的, "找不到帶 -m 的 pytest 規則"
    for 行 in 帶標記的:
        assert "not 真cli" in 行, f"這條 pytest 規則沒排除真cli：{行.strip()}"
