"""審查腦不可達時，前三個模型階段一次都不准被叫到。

現況（架構審查追出來的）：`_工作流前置檢查` 只查審查家的**資格**
（本地腦能不能當審查員、有沒有被熔斷），那些全是本地資料。
資格不等於可達——CLAUDE.md 判準三：**墊片證明的是轉遞形狀，不是可達性。**
額度用完或認證過期的審查腦，資格檢查一路放行，於是
test／impl／refactor 三階照燒（實測每輪約 2.5M token），死在 review，
而中止不接著排，下一輪從頭來。

這一份守兩件事，缺一不可：

1. `Test審查腦不可達就別開跑`：擋得住。斷言**零個角色被呼叫**。
2. `Test接力鏈還有備援就照跑`：**不擋過頭**。少了這一支，這道檢查會把
   「第一家不可達但第二家可達」一起擋掉，接力機制等於沒有。

接縫是 `命令列.可達嗎(家)`：一次**版本查詢級**的便宜探測（零 token、亞秒級），
回 `True`／`False`／`None`（算不出來，照 `載體/線.py` 的慣例留空不拿 0 頂替）。
這裡把它換成計次假探針——真的去碰 CLI 是 `模型/轉接.py` 那一層的事，
在這一層做只會讓測試變慢又出網路。
"""

from pathlib import Path

import pytest

from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局
from nova.契約.角色 import 呼叫選項, 預設選項
from nova.契約.退出碼 import 放行, 未知, 阻擋
from nova.載體 import 命令列


class 計次假腦:
    """只數自己被叫過幾次。**燒不燒 token 就看這個數字。**"""

    名稱 = "計次假腦"

    def __init__(self) -> None:
        """初始化呼叫計數。"""
        self.叫過 = 0

    def 詢問(self, 提示: str, *, 選項: 呼叫選項 = 預設選項) -> 回應:
        del 提示, 選項
        self.叫過 += 1
        return 回應(
            文字="已收到",
            終局=終局.成功,
            失敗代碼=失敗代碼.無,
            原始結束碼=0,
            對話識別碼=None,
            用量=用量(輸入token=1, 輸出token=1),
        )


def _跑一輪(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    審查用: str,
    可達的家: dict[str, bool | None],
) -> tuple[int, 計次假腦, list[str]]:
    """跑一輪工作流，回 (退出碼, 計次假腦, 探針問過哪幾家)。

    `--用` 固定 codex、`--審查用` 由呼叫端給，兩邊分得開才看得出擋的是審查那一側。
    """
    腦 = 計次假腦()
    問過: list[str] = []

    def 探針(家: str, **_其他: object) -> bool | None:
        """假的版本查詢。**不發真實問答**——那本身就是在燒 token 防燒 token。"""
        del _其他  # 只為了讓探針吃得下任何關鍵字參數，內容本身用不到
        問過.append(家)
        return 可達的家[家]

    工作區 = tmp_path / "工作區"
    工作區.mkdir(exist_ok=True)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "狀態"))
    monkeypatch.setattr(命令列, "_建腦", lambda *_args, **_kwargs: 腦)
    monkeypatch.setattr(命令列, "可達嗎", 探針)
    碼 = 命令列.主程式(
        [
            "跑",
            "--用",
            "codex",
            "--審查用",
            審查用,
            "--工作目錄",
            str(工作區),
            "--判準",
            "true",
            "--最多步數",
            "1",
            "--不記帳",
            "任務",
        ]
    )
    return 碼, 腦, 問過


class Test審查腦不可達就別開跑:
    """審查腦碰不到的那一輪，**一個模型階段都不准開始**。"""

    def test_零個角色被呼叫(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """計數要是 0。1 就代表 test 那一階已經燒掉了（實測 500-850k token）。

        「工作流沒跑起來」不足以證明什麼——真正要釘的是**它在哪裡停的**：
        停在建腦之前。`Test接力鏈還有備援就照跑` 用同一套 harness 數到 >= 1，
        所以這裡的 0 是「被擋下來」，不是「這套 harness 本來就叫不到腦」。
        """
        碼, 腦, 問過 = _跑一輪(
            tmp_path, monkeypatch, 審查用="agy", 可達的家={"codex": True, "agy": False}
        )

        assert 腦.叫過 == 0, f"審查腦不可達，卻還是叫了 {腦.叫過} 次模型——那就是沉沒的 token"
        assert "agy" in 問過, "根本沒問過審查家可不可達，那這道檢查不存在"
        assert 碼 == 阻擋, f"還沒開始就擋下要回 {阻擋}（跟前置檢查其他格一致），拿到 {碼}"
        assert 碼 != 未知, f"{未知} 是『跑到一半掛了』，外圈分不出來就會照著重跑"
        assert 碼 != 放行

    def test_擋下來的理由指得出是哪一家(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """只說「被擋下」的話，人得自己一家一家試。訊息要點名那一家。"""
        _跑一輪(tmp_path, monkeypatch, 審查用="agy", 可達的家={"codex": True, "agy": False})

        錯誤輸出 = capsys.readouterr().err
        assert "agy" in 錯誤輸出, f"沒點名不可達的那一家：{錯誤輸出[:300]}"
        assert "審查" in 錯誤輸出, f"沒講清楚是審查那一側的問題：{錯誤輸出[:300]}"


class Test接力鏈還有備援就照跑:
    """**這一支防的是擋過頭。**

    `--審查用 a,b` 是接力：a 不可達還有 b。判準是**整條鏈都不可達**才擋，
    不是第一家不可達就擋——照第一家算的話，接力機制等於沒有。
    """

    def test_第一家不可達第二家可達時工作流照跑(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """整條鏈還有活路，就不准擋。"""
        碼, 腦, 問過 = _跑一輪(
            tmp_path,
            monkeypatch,
            審查用="codex,agy",
            可達的家={"codex": False, "agy": True},
        )

        assert 碼 != 阻擋, "鏈上還有一家可達，卻在開跑前就被擋下來了"
        assert 腦.叫過 >= 1, "備援還在卻一個角色都沒叫到，等於把接力機制擋死了"
        assert "codex" in 問過 or "agy" in 問過, "整條鏈都沒問過"
