"""套件真的裝得起來、匯得進來。"""

import importlib


def test_匯入_nova() -> None:
    nova = importlib.import_module("nova")
    assert nova.__version__ == "0.1.0"


def test_匯入三層子套件() -> None:
    for 名稱 in ["載體", "迴圈", "契約"]:
        模組 = importlib.import_module(f"nova.{名稱}")
        assert 模組.__doc__, f"nova.{名稱} 沒有說明它負責什麼"
