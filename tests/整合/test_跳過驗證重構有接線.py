"""跳過 `驗證重構` 的記帳要在**兩條生產路徑**上都接得上。

`跑工作流` 有一個 `記跳過` 參數不代表真線上有人傳它——CLAUDE.md 判準第 3 條：
有實作、沒有可達的呼叫端，等於沒有。而且兩條路都要接：

- `nova 工作流`（`載體.命令列._子命令_工作流`）：排程、`nova 跑`、`nova 派工`
  最後都收斂到這一條；
- `nova.派工`（`src/nova/__init__.py` 的對外 API）。

只接一處的話，另一條路上的跳過會**靜靜地沒有帳**——而「這一輪沒跳過」跟
「跳了但沒記」在帳本上長得一模一樣，之後就沒有人答得出「跳了幾次、有沒有誤跳」。

手工呼叫 `跑工作流` 蓋不到這兩格，那正是意思會蒸發的地方，所以攔在
「造好零件、交棒給 `跑工作流`」的那一刻，不真的呼叫模型。

順手守第二件事：那一筆帳落到檔案上要是 `stage_skipped`，而且**不准帶 `call`**——
`載體.帳本讀取` 的配對看到帶編號而不屬於「開始的」那一組的事件會去 pop，
帶了編號就會把別人的成對事件配壞。

第三件事：那一筆要**從正式讀取端**看得見。落到檔案上只是寫端的事，
帳本是拿來讀的——讀端認不得的事件會被丟掉、還會被算進 `壞掉的行`，
於是「跳過了一階」在帳上長得像「那次寫壞了一行」。這兩個問題方向相反
（一個少講、一個講錯），都會讓「跳了幾次、有沒有誤跳」問不出答案。
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import nova
from nova.契約.工作流 import 任務, 結束, 結束代碼, 階段代碼
from nova.契約.模型回應 import 回應
from nova.契約.角色 import 呼叫選項, 語言模型, 預設選項
from nova.載體 import 命令列
from nova.載體.帳本 import 開帳本
from nova.載體.帳本讀取 import 列出執行, 讀一次執行, 讀原始事件
from nova.載體.階段記帳 import 建記跳過
from nova.迴圈.工作流 import 工作流結果

_一件事 = "把三處重複的階段判斷收成一支查詢"


class _不該被呼叫的腦:
    """這支測試只驗接線：走到「交棒給工作流」就停，不該有任何模型被叫起來。"""

    名稱 = "不該被呼叫的腦"

    def 詢問(self, 提示: str, *, 選項: 呼叫選項 = 預設選項) -> 回應:
        del 提示, 選項
        訊息 = "這支測試只驗接線，不該真的呼叫模型"
        raise AssertionError(訊息)


def _攔下跑工作流並當場跳一階(
    模組: object, monkeypatch: pytest.MonkeyPatch
) -> list[dict[str, object]]:
    """攔在 `跑工作流`，把呼叫端真的送進去的那些具名參數接下來。

    接下來之後**當場拿 `記跳過` 用一次**：帳本這時候還開著（`with` 區塊裡面），
    所以那一筆會真的落到檔案上——驗的是同一條路上的同一本帳，不是另外造一本。
    """
    收到: list[dict[str, object]] = []

    def 假跑工作流(任: 任務, **其餘: object) -> 工作流結果:
        del 任
        收到.append(dict(其餘))
        記跳過 = 其餘.get("記跳過")
        if callable(記跳過):
            記跳過(階段代碼.驗證重構)
        return 工作流結果(結束=結束(代碼=結束代碼.完成, 原因="這支測試沒有真的跑"), 軌跡=())

    monkeypatch.setattr(模組, "跑工作流", 假跑工作流)
    return 收到


def _走命令列(專案: Path, 執行檔: Path, 帳本目錄: Path) -> int:
    """真的走 `主程式`，不自己拼參數——這一支守的就是那條路上的接線。"""
    return 命令列.主程式(
        [
            "工作流",
            _一件事,
            "--工作目錄",
            str(專案),
            "--用",
            "claude",
            "--審查用",
            "codex",
            "--執行檔",
            str(執行檔),
            "--判準",
            "true",
            "--帳本目錄",
            str(帳本目錄),
        ]
    )


def _走門面(專案: Path, 帳本目錄: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """對外 API 那一條。腦換成假的：接線驗得完，不必有任何 CLI 存在。"""

    def 假建腦(*參數: object, **具名: object) -> 語言模型:
        del 參數, 具名
        return _不該被呼叫的腦()

    monkeypatch.setattr(nova, "_建腦", 假建腦)
    nova.派工(
        _一件事,
        用="codex",
        審查用="claude",
        工作目錄=專案,
        判準指令=["true"],
        帳本目錄=帳本目錄,
    )


def _帳本行們(帳本目錄: Path) -> list[dict[str, object]]:
    行們: list[dict[str, object]] = []
    for 檔 in sorted(帳本目錄.glob("*.jsonl")):
        行們.extend(
            json.loads(行) for 行 in 檔.read_text(encoding="utf-8").splitlines() if 行.strip()
        )
    return 行們


@pytest.mark.parametrize("路線", ["命令列", "門面"])
def test_兩個接線點都把記跳過傳進跑工作流(
    路線: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    做假CLI: Callable[..., tuple[Path, Path]],
) -> None:
    """守：兩條生產路徑都把記帳能力交給工作流，而且那一筆落得到帳本上。"""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    專案 = tmp_path / "某個專案"
    專案.mkdir()
    帳本目錄 = tmp_path / "帳本"
    模組: object = 命令列 if 路線 == "命令列" else nova
    收到 = _攔下跑工作流並當場跳一階(模組, monkeypatch)

    if 路線 == "命令列":
        執行檔, _ = 做假CLI("claude")
        _走命令列(專案, 執行檔, 帳本目錄)
    else:
        _走門面(專案, 帳本目錄, monkeypatch)

    assert len(收到) == 1, f"「{路線}」該把任務交給工作流剛好一次"
    assert 收到[0].get("記跳過") is not None, (
        f"「{路線}」這條路沒把 `記跳過` 傳進 `跑工作流`——這條路上的跳過會靜靜地沒有帳"
    )
    跳過的行們 = [行 for 行 in _帳本行們(帳本目錄) if 行.get("event") == "stage_skipped"]
    assert len(跳過的行們) == 1, f"「{路線}」跳過一階該在帳本上落一筆 stage_skipped"
    assert 跳過的行們[0].get("stage") == 階段代碼.驗證重構.value, (
        "被跳過的是哪一階要寫在既有的 `階段` 欄上，不然帳上答不出跳掉的是什麼"
    )
    assert "call" not in 跳過的行們[0], (
        "跳過事件不成對，帶了呼叫編號會讓 `帳本讀取` 的配對 pop 掉別人的開著事件"
    )


def test_跳過那筆帳從正式讀取端看得到而且不算壞行(tmp_path: Path) -> None:
    """守：跳過那一筆走 `帳本讀取` 正式路徑仍是證據——讀得出來，而且不被當成寫壞的行。"""
    帳本目錄 = tmp_path / "帳本"
    with 開帳本(帳本目錄) as 帳:
        建記跳過(帳)(階段代碼.驗證重構)
    (檔,) = 列出執行(帳本目錄)

    跳過的事件們 = [事 for 事 in 讀原始事件(檔) if 事.get("event") == "stage_skipped"]
    assert [事.get("stage") for 事 in 跳過的事件們] == [階段代碼.驗證重構.value], (
        "`讀原始事件` 認不得的種類會被丟掉——那一階跳過了就在讀取端消失，"
        "帳上答不出跳了幾次、跳掉的是哪一階"
    )
    assert 讀一次執行(檔).壞掉的行 == 0, (
        "正常跳過的那一筆被算進 `壞掉的行`，等於一次成功的跳過在摘要上長得像帳本損壞"
    )
