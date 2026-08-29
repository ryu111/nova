"""使用者說的那句話：**祕密放進去會被用，但不會被記下來。**

這一支是「載入秘密」那條線的第三段，也是唯一一段會在真的執行路徑上失敗的：

1. `載入到` 把鍵名記進 `NOVA_LOADED_SECRETS`（`tests/整合/test_秘密落盤.py`）
2. `遮罩` 照著名單遮（`tests/單元/test_遮罩.py`）
3. **真的跑一次，帳本裡是 0 次**（這裡）

前兩段是墊片，證明的是轉遞形狀。**第三段證明的是那條線真的接上了**——
CLI 忘了呼叫 `載入到`、或者遮罩拿到的是另一份環境，前兩段照樣全綠，
而祕密會以明文躺在帳本裡。

repo 是 public：洩漏一次就是永久的，GitHub 的快取與別人的 clone 收不回來。
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

nova執行檔 = Path(sys.executable).parent / "nova"
做假CLI型 = Callable[..., tuple[Path, Path]]


#: 執行期組出來的假祕密。**不准寫成字面值**——
#: GitHub 的推送保護擋過一次真的長得像 token 的測試資料（GH013）。
def _假祕密() -> str:
    return "sk" + "-" + "nova" + "測試" + "不要外流" + "0" * 12


def _跑(*參數: str, 狀態: Path, 在: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(nova執行檔), *參數],
        cwd=在,
        env={**os.environ, "XDG_STATE_HOME": str(狀態)},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def 佈景(tmp_path: Path) -> tuple[Path, Path]:
    狀態 = tmp_path / "state"
    專案 = tmp_path / "某個專案"
    專案.mkdir()
    return 狀態, 專案


def _讓模型說出祕密(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """讓假 claude 回一句含著那串祕密的話。

    **實錄在執行期組出來，不進 repo。** 存成固定檔的話，repo 裡就會有一個
    長得像憑證的字串——GitHub 的推送保護擋過一次（GH013），而且那個檔案
    本身也會被 `no-secrets` 那條閘掃到。
    """
    原本 = json.loads(
        (Path(__file__).resolve().parent.parent / "整合" / "實錄" / "claude_ok.json").read_text(
            encoding="utf-8"
        )
    )
    原本["result"] = f"我拿到的憑證是 {_假祕密()}，這樣可以嗎"
    實錄 = tmp_path / "說出祕密.json"
    實錄.write_text(json.dumps(原本), encoding="utf-8")
    monkeypatch.setenv("NOVA_FAKE_CLAUDE_TRANSCRIPT", str(實錄))


def _種祕密(狀態: Path, 專案: Path, 內容: str, *, 權限: int = 0o600) -> Path:
    """透過 nova 自己問落點在哪——**不要在測試裡重算一次路徑**。

    重算的話，落點改了測試不會紅，而那正是要守的東西之一。
    """
    第一行 = _跑("秘密", 狀態=狀態, 在=專案).stdout.splitlines()[0]
    路徑 = Path(第一行.removeprefix("祕密檔：").strip())
    路徑.parent.mkdir(parents=True, exist_ok=True)
    路徑.write_text(內容, encoding="utf-8")
    路徑.chmod(權限)
    return 路徑


def _帳本裡的全部字(狀態: Path) -> str:
    """帳本與成果帳的原始位元組。**不經過任何讀取端**——

    讀取端可能剛好不印那個欄位，那樣測出來的是「印不印」不是「記不記」。

    **只掃 `帳本/` 與 `已處理/`，不掃整個專案目錄。** 祕密檔就住在旁邊
    （同一個 `<狀態根>/專案/<識別>/` 底下），整個掃下去一定會撞到它自己，
    然後這一支會永遠紅——**量法把要測的東西污染掉了**。
    """
    根 = 狀態 / "nova" / "專案"
    return "".join(
        路.read_text(encoding="utf-8", errors="replace")
        for 資料夾 in ("帳本", "已處理")
        for 路 in 根.glob(f"*/{資料夾}/**/*")
        if 路.is_file()
    )


def test_載進去的祕密會被用到(佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
    """**先證明它真的有進去。** 沒進去的話「不外洩」是免費的，也是假的。"""
    狀態, 專案 = 佈景
    執行檔, 紀錄 = 做假CLI("claude")
    _種祕密(狀態, 專案, f"MY_THING={_假祕密()}\n")

    跑完 = _跑("問", "--用", "claude", "--執行檔", str(執行檔), "在嗎", 狀態=狀態, 在=專案)

    assert 跑完.returncode == 0, 跑完.stderr[:400]
    收到的 = json.loads(紀錄.read_text(encoding="utf-8"))
    環境 = 收到的.get("env", {})
    assert 環境.get("MY_THING") == _假祕密(), "祕密沒被交到子程序手上"


def test_祕密一個字都不准進帳本(
    佈景: tuple[Path, Path],
    做假CLI: 做假CLI型,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**這一支是這個檔案的重點。**

    `MY_THING` 這個鍵名撞不上 `遮罩` 猜鍵名那條規則（沒有 KEY／TOKEN／SECRET），
    所以它只可能靠 `NOVA_LOADED_SECRETS` 那條路被遮掉。名單沒接上就會明文落盤。
    """
    狀態, 專案 = 佈景
    執行檔, _ = 做假CLI("claude")
    _種祕密(狀態, 專案, f"MY_THING={_假祕密()}\n")
    _讓模型說出祕密(tmp_path, monkeypatch)

    _跑("問", "--用", "claude", "--執行檔", str(執行檔), "在嗎", 狀態=狀態, 在=專案)

    整本 = _帳本裡的全部字(狀態)
    assert 整本.strip(), "帳本是空的——這一支什麼都沒驗到"
    assert 整本.count(_假祕密()) == 0, "祕密以明文躺在帳本裡了"
    assert "遮罩" in 整本, "連遮罩的標記都沒有，代表模型那句話根本沒被記下來"


def test_權限太鬆時整個不出生(佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
    """**出生前就擋。** 打出去之後才發現權限不對，祕密已經在子程序裡了。"""
    狀態, 專案 = 佈景
    執行檔, 紀錄 = 做假CLI("claude")
    _種祕密(狀態, 專案, f"MY_THING={_假祕密()}\n", 權限=0o644)

    跑完 = _跑("問", "--用", "claude", "--執行檔", str(執行檔), "在嗎", 狀態=狀態, 在=專案)

    assert 跑完.returncode != 0
    assert "0600" in 跑完.stderr
    assert not 紀錄.exists(), "權限不對卻還是把請求打出去了"


def test_沒有祕密檔時一切照舊(佈景: tuple[Path, Path], 做假CLI: 做假CLI型) -> None:
    """**預設關閉。** 這一支防的是擋過頭——沒有祕密檔是絕大多數人的狀態。"""
    狀態, 專案 = 佈景
    執行檔, 紀錄 = 做假CLI("claude")

    跑完 = _跑("問", "--用", "claude", "--執行檔", str(執行檔), "在嗎", 狀態=狀態, 在=專案)

    assert 跑完.returncode == 0, 跑完.stderr[:400]
    assert 紀錄.exists()
