"""額度查詢單元測試：純函式解析各家限額與格式換算。

單元層的定義是純函式、不碰 I/O、不 fork 子程序。
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from nova.載體.狀態 import 狀態根目錄
from nova.載體.額度 import (
    分鐘轉標籤,
    短窗排前面,
    視窗型,
    解析agy額度,
    解析codex額度,
    該重抓嗎,
    額度快取路徑,
)


class Test分鐘轉標籤:
    def test_10080分鐘換算為7天(self) -> None:
        """這台機器的真實 primary 是 10080 分鐘（7 天），防把 5h 寫死。"""
        assert 分鐘轉標籤(10080) == "7d"

    def test_300分鐘換算為5小時(self) -> None:
        assert 分鐘轉標籤(300) == "5h"

    def test_其他時間換算(self) -> None:
        assert 分鐘轉標籤(60) == "1h"
        assert 分鐘轉標籤(1440) == "1d"
        assert 分鐘轉標籤(720) == "12h"


class Test解析codex額度:
    def test_從codex回應算出windows_10080分鐘算出標籤7d(self) -> None:
        """輸入必須是 10080 而不是 300，防止把 5h 寫死。"""
        回應 = {
            "id": 2,
            "result": {
                "rateLimits": {
                    "limitId": "codex",
                    "planType": "prolite",
                    "primary": {
                        "usedPercent": 18,
                        "windowDurationMins": 10080,
                        "resetsAt": 1788452826,
                    },
                    "secondary": None,
                }
            },
        }
        視窗們 = 解析codex額度(回應)
        assert len(視窗們) == 1
        assert 視窗們[0] == {
            "label": "7d",
            "used_percent": 18,
            "resets_at": 1788452826,
        }

    def test_secondary為null時只生一格不准補0(self) -> None:
        """secondary 為 null 時不要生那一格，不准補 0% 填充值。"""
        回應 = {
            "id": 2,
            "result": {
                "rateLimits": {
                    "limitId": "codex",
                    "planType": "prolite",
                    "primary": {
                        "usedPercent": 25,
                        "windowDurationMins": 300,
                        "resetsAt": 1788000000,
                    },
                    "secondary": None,
                }
            },
        }
        視窗們 = 解析codex額度(回應)
        assert len(視窗們) == 1
        assert 視窗們[0]["label"] == "5h"
        assert 視窗們[0]["used_percent"] == 25

    def test_secondary有值時雙視窗皆解析(self) -> None:
        回應 = {
            "id": 2,
            "result": {
                "rateLimits": {
                    "limitId": "codex",
                    "planType": "prolite",
                    "primary": {
                        "usedPercent": 18,
                        "windowDurationMins": 10080,
                        "resetsAt": 1788452826,
                    },
                    "secondary": {
                        "usedPercent": 40,
                        "windowDurationMins": 300,
                        "resetsAt": 1788063000,
                    },
                }
            },
        }
        視窗們 = 解析codex額度(回應)
        assert len(視窗們) == 2
        assert 視窗們[0] == {
            "label": "7d",
            "used_percent": 18,
            "resets_at": 1788452826,
        }
        assert 視窗們[1] == {
            "label": "5h",
            "used_percent": 40,
            "resets_at": 1788063000,
        }

    def test_格式不對或缺少欄位回空清單不准硬湊(self) -> None:
        assert 解析codex額度({}) == []
        assert 解析codex額度({"result": {}}) == []
        assert 解析codex額度({"result": {"rateLimits": {}}}) == []


class Test解析agy額度:
    def test_89趴Remaining要變成used_percent_11(self) -> None:
        """百分比是 Remaining（剩下多少），要換算成 used_percent = 100 - 剩下。"""
        文字 = (
            "Gemini Models\tWeekly Limit Remaining\t89%\t2026-09-03T19:05:42Z\n"
            "Gemini Models\tFive Hour Limit Remaining\t80%\t2026-08-29T18:09:43Z\n"
        )
        視窗們 = 解析agy額度(文字)
        assert len(視窗們) == 2
        t1 = datetime.fromisoformat("2026-09-03T19:05:42Z").replace(tzinfo=UTC)
        t2 = datetime.fromisoformat("2026-08-29T18:09:43Z").replace(tzinfo=UTC)
        assert 視窗們[0]["label"] == "7d"
        assert 視窗們[0]["used_percent"] == 11
        assert 視窗們[0]["resets_at"] == int(t1.timestamp())

        assert 視窗們[1]["label"] == "5h"
        assert 視窗們[1]["used_percent"] == 20
        assert 視窗們[1]["resets_at"] == int(t2.timestamp())

    def test_Claude與GPT列要被濾掉(self) -> None:
        """nova 只透過 agy 用 Gemini，只取 Gemini Models 那兩列。"""
        文字 = (
            "Gemini Models\tWeekly Limit Remaining\t89%\t2026-09-03T19:05:42Z\n"
            "Gemini Models\tFive Hour Limit Remaining\t80%\t2026-08-29T18:09:43Z\n"
            "Claude and GPT models\tWeekly Limit Remaining\t100%\t2026-09-05T16:37:38Z\n"
            "Claude and GPT models\tFive Hour Limit Remaining\t100%\t2026-08-29T21:37:38Z\n"
        )
        視窗們 = 解析agy額度(文字)
        assert len(視窗們) == 2
        標籤們 = [視["label"] for 視 in 視窗們]
        assert 標籤們 == ["7d", "5h"]

    def test_整段為空或格式不對回空清單不准硬湊(self) -> None:
        assert 解析agy額度("") == []
        assert 解析agy額度("隨便一段純文字沒有tab") == []
        過濾列 = "Claude and GPT models\tWeekly Limit Remaining\t100%\t2026-09-05T16:37:38Z"
        assert 解析agy額度(過濾列) == []


class Test狀態路徑:
    def test_有設定XDG_STATE_HOME時(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", "/自訂/狀態")
        assert 狀態根目錄() == Path("/自訂/狀態/nova")
        assert 額度快取路徑() == Path("/自訂/狀態/nova/額度/快取.json")


class Test短窗排前面:
    """來源順序不能信：agy 吐的是 Weekly 在前，照抄會顯示成「7d 5h」，讀起來是反的。"""

    def test_長窗在前也要被排到後面(self) -> None:
        排好 = 短窗排前面(
            [
                {"label": "7d", "used_percent": 11, "resets_at": 2},
                {"label": "5h", "used_percent": 20, "resets_at": 1},
            ]
        )
        assert [視窗["label"] for 視窗 in 排好] == ["5h", "7d"]

    def test_只有一格就原樣回來(self) -> None:
        只有一格: list[視窗型] = [{"label": "7d", "used_percent": 18, "resets_at": 3}]
        assert 短窗排前面(只有一格) == 只有一格

    def test_排序的鍵是視窗長度不是字串(self) -> None:
        """`"5h" < "7d"` 剛好成立，所以只有這兩格的話，字串比較會矇混過去。

        `10h` 與 `5h` 才分得開：字串比 `"10h" < "5h"`（比的是第一個字元），
        跟正確答案（5 小時在前）剛好相反。

        **這支是負控逼出來的**：第一版用 90m 與 1h，字串比也剛好給對答案，
        所以把排序改成比字串它照樣綠——那等於沒有守。
        """
        排好 = 短窗排前面(
            [
                {"label": "10h", "used_percent": 1, "resets_at": 1},
                {"label": "5h", "used_percent": 2, "resets_at": 2},
            ]
        )
        assert [視窗["label"] for 視窗 in 排好] == ["5h", "10h"]


class Test該重抓嗎:
    """節流的判斷。

    **這一格原本住在 `~/.claude/settings.json` 的一行 `find -mmin -15` 裡**——
    設定檔裡的程式碼沒辦法測試，等於沒有保證；而且快取路徑在那裡寫了第二份，
    nova 哪天搬家，那條 hook 會安靜地一直看舊路徑、永遠判定「還新」、永遠不刷。
    搬回來就是為了讓它被這幾支守著。
    """

    def test_快取不在就一定要抓(self) -> None:
        assert 該重抓嗎(None, 900) is True

    def test_比門檻舊就要抓(self) -> None:
        assert 該重抓嗎(901, 900) is True

    def test_剛好等於門檻也要抓(self) -> None:
        """邊界要往「抓」那邊倒：多抓一次只花幾秒，少抓一次是顯示騙人。"""
        assert 該重抓嗎(900, 900) is True

    def test_比門檻新就不要抓(self) -> None:
        assert 該重抓嗎(899, 900) is False

    def test_門檻是0就一律要抓(self) -> None:
        """`nova 額度` 不帶旗標時預設不節流——直接叫它就是要現在的數字。"""
        assert 該重抓嗎(0, 0) is True
        assert 該重抓嗎(99999, 0) is True
