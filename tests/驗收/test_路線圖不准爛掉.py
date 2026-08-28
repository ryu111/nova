"""路線圖是手維護的，所以它會爛。

爛掉的路線圖比沒有更糟——讀的人會以為某個東西已經做好了。
所以這裡把圖當成**被驗收的對象**：它宣稱存在的東西必須真的存在。

（這條判準來自宿主反轉那份文件：「文件若宣稱某件事會被自動擋下，
把關器必須存在且有測試背書」。圖也是文件。）
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from nova.載體.模型.轉接 import _規格
from nova.載體.規則表 import 建規則表

專案根目錄 = Path(__file__).resolve().parents[2]
路線圖 = 專案根目錄 / "docs" / "路線圖.html"
合法狀態 = {"好", "半", "無"}


def 讀圖() -> dict[str, Any]:
    文字 = 路線圖.read_text(encoding="utf-8")
    樣式 = r'<script type="application/json" id="圖資料">\s*(.*?)\s*</script>'
    命中 = re.search(樣式, 文字, re.DOTALL)
    assert 命中, "路線圖裡找不到 id=圖資料 的 JSON 區塊——是不是被改成寫死在 JS 裡了？"
    結果: dict[str, Any] = json.loads(命中.group(1))
    return 結果


@pytest.fixture(scope="module")
def 圖() -> dict[str, Any]:
    return 讀圖()


def test_圖存在(圖: dict[str, Any]) -> None:
    assert 圖["節點"], "路線圖沒有任何節點"


def test_標成已完成的檔案必須真的存在(圖: dict[str, Any]) -> None:
    """這是最重要的一條：圖上綠燈的格子，指到的檔案要真的在。

    改了目錄結構卻忘了改圖，這支會紅。
    """
    for 節點 in 圖["節點"]:
        if 節點["態"] != "好":
            continue
        for 相對 in 節點.get("檔", []):
            assert (專案根目錄 / 相對).exists(), (
                f"路線圖說「{節點['標']}」已完成並指到 {相對}，但那個檔案不存在"
            )


def test_未做的格子不准宣稱檔案(圖: dict[str, Any]) -> None:
    """反方向：標成未做卻列了檔案，代表圖沒跟上實作。"""
    for 節點 in 圖["節點"]:
        if 節點["態"] == "無":
            assert not 節點.get("檔"), f"「{節點['標']}」標成未做，卻列了檔案 {節點.get('檔')}"


def test_閘的條數要跟規則表一致(圖: dict[str, Any]) -> None:
    """圖上寫「nova 閘（8 條）」，加規則卻忘了改圖，這支會紅。"""
    宣稱 = next(節點["閘數"] for 節點 in 圖["節點"] if "閘數" in 節點)
    實際 = len([條 for 條 in 建規則表(專案根目錄) if "ci" in 條.閘點])
    assert 宣稱 == 實際, f"路線圖說 {宣稱} 條閘，規則表實際有 {實際} 條"


def test_h_層要跟轉接器的規格表一致(圖: dict[str, Any]) -> None:
    """新增一家 CLI 卻沒畫上圖，或圖上畫了不存在的家，都要紅。"""
    圖上 = {節點["家"] for 節點 in 圖["節點"] if 節點.get("家")}
    assert 圖上 == set(_規格), f"圖上的 h：{sorted(圖上)}；轉接器實際支援：{sorted(_規格)}"


def test_連線兩端都要是存在的節點(圖: dict[str, Any]) -> None:
    識別碼 = {節點["id"] for 節點 in 圖["節點"]}
    for 線 in 圖["連線"]:
        assert 線["從"] in 識別碼, f"連線指向不存在的節點：{線['從']}"
        assert 線["到"] in 識別碼, f"連線指向不存在的節點：{線['到']}"


def test_狀態只能是三種之一(圖: dict[str, Any]) -> None:
    for 節點 in 圖["節點"]:
        assert 節點["態"] in 合法狀態, f"「{節點['標']}」的狀態 {節點['態']!r} 不合法"
