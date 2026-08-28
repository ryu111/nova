"""nova：宿主反轉架構。

nova = harness engineering[loop engineering[llm]]

模型不是系統的主人，是被載體包住的元件。載體決定模型看得到什麼、能做什麼；
迴圈決定什麼觸發下一次嘗試、何時停止。三層定義見 docs/AGENT_ARCHITECTURE.md。
"""

from collections.abc import Sequence
from pathlib import Path
from typing import cast

from nova.契約.工作流 import 任務
from nova.契約.模型回應 import 回應, 失敗代碼, 終局
from nova.契約.角色 import 呼叫選項, 權限
from nova.載體.判準 import 建判準
from nova.載體.模型.轉接 import 家族, 建立
from nova.載體.角色 import 固定提示角色
from nova.迴圈 import 角色提示
from nova.迴圈.工作流 import 建TDD執行器, 工作流結果, 跑工作流

__version__ = "0.1.0"
__all__ = ["__version__", "問", "派工", "回應", "工作流結果", "終局", "失敗代碼", "權限"]


def 問(  # noqa: PLR0913 —— 公開簽章由門面規格固定
    提示: str,
    *,
    用: str,
    模型: str | None = None,
    工作目錄: Path | None = None,
    可編輯: bool = False,
    隔離設定: bool = True,
    逾時秒: float = 300.0,
    執行檔: Path | None = None,
) -> 回應:
    """用指定的腦詢問一次。"""
    return 建立(cast(家族, 用), 執行檔=執行檔).詢問(
        提示,
        選項=呼叫選項(
            模型=模型,
            工作目錄=工作目錄 or Path.cwd(),
            權限=權限.可編輯 if 可編輯 else 權限.唯讀,
            隔離設定=隔離設定,
            逾時秒=逾時秒,
        ),
    )


def 派工(  # noqa: PLR0913 —— 公開簽章由門面規格固定
    任務描述: str,
    *,
    用: str,
    審查用: str,
    工作目錄: Path | None = None,
    判準指令: Sequence[str] | None = None,
    最多步數: int = 12,
    執行檔: Path | None = None,
    審查執行檔: Path | None = None,
) -> 工作流結果:
    """用兩顆不同的腦跑一輪 TDD 工作流。

    `執行檔` 只給 `用` 那家，`審查執行檔` 只給 `審查用` 那家——兩家是不同的二進位，
    共用一個路徑就是拿 codex 的執行檔去跑 agy。兩個都是給測試注入假 CLI 用的，
    正式使用不給，由 `找執行檔` 自己找。
    """
    if 審查用 == 用:
        訊息 = "審查要換一顆腦"
        raise ValueError(訊息)
    執行者 = 建立(cast(家族, 用), 執行檔=執行檔)
    審查者 = 建立(cast(家族, 審查用), 執行檔=審查執行檔)
    執行 = 建TDD執行器(
        測試=固定提示角色(名稱=用, 系統提示=角色提示.測試員, 腦=執行者, 權限=權限.可編輯),
        實作=固定提示角色(名稱=用, 系統提示=角色提示.實作員, 腦=執行者, 權限=權限.可編輯),
        審查=固定提示角色(名稱=審查用, 系統提示=角色提示.審查員, 腦=審查者, 權限=權限.唯讀),
        跑判準=建判準() if 判準指令 is None else 建判準(判準指令),
    )
    目錄 = 工作目錄 or Path.cwd()
    return 跑工作流(任務(描述=任務描述, 工作目錄=目錄), 執行一步=執行, 最多步數=最多步數)
