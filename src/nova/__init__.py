"""nova：宿主反轉架構。

nova = harness engineering[loop engineering[llm]]

模型不是系統的主人，是被載體包住的元件。載體決定模型看得到什麼、能做什麼；
迴圈決定什麼觸發下一次嘗試、何時停止。三層定義見 docs/AGENT_ARCHITECTURE.md。
"""

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from nova.契約.工作流 import (
    任務,
    停止條件,
    執行器,
    步驟結果,
    階段代碼,
    階段定義,
    預設單次最多token,
    預設最多token,
    預設最多步數,
)
from nova.契約.模型回應 import 回應 as 回應
from nova.契約.模型回應 import 失敗代碼 as 失敗代碼
from nova.契約.模型回應 import 終局 as 終局
from nova.契約.派工 import 派法
from nova.契約.角色 import 呼叫選項, 角色, 語言模型, 預設逾時秒
from nova.契約.角色 import 權限 as 權限
from nova.契約.額度 import 家族額度 as 家族額度
from nova.契約.額度 import 視窗 as 視窗
from nova.契約.額度 import 額度快照 as 額度快照
from nova.載體.判準 import 可作指定pytest目標, 建判準, 建重構判準, 建預設判準, 預設判準指令
from nova.載體.工作區 import 判定工作區, 拍工作區快照
from nova.載體.帳本 import 不記帳本, 帳本, 開帳本
from nova.載體.模型.接力 import 接力腦
from nova.載體.模型.本地 import 審查資格理由
from nova.載體.模型.記帳 import 記帳每一顆
from nova.載體.模型.轉接 import 家族, 建立或缺席
from nova.載體.派工表 import 怎麼派
from nova.載體.角色 import 固定提示角色
from nova.載體.重構護欄 import 動到測試了嗎
from nova.載體.階段記帳 import 記帳執行器
from nova.載體.額度 import 查詢額度
from nova.迴圈.工作流 import 建TDD執行器, 跑工作流
from nova.迴圈.工作流 import 工作流結果 as 工作流結果
from nova.迴圈.角色工廠 import 建TDD角色藍圖, 建角色表

#: `用` 可以給一家，也可以給一串（前一顆失敗就換下一顆）。
#: 字串用逗號分隔也算一串，方便從命令列傳進來。
腦來源 = str | Sequence[str]
#: `執行檔` 是給測試注入假 CLI 用的。給一條路徑＝整串都用它；
#: 給一個對照表＝每家用自己的（一串裡各家的 envelope 形狀不同，得分開給）。
執行檔來源 = Path | Mapping[str, Path] | None


def _拆成家們(來源: 腦來源) -> list[str]:
    家們 = 來源.split(",") if isinstance(來源, str) else list(來源)
    乾淨 = [家.strip() for 家 in 家們 if 家.strip()]
    if not 乾淨:
        訊息 = "至少要指定一家"
        raise ValueError(訊息)
    return 乾淨


def _挑權限(*, 可編輯: bool, 全開: bool) -> 權限:
    """全開蓋過可編輯。兩個都沒給就是唯讀——最嚴的那一邊當預設。"""
    if 全開:
        return 權限.全開
    return 權限.可編輯 if 可編輯 else 權限.唯讀


def _找執行檔(家: str, 執行檔: 執行檔來源) -> Path | None:
    """一條路徑＝整串都用它；一個對照表＝每家用自己的。"""
    if isinstance(執行檔, Mapping):
        return 執行檔.get(家)
    return 執行檔


def _建腦(
    來源: 腦來源,
    執行檔: 執行檔來源,
    帳: 帳本,
    *,
    單次最多token: int = 預設單次最多token,
) -> 語言模型:
    """把一家或一串接成一顆腦。一串會包成 `接力腦`，它本身也是一顆腦。

    **記帳包在接力鏈的裡面**（一顆腦一層）。包在外面的話「第一顆掛了換第二顆」
    會壓成一筆，換腦的原因整個消失。
    """
    家們 = _拆成家們(來源)
    # 一串裡少裝一家不該讓整串垮掉——那正是接力要處理的事（見 `缺席腦`）。
    # 只指定一家卻沒裝則是明確的設定錯誤，讓它炸。
    原始 = tuple(
        建立或缺席(
            cast(家族, 家),
            執行檔=_找執行檔(家, 執行檔),
            可以缺席=len(家們) > 1,
            記=帳.記一筆,
        )
        for 家 in 家們
    )
    腦們 = 記帳每一顆(原始, 帳, 單次最多token=單次最多token)
    if len(腦們) == 1:
        return 腦們[0]
    return 接力腦(名稱="→".join(家們), 腦們=腦們)


