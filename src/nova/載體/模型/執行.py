"""跑外部 CLI 的共用出口。

**執行檔路徑是參數，不信 PATH。** 本機實測：`which claude codex` 指到 cmux 的
shim，走 shim 跑 `codex exec --json` 會多吐兩條垃圾事件，直接跑真二進位就沒有。
理由和 `規則表._外部指令` 同源——PATH 會讓不同機器跑到不同東西。
"""

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from nova.契約.角色 import 預設逾時秒


class 執行逾時(Exception):
    """子程序超過時限被殺掉。"""


@dataclass(frozen=True, slots=True)
class 執行結果:
    """一次子程序執行的原始結果。"""

    標準輸出: str
    標準錯誤: str
    結束碼: int


def 跑cli(
    執行檔: Path,
    參數: Sequence[str],
    *,
    工作目錄: Path | None = None,
    逾時秒: float = 預設逾時秒,
    環境: Mapping[str, str] | None = None,
) -> 執行結果:
    """跑一次外部 CLI，回結構化結果。逾時會殺掉子程序並丟 `執行逾時`。

    `環境` 是整份取代，不是疊加——呼叫端要什麼就明講什麼，
    避免「本機有某個環境變數所以會過、CI 沒有所以會紅」這種不可重現的失敗。
    """
    if not 執行檔.exists():
        訊息 = f"找不到執行檔：{執行檔}"
        raise FileNotFoundError(訊息)
    try:
        完成 = subprocess.run(  # noqa: S603 —— 執行檔與參數由轉接器組出，不吃使用者自由字串
            [str(執行檔), *參數],
            cwd=工作目錄,
            env=dict(環境) if 環境 is not None else None,
            capture_output=True,
            text=True,
            timeout=逾時秒,
            check=False,
        )
    except subprocess.TimeoutExpired as 錯:
        訊息 = f"{執行檔.name} 超過 {逾時秒} 秒沒回應"
        raise 執行逾時(訊息) from 錯
    return 執行結果(標準輸出=完成.stdout, 標準錯誤=完成.stderr, 結束碼=完成.returncode)
