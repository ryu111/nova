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


def test_豁免清單只准變短不准變長() -> None:
    """豁免集合的大小必須寫死地板上限，加豁免時必須同時修改上限常數以在 diff 留下紀錄。"""
    from nova.載體.豁免登記 import ruff豁免數量上限

    assert len(期望ruff豁免) <= ruff豁免數量上限
    assert ruff豁免數量上限 == 32, f"現有豁免只有 32 條，地板上限不准偷加：{ruff豁免數量上限}"


def test_pytest設定鍵未登記時指名多了哪個鍵() -> None:
    """pytest ini_options 的鍵集合必須登記，多一個鍵要指名並擋下。"""
    from nova.載體.豁免登記 import 判定pytest設定鍵, 期望pytest設定鍵

    實際 = 期望pytest設定鍵 | frozenset(
        {"disable_test_id_escaping_and_forfeit_all_rights_to_community_support"}
    )
    通過, 訊息 = 判定pytest設定鍵(實際)

    assert 通過 is False
    assert "多了：disable_test_id_escaping_and_forfeit_all_rights_to_community_support" in 訊息


def test_pytest設定鍵符合登記表時是綠的() -> None:
    """pytest ini_options 的鍵集合與登記表一致時判定為通過。"""
    from nova.載體.豁免登記 import 判定pytest設定鍵, 期望pytest設定鍵

    通過, 訊息 = 判定pytest設定鍵(期望pytest設定鍵)

    assert 通過 is True
    assert 訊息 == "pytest 設定鍵符合登記表"


def test_解析pytest設定鍵() -> None:
    """從 pyproject.toml 內容解析出 pytest ini_options 鍵集合。"""
    from nova.載體.豁免登記 import 解析pytest設定鍵

    設定 = """
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
"""
    assert 解析pytest設定鍵(設定) == frozenset({"testpaths", "addopts"})


#: 實測 ruff 0.x（`ruff check --isolated --select F401`）：這幾種寫法**都**真的
#: 讓整個檔案免檢查，但 `tests/驗收/test_專案骨架.py::test_不准整檔關閉ruff檢查`
#: 只認 `# ruff: noqa` 與 `# flake8: noqa` 這兩個開頭，其餘全部漏掉。
#: 漏掉就等於留了一條「把門檻調低來換綠」的暗門。
_ruff真的認可的整檔關閉寫法 = (
    "#ruff:noqa",
    "#  ruff : noqa",
    "# flake8:noqa",
    "\t#ruff: noqa",
)


def test_整檔noqa的空白變體也要被抓到並指名規則() -> None:
    """整檔關閉的偵測要跟 ruff 認可的寫法一樣寬，行尾豁免則不准誤報。

    `# ruff: noqa` 是對整個檔案關掉檢查，沒有正當用途；但少一個空格寫成
    `#ruff:noqa` 一樣有效，只擋前者等於沒擋。偵測要回傳「第幾行、關掉哪一條」，
    沒指定規則就是關掉全部。
    """
    from nova.載體.豁免登記 import 找出整檔noqa

    for 寫法 in _ruff真的認可的整檔關閉寫法:
        assert 找出整檔noqa(f"{寫法}\nimport os\n") == ((1, "全部"),), (
            f"ruff 真的會認 {寫法!r}，偵測卻放它過去"
        )

    assert 找出整檔noqa('"""說明。"""\n\n# ruff: noqa: SLF001\n') == ((3, "SLF001"),), (
        "整檔關閉不一定在第一行，且要指名關掉的是哪一條規則"
    )

    assert 找出整檔noqa("import os  # noqa: F401\n") == (), "行尾豁免是正當寫法，不准被當成整檔關閉"