@contextmanager
def _開帳(目錄: Path | None) -> Iterator[帳本]:
    """給了目錄才記帳。

    **函式庫不准偷偷往使用者家目錄寫東西**——`import nova; nova.問(...)`
    產生副作用會讓人意外。CLI 是程式不是函式庫，它預設會記
    （見 `nova 問 --帳本目錄`）。
    """
    if 目錄 is None:
        yield 不記帳本()
        return
    with 開帳本(目錄) as 帳:
        yield 帳


__version__ = "0.1.0"
__all__ = [
    "__version__",
    "問",
    "派工",
    "回應",
    "工作流結果",
    "終局",
    "失敗代碼",
    "權限",
    "額度",
    "額度快照",
    "家族額度",
    "視窗",
]


def 額度(
    *,
    最舊秒: float = 0.0,
    每家: Callable[[家族額度], None] | None = None,
) -> 額度快照:
    """查詢 codex 與 agy 的訂閱限額快照。

    每拿到一家的結果就立刻呼叫一次 `每家`。
    快取比 `最舊秒` 新時直接從快取讀回。
    """
    return 查詢額度(最舊秒=最舊秒, 每家=每家)


def 問(  # noqa: PLR0913 —— 公開簽章由門面規格固定
    提示: str,
    *,
    用: 腦來源,
    模型: str | None = None,
    工作目錄: Path | None = None,
    可編輯: bool = False,
    全開: bool = False,
    隔離設定: bool = True,
    逾時秒: float = 預設逾時秒,
    續接: str | None = None,
    保留對話: bool = False,
    執行檔: 執行檔來源 = None,
    帳本目錄: Path | None = None,
) -> 回應:
    """用指定的腦詢問一次。

    `用` 給一串（`["codex", "agy"]` 或 `"codex,agy"`）就是接力：前一顆失敗換下一顆。
    **可編輯時遇到「結果未知」不會換**——可能已經改了檔案，換一顆就是做第二次。

    持久對話：第一輪給 `保留對話=True`，記下回應的 `對話識別碼`，
    下一輪用 `續接=那個識別碼` 就接得回去。接力鏈上用續接沒有意義
    （id 只屬於某一家），所以續接時請只給一家。
    """
    with _開帳(帳本目錄) as 帳:
        return _建腦(用, 執行檔, 帳).詢問(
            提示,
            選項=呼叫選項(
                模型=模型,
                工作目錄=工作目錄 or Path.cwd(),
                權限=_挑權限(可編輯=可編輯, 全開=全開),
                隔離設定=隔離設定,
                逾時秒=逾時秒,
                續接=續接,
                保留對話=保留對話,
            ),
        )


def 派工(  # noqa: PLR0913 —— 公開簽章由門面規格固定
    任務描述: str,
    *,
    用: 腦來源,
    審查用: 腦來源,
    工作目錄: Path | None = None,
    判準指令: Sequence[str] | None = None,
    最多步數: int = 預設最多步數,
    最多token: int = 預設最多token,
    單次最多token: int = 預設單次最多token,
    執行檔: 執行檔來源 = None,
    審查執行檔: 執行檔來源 = None,
    每步: Callable[[階段定義, 步驟結果], None] | None = None,
    帳本目錄: Path | None = None,
    起點: str = 階段代碼.測試.value,
    新增保證: bool = False,
) -> 工作流結果:
    """用兩顆不同的腦跑一輪 TDD 工作流。

    `用` 與 `審查用` 都可以給一串（接力），**同一家也可以**——
    判準是**對話**不是家族名：三家不給續接時本來就都是新對話
    （codex `--ephemeral`、claude 不給 `--resume`、agy 不給 `--conversation`），
    新對話沒有共享 context，看不到做事那邊的推理過程，只看得到產出。
    換一家能多減一層（不同權重、不同偏誤），但那是加分不是門檻。

    **真正要擋的「自寫自評」是做事與審查跑在同一個對話裡**，
    而那在結構上不可能：`固定提示角色` 組呼叫選項時沒有續接這個欄位。
    由 `tests/單元/test_換腦判準.py::test_角色結構上不可能續接到同一個對話` 守著。

    `本地腦不能當審查員`；命令列與這個門面都會在建腦前檢查。

    `執行檔` 只給 `用` 那邊，`審查執行檔` 只給 `審查用` 那邊——不同家是不同的二進位。
    兩個都是給測試注入假 CLI 用的，正式使用不給，由 `找執行檔` 自己找。

    `每步` 每跑完一個階段被呼叫一次，讓呼叫端能邊跑邊回報進度。

    兩個停止條件都有預設值：`最多步數` 擋來回幾次，`最多token` 擋花多少。
    **忘了傳不等於沒有上限**——沒有預設的保證是懇求，不是保證。
    """
    從哪開始 = _認起點(起點)
    做事的, 審查的 = _拆成家們(用), _拆成家們(審查用)
    不合格理由 = 審查資格理由(審查的)
    if 不合格理由 is not None:
        raise ValueError(不合格理由)
    with _開帳(帳本目錄) as 帳:
        return _跑一輪(
            任務描述,
            做事的=做事的,
            審查的=審查的,
            工作目錄=工作目錄,
            判準指令=判準指令,
            停止=停止條件(
                最多步數=最多步數,
                最多token=最多token,
                單次最多token=單次最多token,
            ),
            執行檔=執行檔,
            審查執行檔=審查執行檔,
            每步=每步,
            帳=帳,
            起點=從哪開始,
            新增保證=新增保證,
        )


