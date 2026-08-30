"""Ornith-1.5-9B-MLX-8bit 的能力邊界探針。

這些測試只打真本機端點；答案由固定字串、JSON 欄位與延遲數字機械判定。
"""

import contextlib
import io
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable

import pytest

from nova.契約.模型回應 import 回應, 終局
from nova.契約.角色 import 呼叫選項, 權限
from nova.載體.命令列 import 主程式
from nova.載體.模型.本地 import 本地腦, 預設本地網址

測試次數 = 3


@pytest.fixture
def 真端點網址() -> str:
    """探真端點；本機沒開服務就跳過。"""
    網址 = 預設本地網址()
    try:
        with urllib.request.urlopen(f"{網址}/models", timeout=2):  # noqa: S310
            pass
    except urllib.error.HTTPError:
        raise
    except OSError:
        pytest.skip(f"本機沒有推論伺服器（{網址}）")
    return 網址


def _量測(名稱: str, 探針: Callable[[], bool]) -> None:
    延遲們: list[float] = []
    通過數 = 0
    for _ in range(測試次數):
        開始 = time.perf_counter()
        通過 = 探針()
        延遲們.append(time.perf_counter() - 開始)
        通過數 += 通過

    平均延遲 = sum(延遲們) / len(延遲們)
    報告 = (
        f"{名稱}：通過率 {通過數}/{測試次數}，平均延遲 {平均延遲:.3f}s，最慢 {max(延遲們):.3f}s\n"
    )
    sys.stderr.write(報告)
    assert 通過數 == 測試次數, (
        f"{名稱}：通過率 {通過數}/{測試次數}，平均延遲 {平均延遲:.3f}s，最慢 {max(延遲們):.3f}s"
    )


def _問(網址: str, 提示: str) -> 回應:
    return 本地腦(網址=網址).詢問(提示, 選項=呼叫選項(權限=權限.唯讀, 逾時秒=120))


@pytest.mark.真端點
def test_硬格式服從(真端點網址: str) -> None:
    """最後一行必須是審查結論，逐字比對。"""
    提示 = (
        "請先回答一句話。最後一行必須且只能是 REVIEW: PASS 或 "
        "REVIEW: CHANGES-REQUESTED；最後一行不要加標點、Markdown 或其他文字。"
    )

    def 探針() -> bool:
        答 = _問(真端點網址, 提示)
        行們 = 答.文字.rstrip().splitlines()
        return (
            答.終局 is 終局.成功
            and bool(行們)
            and 行們[-1]
            in {
                "REVIEW: PASS",
                "REVIEW: CHANGES-REQUESTED",
            }
        )

    _量測("硬格式服從", 探針)


@pytest.mark.真端點
def test_長提示不漏中段指令(真端點網址: str) -> None:
    """中段的具體要求必須出現在回應中。"""
    前段 = "\n".join(f"前情第 {編號} 段：這是與答案無關的背景資料。" for 編號 in range(80))
    後段 = "\n".join(f"後情第 {編號} 段：這也是與答案無關的背景資料。" for 編號 in range(80))
    提示 = (
        "你是唯讀資料整理員。\n\n"
        "題目：讀完前情後回覆一句話。\n\n"
        f"{前段}\n"
        "中段機械指令：回應中必須逐字包含 LOCAL_MIDPOINT_9B_OK。\n"
        f"{後段}\n"
        "請保持簡短。"
    )

    def 探針() -> bool:
        答 = _問(真端點網址, 提示)
        return 答.終局 is 終局.成功 and "LOCAL_MIDPOINT_9B_OK" in 答.文字

    _量測("長提示不漏中段指令", 探針)


@pytest.mark.真端點
def test_json輸出符合回應契約(真端點網址: str) -> None:
    """走 `--json`，解析並檢查 nova 回應契約欄位。"""
    del 真端點網址

    def 探針() -> bool:
        標準輸出 = io.StringIO()
        標準錯誤 = io.StringIO()
        with contextlib.redirect_stdout(標準輸出), contextlib.redirect_stderr(標準錯誤):
            碼 = 主程式(
                [
                    "問",
                    "--用",
                    "local",
                    "--json",
                    "--不記帳",
                    "--逾時",
                    "120",
                    "只回一句簡短文字。",
                ]
            )
        try:
            證據 = json.loads(標準輸出.getvalue())
        except json.JSONDecodeError:
            return False
        if not isinstance(證據, dict):
            return False
        必備 = {"文字", "終局", "失敗代碼", "原始結束碼", "對話識別碼", "用量", "結構化輸出"}
        用量 = 證據.get("用量")
        return (
            碼 == 0
            and 必備 <= 證據.keys()
            and 證據["終局"] == "success"
            and isinstance(證據["文字"], str)
            and isinstance(用量, dict)
            and {"輸入token", "輸出token", "成本美金"} <= 用量.keys()
        )

    _量測("JSON 輸出符合回應契約", 探針)


@pytest.mark.真端點
def test_拒絕答不出的事實(真端點網址: str) -> None:
    """沒有資料可回答時，只接受明確拒答，不接受杜撰名稱。"""
    提示 = (
        "問題：LOCAL-9B-UNKNOWN-20260830-7 的真實建立者是誰？"
        "這個識別碼是剛編的，提示沒有提供建立者資料。"
        "若你沒有依據，請只回答「我不知道」，不要猜測。"
    )

    def 探針() -> bool:
        答 = _問(真端點網址, 提示)
        return 答.終局 is 終局.成功 and 答.文字.strip() == "我不知道"

    _量測("拒絕答不出的事實", 探針)
