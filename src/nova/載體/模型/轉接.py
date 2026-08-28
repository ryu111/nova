"""三個薄轉接器：把各家 CLI 退回成一顆腦。

每個轉接器只有兩件事——**怎麼組參數**與**用哪支解析器**。
其餘（子程序、逾時、工作目錄）全部共用，所以加第四家的成本是一筆資料。

轉接器的核心職責是**把該家自帶的載體關到最小**（工具、家目錄設定、自帶
system prompt），讓「換腦但行為一樣」成立。哪幾條旗標做這件事，
由 `tests/整合/test_模型轉接.py::Test把各家載體關到最小` 背書。
"""

import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局, 終局判定
from nova.契約.角色 import 呼叫選項, 權限, 預設選項
from nova.載體.模型.執行 import 執行逾時, 跑cli
from nova.載體.模型.解析 import 解析agy, 解析claude, 解析codex

家族 = Literal["claude", "codex", "agy"]
預設候選目錄 = (Path.home() / ".local" / "bin",)

組參數型 = Callable[[str, 呼叫選項], list[str]]
解析型 = Callable[[str, int], 回應]


#: 可編輯模式下 claude 需要的工具。列白名單不用 "default"——要哪些寫出來。
_claude可編輯工具 = "Read,Write,Edit,Bash,Grep,Glob"


def _claude組參數(提示: str, 選項: 呼叫選項) -> list[str]:
    """--bare 跳過 hooks／auto-memory／CLAUDE.md 自動探索；--system-prompt "" 拿掉自帶人格。

    **`--tools` 是變長參數（`<tools...>`），不能放在提示前面的最後一個位置**——
    它會把提示一起吞掉，claude 就會抱怨「沒有 prompt」。實測踩過一次。
    所以後面一定要接一個真正的選項把它終結掉，這裡是 `--system-prompt`。
    """
    # --bare 連 keychain／OAuth 都不讀（訂閱登入會死）；--restricted 只隔離設定檔，
    # CLAUDE.md 仍會被讀。兩害相權由呼叫端決定，不由這裡決定。
    參數 = ["--print", "--output-format", "json"]
    if 選項.隔離設定:
        # 實測：`--setting-sources ""` 讓設定檔與 CLAUDE.md 都讀不到，而且訂閱登入照樣能用。
        # **不要換回 `--bare`**——那條連 keychain 與 OAuth 都不讀，訂閱使用者會直接掛掉。
        參數 += ["--setting-sources", ""]
    if 選項.續接:
        參數 += ["--resume", 選項.續接]
    if 選項.權限 is 權限.唯讀:
        參數 += ["--tools", ""]  # help 原文：Use "" to disable all tools
    elif 選項.權限 is 權限.可編輯:
        參數 += ["--tools", _claude可編輯工具, "--permission-mode", "acceptEdits"]
    else:
        參數 += ["--tools", _claude可編輯工具, "--dangerously-skip-permissions"]
    參數 += ["--system-prompt", ""]  # 順便終結上面的變長參數，不要調換順序
    if 選項.模型:
        參數 += ["--model", 選項.模型]
    return [*參數, 提示]


#: codex 只用這兩個型號（使用者裁定）。luna 是常用的，sol 是高階推理。
codex常用模型 = "gpt-5.6-luna"
codex高階模型 = "gpt-5.6-sol"
#: codex **沒有** `--effort` 旗標（實測 `codex exec --help`），推理強度走設定覆寫。
#: 值要是合法的 TOML，所以字串得再包一層引號。
codex推理強度 = "max"


def _codex共通參數(選項: 呼叫選項) -> list[str]:
    """`exec` 與 `exec resume` 都吃的那幾條。"""
    參數 = ["--json", "--skip-git-repo-check", "-c", f'model_reasoning_effort="{codex推理強度}"']
    if 選項.隔離設定:
        # codex 的隔離旗標不影響認證（auth.json 另外存），所以沒有 claude 那個取捨。
        參數 += ["--ignore-user-config", "--ignore-rules"]
    return [*參數, "--model", 選項.模型 or codex常用模型]


def _codex組參數(提示: str, 選項: 呼叫選項) -> list[str]:
    共通 = _codex共通參數(選項)
    if 選項.續接:
        # 實測：`exec resume` **不吃** `--sandbox` 與 `--approve-for-me`（給了 exit 2），
        # 權限沿用原 session。也不加 `--ephemeral`——續接完還要能再續接。
        return ["exec", "resume", *共通, 選項.續接, 提示]
    if not 選項.保留對話:
        共通 += ["--ephemeral"]  # 不落地就續接不到
    if 選項.權限 is 權限.唯讀:
        共通 += ["--sandbox", "read-only"]
    elif 選項.權限 is 權限.可編輯:
        # 實測：`--sandbox` 與 `--approve-for-me` **互斥**，一起給會 exit 2。
        # --approve-for-me 自己就是「用 workspace-write 沙箱自動核准」（help 原文）。
        共通 += ["--approve-for-me"]
    else:
        # 全開才用這條——它連沙箱都拿掉。
        共通 += ["--dangerously-bypass-approvals-and-sandbox"]
    return ["exec", *共通, 提示]


#: agy 的推理強度包在型號裡（`agy models` 實測），不是另一個旗標。
agy預設模型 = "gemini-3.7-flash-high"


