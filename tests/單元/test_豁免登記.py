"""ruff 豁免登記的純判定：設定與登記表不能悄悄漂移。"""

from nova.載體.豁免登記 import 判定ruff豁免, 期望ruff豁免

_加豁免不是修lint = "加豁免不是修 lint。要加，先改登記表並說明理由"


def test_豁免跟登記表一致時是綠的() -> None:
    綠, 訊息 = 判定ruff豁免(期望ruff豁免)

    assert 綠 is True
    assert 訊息 == "ruff 豁免符合登記表"


def test_多一條沒登記的豁免時指名多了哪一條() -> None:
    綠, 訊息 = 判定ruff豁免(期望ruff豁免 | frozenset({"ignore:F401"}))

    assert 綠 is False
    assert "多了：ignore:F401" in 訊息
    assert _加豁免不是修lint in 訊息


def test_少一條登記過的豁免時指名少了哪一條() -> None:
    綠, 訊息 = 判定ruff豁免(期望ruff豁免 - frozenset({"ignore:N"}))

    assert 綠 is False
    assert "少了：ignore:N" in 訊息
    assert _加豁免不是修lint in 訊息


def test_同時多一條又少一條時兩邊都報() -> None:
    綠, 訊息 = 判定ruff豁免((期望ruff豁免 - frozenset({"ignore:N"})) | frozenset({"ignore:F401"}))

    assert 綠 is False
    assert "多了：ignore:F401" in 訊息
    assert "少了：ignore:N" in 訊息
    assert _加豁免不是修lint in 訊息
