"""ruff 豁免登記的純判定：設定與登記表不能悄悄漂移。"""

from nova.載體.豁免登記 import 判定ruff豁免, 期望ruff豁免, 解析ruff豁免

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


def test_格式排除要被當成未登記豁免而指名() -> None:
    設定 = """
[tool.ruff.lint]
ignore = []
per-file-ignores = {}

[tool.ruff.format]
exclude = ["tests/單元/test_架構決策.py"]
"""

    綠, 訊息 = 判定ruff豁免(解析ruff豁免(設定), frozenset())

    assert 綠 is False, 訊息
    assert "多了：format:exclude:tests/單元/test_架構決策.py" in 訊息
    assert _加豁免不是修lint in 訊息


def test_外接設定要被當成未登記豁免而指名() -> None:
    設定 = """
[tool.ruff]
extend = "ruff-base.toml"

[tool.ruff.lint]
ignore = []
per-file-ignores = {}
"""

    綠, 訊息 = 判定ruff豁免(解析ruff豁免(設定), frozenset())

    assert 綠 is False, 訊息
    assert "多了：extend:ruff-base.toml" in 訊息
    assert _加豁免不是修lint in 訊息


def test_各層排除鍵都會攤平() -> None:
    設定 = """
[tool.ruff]
exclude = ["根層"]
extend-exclude = ["根層延伸"]

[tool.ruff.lint]
exclude = ["lint層"]

[tool.ruff.format]
exclude = ["格式層"]
extend-exclude = ["格式層延伸"]
"""

    assert 解析ruff豁免(設定) == frozenset(
        {
            "exclude:根層",
            "extend-exclude:根層延伸",
            "lint:exclude:lint層",
            "format:exclude:格式層",
            "format:extend-exclude:格式層延伸",
        }
    )


def test_輸入範圍鍵也會攤平() -> None:
    設定 = """
[tool.ruff]
include = ["src/**"]
extend-include = ["*.pyi"]

[tool.ruff.lint]
ignore = []
per-file-ignores = {}
"""

    assert 解析ruff豁免(設定) == frozenset({"include:src/**", "extend-include:*.pyi"})


def test_舊式頂層豁免鍵也會攤平() -> None:
    設定 = """
[tool.ruff]
ignore = ["F401"]
extend-ignore = ["E501"]
per-file-ignores = {"tests/**" = ["S101"]}
extend-per-file-ignores = {"src/**" = ["T201"]}
"""

    assert 解析ruff豁免(設定) == frozenset(
        {
            "ignore:F401",
            "extend-ignore:E501",
            "per-file-ignores:tests/**:S101",
            "extend-per-file-ignores:src/**:T201",
        }
    )