def _agy組參數(提示: str, 選項: 呼叫選項) -> list[str]:
    # agy 查不到設定隔離的旗標（見設計文件 02 缺口），所以 隔離設定 對它是 no-op。
    模式 = "plan" if 選項.權限 is 權限.唯讀 else "accept-edits"
    參數 = ["--output-format", "json", "--mode", 模式]
    if 選項.權限 is 權限.全開:
        參數 += ["--dangerously-skip-permissions"]
    參數 += ["--model", 選項.模型 or agy預設模型]
    if 選項.續接:
        參數 += ["--conversation", 選項.續接]
    # agy 一律會留對話，沒有 --ephemeral 這種東西，所以 保留對話 對它是 no-op。
    # --print 吃的是旗標值，不是位置參數（Go flag 風格）。
    return [*參數, "--print", 提示]


_規格: dict[str, tuple[組參數型, 解析型]] = {
    "claude": (_claude組參數, 解析claude),
    "codex": (_codex組參數, 解析codex),
    "agy": (_agy組參數, 解析agy),
}


def 找執行檔(
    家: str,
    *,
    候選目錄: Sequence[Path] = 預設候選目錄,
    查PATH: Callable[[str], str | None] = shutil.which,
) -> Path:
    """先找候選目錄的真二進位，都沒有才退回 PATH；再沒有就報錯，不靜默。"""
    for 目錄 in 候選目錄:
        路徑 = 目錄 / 家
        if 路徑.exists():
            return 路徑
    找到 = 查PATH(家)
    if 找到:
        return Path(找到)
    訊息 = f"找不到 {家} 的執行檔（找過：{'、'.join(str(d) for d in 候選目錄)}，以及 PATH）"
    raise FileNotFoundError(訊息)


@dataclass(frozen=True, slots=True)
class 命令列模型:
    """一家 CLI 的轉接器。用 `建立()` 產生，不要自己拼。"""

    名稱: str
    執行檔: Path
    組參數: 組參數型
    解析: 解析型

    def 詢問(
        self,
        提示: str,
        *,
        選項: 呼叫選項 = 預設選項,
        環境: Mapping[str, str] | None = None,
    ) -> 回應:
        """問一次，拿回結構化的證據。

        `選項` 是**選填**（有真正的預設值，不是 `None` 哨兵）；
        `環境` 是**選填且 None 有意義**——None 代表沿用父程序的環境，`{}` 代表清空。

        `選項.模型` 原樣傳下去不翻譯——各家的模型命名空間不交集，硬翻譯只會翻錯。
        `選項.權限` 預設唯讀：忘了設不會變成放行。
        """
        try:
            結果 = 跑cli(
                self.執行檔,
                self.組參數(提示, 選項),
                工作目錄=選項.工作目錄,
                逾時秒=選項.逾時秒,
                環境=環境,
            )
        except 執行逾時:
            # 逾時是**結果未知**不是確定失敗——子程序被殺時工作可能已經做了一半。
            return 回應(
                文字="",
                終局=終局判定(失敗代碼.逾時),
                失敗代碼=失敗代碼.逾時,
                原始結束碼=-1,
                對話識別碼=None,
                用量=用量(輸入token=0, 輸出token=0),
            )
        答 = _補上診斷(self.解析(結果.標準輸出, 結果.結束碼), 結果.標準錯誤)
        return _補上認證提示(答, self.名稱, 選項)


def 建立(家: 家族, *, 執行檔: Path | None = None) -> 命令列模型:
    """做一個轉接器。`執行檔` 不給就照 `找執行檔` 的順序找。"""
    if 家 not in _規格:
        可用 = "、".join(sorted(_規格))
        訊息 = f"不認得的 LLM CLI：{家}（可用：{可用}）"
        raise ValueError(訊息)
    組, 析 = _規格[家]
    return 命令列模型(名稱=家, 執行檔=執行檔 or 找執行檔(家), 組參數=組, 解析=析)


_診斷上限 = 2000


def _補上診斷(答: 回應, 標準錯誤: str) -> 回應:
    """失敗而且沒話可說時，把 stderr 當證據。

    不補的話，`usage`（旗標給錯）這種失敗會回一個**空字串**——
    使用者只看得到「確定失敗 usage」，看不到是哪個旗標錯了。
    診斷丟掉比結論丟掉更難查，因為它看起來完全正常。
    """
    if 答.終局 is 終局.成功 or 答.文字.strip():
        return 答
    診斷 = 標準錯誤.strip()
    if not 診斷:
        return 答
    return replace(答, 文字=診斷[:_診斷上限])


#: 認證失敗時的家別提示。錯誤訊息只說「沒登入」，不會說是哪個旗標害的。
_認證提示 = {
    "claude": "\n（nova 提示：claude 沒登入。跑 `claude` 登入，或設 ANTHROPIC_API_KEY。）",
}


def _補上認證提示(答: 回應, 家: str, 選項: 呼叫選項) -> 回應:
    """認證失敗時說清楚是哪個隔離旗標造成的。

    「Not logged in」這句話本身沒有指向真因——使用者明明登入了。
    診斷丟掉比結論丟掉更難查。
    """
    if 答.失敗代碼 is not 失敗代碼.認證 or not 選項.隔離設定:
        return 答
    提示 = _認證提示.get(家)
    return replace(答, 文字=答.文字 + 提示) if 提示 else 答
