"""三個薄轉接器：把各家 CLI 退回成一顆腦。

每個轉接器只有兩件事——**怎麼組參數**與**用哪支解析器**。
其餘（子程序、逾時、工作目錄）全部共用，所以加第四家的成本是一筆資料。

轉接器的核心職責是**把該家自帶的載體關到最小**（工具、家目錄設定、自帶
system prompt），讓「換腦但行為一樣」成立。哪幾條旗標做這件事，
由 `tests/整合/test_模型轉接.py::Test把各家載體關到最小` 背書。
"""

import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from nova.契約.模型回應 import 回應, 用量, 終局判定
from nova.載體.模型.執行 import 執行逾時, 跑cli
from nova.載體.模型.解析 import 解析agy, 解析claude, 解析codex

家族 = Literal["claude", "codex", "agy"]
預設候選目錄 = (Path.home() / ".local" / "bin",)

組參數型 = Callable[[str, str | None], list[str]]
解析型 = Callable[[str, int], 回應]


def _claude組參數(提示: str, 模型: str | None) -> list[str]:
    # --tools "" 關掉全部內建工具；--bare 跳過 hooks／auto-memory／CLAUDE.md 自動探索；
    # --system-prompt "" 拿掉自帶人格。三條都經 `claude --help` 查證。
    參數 = ["--print", "--output-format", "json", "--tools", "", "--bare", "--system-prompt", ""]
    if 模型:
        參數 += ["--model", 模型]
    return [*參數, 提示]


def _codex組參數(提示: str, 模型: str | None) -> list[str]:
    參數 = [
        "exec",
        "--json",
        "--sandbox",
        "read-only",
        "--ignore-user-config",
        "--ignore-rules",
        "--ephemeral",
        "--skip-git-repo-check",
    ]
    if 模型:
        參數 += ["--model", 模型]
    return [*參數, 提示]


def _agy組參數(提示: str, 模型: str | None) -> list[str]:
    參數 = ["--output-format", "json", "--mode", "plan"]
    if 模型:
        參數 += ["--model", 模型]
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
        模型: str | None = None,
        工作目錄: Path | None = None,
        逾時秒: float = 300.0,
        環境: Mapping[str, str] | None = None,
    ) -> 回應:
        """問一次，拿回結構化的證據。

        `模型` 原樣傳下去不翻譯——各家的模型命名空間不交集，硬翻譯只會翻錯。
        """
        try:
            結果 = 跑cli(
                self.執行檔,
                self.組參數(提示, 模型),
                工作目錄=工作目錄,
                逾時秒=逾時秒,
                環境=環境,
            )
        except 執行逾時:
            # 逾時是**結果未知**不是確定失敗——子程序被殺時工作可能已經做了一半。
            return 回應(
                文字="",
                終局=終局判定("timeout"),
                失敗代碼="timeout",
                原始結束碼=-1,
                對話識別碼=None,
                用量=用量(輸入token=0, 輸出token=0),
            )
        return self.解析(結果.標準輸出, 結果.結束碼)


def 建立(家: 家族, *, 執行檔: Path | None = None) -> 命令列模型:
    """做一個轉接器。`執行檔` 不給就照 `找執行檔` 的順序找。"""
    if 家 not in _規格:
        可用 = "、".join(sorted(_規格))
        訊息 = f"不認得的 LLM CLI：{家}（可用：{可用}）"
        raise ValueError(訊息)
    組, 析 = _規格[家]
    return 命令列模型(名稱=家, 執行檔=執行檔 or 找執行檔(家), 組參數=組, 解析=析)
