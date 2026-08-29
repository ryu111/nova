"""額度查詢單元測試：純函式解析各家限額與格式換算。

單元層的定義是純函式、不碰 I/O、不 fork 子程序。
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from nova.載體.額度 import (
    分鐘轉標籤,
    狀態根目錄,
    解析agy額度,
    解析codex額度,
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
