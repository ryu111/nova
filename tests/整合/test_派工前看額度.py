"""派工前先看一眼額度：**快撞到就不派，查不到就放行，兩種都要說出口。**

2026-09-02 15:16～15:28 台北派出四條線，15:29 四條在同一分鐘內全撞 claude 的
session limit，$3.75、41 分鐘模型時間換回四棵改到一半的工作樹。
那天的 `nova 派工` 過了 `_派工該擋的理由` 就直接落票、開樹、起線——
**沒有任何一格讀過額度**，而數字當時就躺在快取裡。

所以這一支釘的是派工前多出來的那道門，它只有三種結局：

1. **有數字而且快撞到 → 不派。** 回護欄碼 4（不是阻擋 2：那是「人打錯字」），
   而且**票不落、樹不開、模型不叫**——擋在花錢之前才叫擋，落完票再擋只是留垃圾。
2. **查不到 → 照派，但要說。** 快取裡沒這家、或那一家自己的數字太舊，
   都往放行倒（照 `_審查腦碰不到的理由` 的慣例：算不出來不擋），
   但安靜放行等於這道門不存在——所以「照派」這件事要印出來。
3. **門檻之下 → 安靜放行。** 沒事不吵。

**「多舊」問的是那一家自己的時戳**，不是全域那一個：`--從狀態列` 只寫得到
`cl`，全域 `ts` 卻是上一次問 codex／agy 的時間，拿全域去判會把三小時前的
claude 數字當成剛查的。

住整合層、走真的 subprocess：`_派工該擋的理由` 判 `"派工" in sys.argv[1:]`，
而放行那條路的 `_背景起一條線` 又拿 `sys.argv` 重發，行程內叫 `主程式`
兩件事都會走岔。快取也**不手寫**（除了「太舊」那一格，理由見該處註解）：
手寫最終快取只測得到讀端，狀態列的解析與合併就沒人守了。
"""

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from nova.契約.退出碼 import 放行, 護欄碼

nova執行檔 = Path(sys.executable).parent / "nova"
做假CLI型 = Callable[..., tuple[Path, Path]]

#: 一張四欄齊全的票——缺欄的自主票會被 `收件._擋下殘缺的自主票` 擋在別的地方，
#: 那條擋人是對的，但不是這一支要測的東西。
票內容 = """# 把某件事做完

## 輸入

`src/nova/載體/命令列.py`

## 輸出

一個會動的東西

## 驗收

<!--nova:驗收 true-->

## 停止

做不出來就停下來問人
"""

#: 門檻是 90（載體層常數，不是旗標）。95 要擋、60 不擋，兩邊都離門檻夠遠，
#: 不會因為「>= 還是 >」的爭議而變色。
撞到的百分比 = 95
寬裕的百分比 = 60

#: 「多舊算舊」是 7200 秒。三小時前的數字＝查不到。
三小時 = 3 * 60 * 60


def _跑(
    *參數: str, 狀態: Path, 在: Path, 餵: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=在,
        env={**os.environ, "XDG_STATE_HOME": str(狀態)},
        input=餵,
        capture_output=True,
        text=True,
        check=False,
    )


def _造一個commit的repo(根: Path) -> None:
    """派工要開 worktree，所以工作區得是一個真的 repo。"""

    def git(*指令: str) -> int:
        return subprocess.run(["git", *指令], cwd=根, check=False).returncode

    for 指令 in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "測試@例子"),
        ("config", "user.name", "測試"),
    ):
        assert git(*指令) == 0
    (根 / "讀我.md").write_text("第一版\n", encoding="utf-8")
    assert git("add", "-A") == 0
    assert git("commit", "-q", "-m", "第一版") == 0


def _佈景(母目錄: Path, 名: str) -> tuple[Path, Path]:
    """一格一個乾淨的狀態目錄與專案：快取、收件匣、工作樹都不准跨格互相汙染。"""
    狀態 = 母目錄 / 名 / "state"
    專案 = 母目錄 / 名 / "某個專案"
    專案.mkdir(parents=True)
    _造一個commit的repo(專案)
    return 狀態, 專案


