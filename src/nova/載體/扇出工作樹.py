"""把「每顆分支一棵 git worktree」接到扇出 runner 上。

住載體不住迴圈，理由是架構閘那條：`迴圈/` 不准 import `載體/`，
所以**開樹、收樹都在這一側**，迴圈只收到一個已經開好的路徑。
形狀跟 `載體/命令列.py` 把載體的能力交給迴圈時一樣：呼叫端先把東西準備好，
再當參數送進去。

誰開、開不出來怎麼辦、誰收——三件事各由下面一支函式回答，
理由就寫在那支函式上。
"""

import warnings
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from nova.契約.扇出 import 分支工作, 扇出政策, 扇出結果, 開不出工作樹
from nova.契約.節點 import 節點上下文, 節點結果
from nova.載體.工作樹 import 收掉工作樹, 開一個工作樹
from nova.迴圈.扇出 import 執行扇出

__all__ = ["帶著工作樹扇出"]


def 帶著工作樹扇出[輸入, 輸出, 依賴](  # noqa: PLR0913 —— 扇出原本的四個參數再加開樹要的三個
    工作: tuple[分支工作[輸入, 依賴], ...],
    *,
    執行一顆: Callable[[分支工作[輸入, 依賴], 節點上下文], 節點結果[輸出]],
    上下文: 節點上下文,
    政策: 扇出政策,
    專案: Path,
    樹根: Path,
    起點commit: str,
) -> 扇出結果[輸出]:
    """先替每顆分支開一棵工作樹，再照常扇出，最後一定回頭收樹。

    `finally` 只在程序自己跑完時算話：被 kill 掉的話一棵樹都不會收，
    連收不掉時的那句話都不會出現——**殘骸的可見性由 `nova 線` 負責，不是這裡**。
    """
    樹根.mkdir(parents=True, exist_ok=True)
    帶樹的工作 = tuple(
        _開這顆的樹(工作項, 專案=專案, 樹根=樹根, 起點commit=起點commit) for 工作項 in 工作
    )
    try:
        return 執行扇出(帶樹的工作, 執行一顆=執行一顆, 上下文=上下文, 政策=政策)
    finally:
        _收掉這批的樹(帶樹的工作)


def _開這顆的樹[輸入, 依賴](
    工作項: 分支工作[輸入, 依賴],
    *,
    專案: Path,
    樹根: Path,
    起點commit: str,
) -> 分支工作[輸入, 依賴]:
    """開一棵給這顆分支的樹；開不出來就把失敗記在工作上，不是丟出去。

    丟出去的話一棵開不出來的樹會讓整批扇出掛掉，其他分支明明還跑得動；
    記成 `開不出工作樹`，runner 會跳掉那一顆，整批照跑。
    **不准退回共用工作目錄**，那是假隔離。
    """
    落點 = 樹根 / str(工作項.分支)
    try:
        開一個工作樹(專案, 落點=落點, 起點commit=起點commit)
    except OSError as 出事:
        return replace(工作項, 工作樹=開不出工作樹(原因=str(出事)))
    return replace(工作項, 工作樹=落點)


def _收掉這批的樹[輸入, 依賴](工作: tuple[分支工作[輸入, 依賴], ...]) -> None:
    """收掉這批扇出開出來的樹。

    收得掉的只有乾淨的樹：只要那顆分支寫過檔（含 `收集證據` 動過 index 的），
    `收掉工作樹` 會拒絕，於是留現場。硬 `--force` 等於把現場銷毀，所以不做。
    留現場的那些這裡只負責讓它出聲、並指去 `nova 線`（`載體/線.py` 的
    `git worktree list --porcelain`，帶未提交檔案數與最後改動時間）——
    查殘骸是那條指令的事。
    """
    for 工作項 in 工作:
        開出來的那棵 = 工作項.工作樹
        if not isinstance(開出來的那棵, Path):
            # `開不出工作樹` 與 `None` 都沒有開出來的樹，沒有現場可收。
            continue
        try:
            收掉工作樹(開出來的那棵)
        except OSError as 出事:
            warnings.warn(f"扇出留下一棵有產出的工作樹，用 `nova 線` 找它：{出事}", stacklevel=2)