def _建TDD角色表(執行者: 語言模型, 審查者: 語言模型) -> Mapping[階段代碼, 角色]:
    """用兩顆已建好的腦，組出 TDD 的角色表。

    這裡是組裝點：派工表與固定提示角色都是**載體**的東西，由這裡當參數傳進迴圈。
    """
    藍圖們 = 建TDD角色藍圖(怎麼派)
    審查派法 = 藍圖們[-1].派法

    def 建腦(角色派法: 派法) -> 語言模型:
        return 審查者 if 角色派法 == 審查派法 else 執行者

    return cast(
        Mapping[階段代碼, 角色],
        建角色表(藍圖們, 建腦=建腦, 組角色=固定提示角色),
    )


def _跑一輪(  # noqa: PLR0913 —— 全部是 派工 的參數，收成物件只是換個地方列
    任務描述: str,
    *,
    做事的: list[str],
    審查的: list[str],
    工作目錄: Path | None,
    判準指令: Sequence[str] | None,
    停止: 停止條件,
    執行檔: 執行檔來源,
    審查執行檔: 執行檔來源,
    每步: Callable[[階段定義, 步驟結果], None] | None,
    帳: 帳本,
    起點: 階段代碼,
    新增保證: bool,
) -> 工作流結果:
    """接好零件跑一輪。拆出來只為了讓 `派工` 的 `with` 區塊短到看得完。"""
    執行者 = _建腦(做事的, 執行檔, 帳, 單次最多token=停止.單次最多token)
    審查者 = _建腦(審查的, 審查執行檔, 帳, 單次最多token=停止.單次最多token)
    這次的判準指令 = 預設判準指令 if 判準指令 is None else tuple(判準指令)
    執行 = 建TDD執行器(
        角色表=_建TDD角色表(執行者, 審查者),
        # 沒指定就用預設判準（全測試 ＋ 提交閘），不是只有全測試。
        跑判準=建預設判準() if 判準指令 is None else 建判準(判準指令),
        跑重構判準=建重構判準(),
        # `驗證紅` 只驗這一輪動過的那幾支測試——整套 suite 的非零退出可能是別人的紅。
        建指定測試判準=lambda 檔們: 建判準((*這次的判準指令, *檔們)),
        篩選指定測試=可作指定pytest目標,
    )
    目錄 = 工作目錄 or Path.cwd()
    return 跑工作流(
        任務(描述=任務描述, 工作目錄=目錄, 新增保證=新增保證),
        執行一步=記帳執行器(_邊跑邊回報(執行, 每步), 帳, 單次最多token=停止.單次最多token),
        停止=停止,
        起點=起點,
        拍快照=拍工作區快照,
        動到測試了嗎=動到測試了嗎,
        判定工作區=判定工作區,
    )


def _邊跑邊回報(內層: 執行器, 每步: Callable[[階段定義, 步驟結果], None] | None) -> 執行器:
    """一輪工作流要跑好幾分鐘，呼叫端需要知道走到哪了。

    包一層而不是把印出來寫進 `跑工作流`——那支不該知道有沒有人在看。
    """
    if 每步 is None:
        return 內層

    def 執行一步(定義: 階段定義, 任: 任務, 軌跡: tuple[步驟結果, ...]) -> 步驟結果:
        結果 = 內層(定義, 任, 軌跡)
        每步(定義, 結果)
        return 結果

    return 執行一步


def _認起點(起點: str) -> 階段代碼:
    """字串 → 階段代碼。**打錯字要當場炸**，不要靜默從頭跑一輪。

    收字串不收列舉是因為它從命令列來；轉換只做一次，在門面這一層。
    """
    try:
        return 階段代碼(起點)
    except ValueError as 錯:
        可用 = "、".join(代碼.value for 代碼 in 階段代碼)
        訊息 = f"不認得的起點：{起點}（可用：{可用}）"
        raise ValueError(訊息) from 錯