def _收件匣(狀態: Path, 專案: Path) -> Path:
    """問 nova 自己收件匣在哪——**不要在測試裡重算一次路徑**。"""
    第一行 = _跑("收件", 狀態=狀態, 在=專案).stdout.splitlines()[0]
    return Path(第一行.removeprefix("收件匣：").strip())


def _躺著的(目錄: Path) -> list[str]:
    """目錄裡的檔名；目錄不在就是空的——「擋下來」本來就可能連目錄都沒建。"""
    return sorted(路.name for 路 in 目錄.glob("*")) if 目錄.is_dir() else []


def _狀態列JSON(用掉百分比: int, 重置於: int) -> str:
    """claude 狀態列 JSON 的形狀照官方文件：`resets_at` 是 epoch 秒。"""
    return json.dumps(
        {
            "session_id": "測試用",
            "model": {"display_name": "Sonnet 4.6"},
            "rate_limits": {
                "five_hour": {"used_percentage": 用掉百分比, "resets_at": 重置於},
                "seven_day": {"used_percentage": 3, "resets_at": 重置於 + 86400},
            },
        },
        ensure_ascii=False,
    )


def _快取檔(狀態: Path) -> Path:
    return 狀態 / "nova" / "額度" / "快取.json"


def _餵狀態列(狀態: Path, 專案: Path, 用掉百分比: int, 重置於: int) -> None:
    """**快取由真的那條路產生**：`nova 額度 --從狀態列` 吃 stdin 的狀態列 JSON。

    手寫最終快取的話，狀態列的解析、合併、每家時戳與節流全都沒人守著。
    """
    結果 = _跑("額度", "--從狀態列", 狀態=狀態, 在=專案, 餵=_狀態列JSON(用掉百分比, 重置於))
    assert 結果.returncode == 放行, f"餵狀態列自己就失敗了：{結果.stderr[:400]}"
    assert _快取檔(狀態).is_file(), "狀態列那條路沒把 claude 寫進快取，後面幾格就沒得測了"


def _手寫快取(狀態: Path, 家們: list[dict[str, object]], 全域ts: int) -> None:
    """只給「太舊」與「沒這家」兩格用。

    這兩格測的是**讀端的政策**（多舊算舊、沒這家怎麼辦），而 CLI 那條路蓋的
    永遠是「現在」的時戳，做不出三小時前的數字——所以這裡例外手寫。
    """
    檔 = _快取檔(狀態)
    檔.parent.mkdir(parents=True, exist_ok=True)
    檔.write_text(
        json.dumps({"ts": 全域ts, "families": 家們}, ensure_ascii=False), encoding="utf-8"
    )


def _派(狀態: Path, 專案: Path, 執行檔: Path) -> subprocess.CompletedProcess[str]:
    票檔 = 專案 / "票.md"
    票檔.write_text(票內容, encoding="utf-8")
    return _跑(
        "派工",
        str(票檔),
        "--用",
        "claude",
        "--審查用",
        "codex",
        "--執行檔",
        str(執行檔),
        # 一顆模型都不叫，所以放行那幾格不燒 token。
        "--最多步數",
        "0",
        "--判準",
        "true",
        狀態=狀態,
        在=專案,
    )


