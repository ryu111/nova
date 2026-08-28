"""閘的核心行為：挑規則、判定、把證據原樣帶出來。"""

import pytest

from nova.載體.閘 import 規則, 跑閘


def _假規則(代碼: str, 閘點: list[str], 通過: bool, 證據: str = "假證據") -> 規則:
    return 規則(
        代碼=代碼,
        名稱=f"假規則 {代碼}",
        閘點=frozenset(閘點),
        負責層="載體",
        檢查=lambda: (通過, 證據),
    )


def test_只跑掛在該閘點的規則() -> None:
    規則表 = [_假規則("a", ["提交"], True), _假規則("b", ["ci"], True)]
    assert [結果.代碼 for 結果 in 跑閘("提交", 規則表)] == ["a"]


def test_同一條規則可以掛多個閘點() -> None:
    規則表 = [_假規則("a", ["提交", "ci"], True)]
    assert len(跑閘("提交", 規則表)) == 1
    assert len(跑閘("ci", 規則表)) == 1


def test_證據原樣帶出來() -> None:
    """回饋要具體。只說「紅了」不可行動。"""
    結果 = 跑閘("提交", [_假規則("a", ["提交"], False, "第 3 行有非繁體字")])[0]
    assert 結果.通過 is False
    assert "第 3 行" in 結果.證據
    assert 結果.負責層 == "載體"


def test_規則爆炸算紅不算過() -> None:
    """fail-closed：檢查自己壞掉時不准放行，否則保證會靜默消失。"""

    def 會爆的檢查() -> tuple[bool, str]:
        訊息 = "檢查自己壞了"
        raise RuntimeError(訊息)

    規則表 = [
        規則(
            代碼="爆",
            名稱="會爆的規則",
            閘點=frozenset(["提交"]),
            負責層="載體",
            檢查=會爆的檢查,
        )
    ]
    結果 = 跑閘("提交", 規則表)[0]
    assert 結果.通過 is False
    assert "檢查自己壞了" in 結果.證據


def test_未知閘點要當場報錯() -> None:
    """打錯閘點名字時，靜默跑零條規則然後全綠是最危險的失敗方式。"""
    with pytest.raises(ValueError, match="未知的閘點"):
        跑閘("不存在的閘點", [_假規則("a", ["提交"], True)])


def _階段規則(代碼: str, 階段: int, 通過: bool, 紀錄: list[str]) -> 規則:
    def 檢查() -> tuple[bool, str]:
        紀錄.append(代碼)
        return 通過, ""

    return 規則(
        代碼=代碼,
        名稱=f"階段 {階段} 的 {代碼}",
        閘點=frozenset(["提交"]),
        負責層="載體",
        檢查=檢查,
        階段=階段,
    )


def test_依階段由小到大執行() -> None:
    """快的先跑、重的後跑，而且一次只跑一條——避免同時吃滿 CPU 互搶到紅燈。"""
    紀錄: list[str] = []
    規則表 = [
        _階段規則("慢", 3, True, 紀錄),
        _階段規則("快", 1, True, 紀錄),
        _階段規則("中", 2, True, 紀錄),
    ]
    跑閘("提交", 規則表)
    assert 紀錄 == ["快", "中", "慢"]


def test_提前停止時後面的階段不跑() -> None:
    """TDD 內圈要的是第一個紅就停，不要等三分鐘的測試跑完才看到 lint 錯字。"""
    紀錄: list[str] = []
    規則表 = [_階段規則("快", 1, False, 紀錄), _階段規則("慢", 3, True, 紀錄)]
    結果 = 跑閘("提交", 規則表, 提前停止=True)
    assert 紀錄 == ["快"]
    assert [r.代碼 for r in 結果] == ["快"]


def test_不提前停止時全部跑完() -> None:
    """CI 要的是全貌：一次看到所有紅的，不要修一條推一次。"""
    紀錄: list[str] = []
    規則表 = [_階段規則("快", 1, False, 紀錄), _階段規則("慢", 3, False, 紀錄)]
    結果 = 跑閘("提交", 規則表, 提前停止=False)
    assert 紀錄 == ["快", "慢"]
    assert len(結果) == 2


def test_同階段內維持宣告順序() -> None:
    紀錄: list[str] = []
    規則表 = [_階段規則("甲", 1, True, 紀錄), _階段規則("乙", 1, True, 紀錄)]
    跑閘("提交", 規則表)
    assert 紀錄 == ["甲", "乙"]
