"""額度契約與快取資料轉換單元測試。

單元層只測純函式與資料結構轉換，不碰 I/O、不 fork 子程序。
"""

import dataclasses

import pytest

from nova.契約.額度 import 家族額度, 快取轉快照, 視窗, 額度快照
from nova.載體.額度 import 快取資料型


class Test額度契約資料類別:
    """測試契約 dataclass 的結構與不可變性質。"""

    def test_視窗欄位與不可變(self) -> None:
        窗 = 視窗(標籤="5h", 用掉百分比=20, 重置於=1788063000)
        assert 窗.標籤 == "5h"
        assert 窗.用掉百分比 == 20
        assert 窗.重置於 == 1788063000
        with pytest.raises(dataclasses.FrozenInstanceError):
            窗.用掉百分比 = 30  # type: ignore[misc]

    def test_家族額度成功結構(self) -> None:
        窗 = 視窗(標籤="7d", 用掉百分比=18, 重置於=1788452826)
        家族 = 家族額度(家="codex", 視窗們=(窗,), 失敗原因=None)
        assert 家族.家 == "codex"
        assert 家族.視窗們 == (窗,)
        assert 家族.失敗原因 is None
        with pytest.raises(dataclasses.FrozenInstanceError):
            家族.失敗原因 = "失敗"  # type: ignore[misc]

    def test_家族額度失敗時視窗們為空且有失敗原因(self) -> None:
        家族 = 家族額度(家="codex", 視窗們=(), 失敗原因="啟動 codex app-server 失敗")
        assert 家族.家 == "codex"
        assert 家族.視窗們 == ()
        assert 家族.失敗原因 == "啟動 codex app-server 失敗"

    def test_額度快照結構與不可變(self) -> None:
        家族 = 家族額度(家="agy", 視窗們=(), 失敗原因=None)
        快照 = 額度快照(時間=1788452800, 家族們=(家族,))
        assert 快照.時間 == 1788452800
        assert 快照.家族們 == (家族,)
        with pytest.raises(dataclasses.FrozenInstanceError):
            快照.時間 = 0  # type: ignore[misc]


class Test快取轉快照:
    """測試 ASCII TypedDict 快取資料與繁體中文 dataclass 契約之間的轉換。"""

    def test_快取字典轉額度快照(self) -> None:
        快取資料: 快取資料型 = {
            "ts": 1788452800,
            "families": [
                {
                    "family": "cx",
                    "windows": [
                        {
                            "label": "7d",
                            "used_percent": 18,
                            "resets_at": 1788452826,
                        }
                    ],
                },
                {
                    "family": "ay",
                    "windows": [
                        {
                            "label": "5h",
                            "used_percent": 20,
                            "resets_at": 1788063000,
                        },
                        {
                            "label": "7d",
                            "used_percent": 11,
                            "resets_at": 1788452826,
                        },
                    ],
                },
            ],
        }

        快照 = 快取轉快照(快取資料)
        assert isinstance(快照, 額度快照)
        assert 快照.時間 == 1788452800
        assert len(快照.家族們) == 2

        cx = 快照.家族們[0]
        assert isinstance(cx, 家族額度)
        assert cx.家 == "codex"
        assert cx.失敗原因 is None
        assert len(cx.視窗們) == 1
        assert cx.視窗們[0] == 視窗(標籤="7d", 用掉百分比=18, 重置於=1788452826)

        ay = 快照.家族們[1]
        assert isinstance(ay, 家族額度)
        assert ay.家 == "agy"
        assert ay.失敗原因 is None
        assert len(ay.視窗們) == 2
        assert ay.視窗們[0] == 視窗(標籤="5h", 用掉百分比=20, 重置於=1788063000)
        assert ay.視窗們[1] == 視窗(標籤="7d", 用掉百分比=11, 重置於=1788452826)

    def test_空家族清單轉出空家族快照不准生假資料(self) -> None:
        快取資料: 快取資料型 = {
            "ts": 1788452800,
            "families": [],
        }
        快照 = 快取轉快照(快取資料)
        assert 快照.時間 == 1788452800
        assert 快照.家族們 == ()

    def test_視窗與家族為元組型別(self) -> None:
        快取資料: 快取資料型 = {
            "ts": 1788452800,
            "families": [
                {
                    "family": "cx",
                    "windows": [
                        {
                            "label": "5h",
                            "used_percent": 10,
                            "resets_at": 1788000000,
                        }
                    ],
                }
            ],
        }
        快照 = 快取轉快照(快取資料)
        assert isinstance(快照.家族們, tuple)
        assert isinstance(快照.家族們[0].視窗們, tuple)