def test_額度快撞到就不派而查不到就放行且都要說出口(tmp_path: Path, 做假CLI: 做假CLI型) -> None:
    """四格：撞到（擋）、太舊（放行並說）、沒這家（放行並說）、寬裕（安靜放行）。"""
    執行檔, 紀錄檔 = 做假CLI("claude")
    現在 = int(time.time())
    重置於 = 現在 + 40 * 60

    # ── 一、快撞到：不派，而且票不落、樹不開、模型不叫 ────────────────
    狀態, 專案 = _佈景(tmp_path, "撞到")
    _餵狀態列(狀態, 專案, 撞到的百分比, 重置於)

    擋了 = _派(狀態, 專案, 執行檔)

    assert 擋了.returncode == 護欄碼, (
        f"額度剩不到一成還照派。stdout={擋了.stdout[:400]} stderr={擋了.stderr[:600]}"
    )
    # 點名到家：哪一家、哪個視窗、用了多少、什麼時候回來——少一樣，人就得自己去查。
    for 該說的 in ("claude", "5h", "95"):
        assert 該說的 in 擋了.stderr, f"擋下來卻沒說 {該說的}：{擋了.stderr[:600]}"
    本機重置 = datetime.fromtimestamp(重置於).astimezone().strftime("%Y-%m-%d %H:%M")
    assert 本機重置 in 擋了.stderr, (
        f"重置時間要印本機時間（epoch 秒讀不出「還要等多久」）：{擋了.stderr[:600]}"
    )

    匣 = _收件匣(狀態, 專案)
    assert not _躺著的(匣), f"擋下來卻把票落進收件匣了，排程醒來會再撿一次：{_躺著的(匣)}"
    assert not _躺著的(匣 / "處理中"), f"擋下來卻把票搶進處理中了：{_躺著的(匣 / '處理中')}"
    樹們 = [路.name for 路 in 專案.parent.glob("nova-wt-*")]
    assert not 樹們, f"擋下來卻開了工作樹，得有人手動收：{樹們}"
    assert not 紀錄檔.exists(), "擋下來卻還是叫了模型——那這道門一塊錢也沒省"

    # ── 二、數字太舊：那一家自己的時戳三小時前，全域 ts 是新的 ────────
    # 拿全域 ts 判的實作在這一格會過關，然後拿三小時前的數字當現在的用。
    狀態, 專案 = _佈景(tmp_path, "太舊")
    _手寫快取(
        狀態,
        [
            {
                "family": "cl",
                "windows": [{"label": "5h", "used_percent": 撞到的百分比, "resets_at": 重置於}],
                "ts": 現在 - 三小時,
            }
        ],
        全域ts=現在,
    )

    太舊了 = _派(狀態, 專案, 執行檔)

    assert 太舊了.returncode == 放行, f"查不到就該放行（算不出來不擋）：{太舊了.stderr[:600]}"
    for 該說的 in ("查不到", "照派"):
        assert 該說的 in 太舊了.stderr, f"放行卻不說，等於這道門不存在：{太舊了.stderr[:600]}"
    匣 = _收件匣(狀態, 專案)
    assert len(_躺著的(匣 / "處理中")) == 1, f"放行了卻沒把票搶進處理中：{_躺著的(匣 / '處理中')}"

    # ── 三、快取裡根本沒這家：一樣放行、一樣要說 ──────────────────────
    狀態, 專案 = _佈景(tmp_path, "沒這家")
    _手寫快取(
        狀態,
        [
            {
                "family": "cx",
                "windows": [{"label": "5h", "used_percent": 10, "resets_at": 重置於}],
                "ts": 現在,
            }
        ],
        全域ts=現在,
    )

    沒這家 = _派(狀態, 專案, 執行檔)

    assert 沒這家.returncode == 放行, f"快取沒 claude 就該放行：{沒這家.stderr[:600]}"
    for 該說的 in ("查不到", "照派"):
        assert 該說的 in 沒這家.stderr, f"放行卻不說：{沒這家.stderr[:600]}"
    匣 = _收件匣(狀態, 專案)
    assert len(_躺著的(匣 / "處理中")) == 1, f"放行了卻沒把票搶進處理中：{_躺著的(匣 / '處理中')}"

    # ── 四、寬裕：安靜放行，一個字都不吵 ──────────────────────────────
    狀態, 專案 = _佈景(tmp_path, "寬裕")
    _餵狀態列(狀態, 專案, 寬裕的百分比, 重置於)

    寬裕 = _派(狀態, 專案, 執行檔)

    assert 寬裕.returncode == 放行, f"六成就擋人的話沒人敢開這道門：{寬裕.stderr[:600]}"
    assert "額度：" not in 寬裕.stderr, f"沒事不要吵：{寬裕.stderr[:600]}"
