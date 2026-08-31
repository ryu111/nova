"""三個薄轉接器：把各家 CLI 退回成一顆腦。

每個轉接器只有兩件事——**怎麼組參數**與**用哪支解析器**。
其餘（子程序、逾時、工作目錄）全部共用，所以加第四家的成本是一筆資料。

轉接器的核心職責是**把該家自帶的載體關到最小**（工具、家目錄設定、自帶
system prompt），讓「換腦但行為一樣」成立。哪幾條旗標做這件事，
由 `tests/整合/test_模型轉接.py::Test把各家載體關到最小` 背書。
"""

import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from time import monotonic
from typing import Literal

from nova.契約.帳本 import 記一筆
from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局判定
from nova.契約.角色 import 呼叫選項, 權限, 語言模型, 預設選項
from nova.載體.模型.執行 import 執行逾時, 跑cli
from nova.載體.模型.接力 import 缺席腦
from nova.載體.模型.本地 import 家族名 as 本地家族名
from nova.載體.模型.本地 import 本地腦, 網址環境變數, 預設本地網址
from nova.載體.模型.解析 import 撿對話識別碼, 解析agy, 解析claude, 解析codex

#: `local` 是本機的 OpenAI 相容端點（omlx-server／llama.cpp／ollama），
#: 形狀跟另外三家完全不同：它只有腦，沒有 CLI、沒有工具、沒有 session。
#: **它裝得進來，就證明 `語言模型` Protocol 是模型形狀不是 CLI 形狀。**
家族 = Literal["claude", "codex", "agy", "local"]
預設候選目錄 = (Path.home() / ".local" / "bin",)

組參數型 = Callable[[str, 呼叫選項], list[str]]
#: 解析一次 CLI 執行要三樣東西：stdout、結束碼、**stderr**。
#: 少了第三樣，「CLI 明明講了為什麼失敗」就會變成「不知道發生什麼事」。
解析型 = Callable[[str, int, str], 回應]


#: 可編輯模式下 claude 需要的工具。列白名單不用 "default"——要哪些寫出來。
_claude可編輯工具 = "Read,Write,Edit,Bash,Grep,Glob"
#: 唯讀模式的白名單。**不要換回 `--tools ""`**——那條的 help 原文是
#: 「Use "" to disable all tools」，而 all 是真的 all，連 Read 都沒了。
#: 實測叫它讀工作目錄裡的檔案，回的是「I don't have any file access tools available」。
#: 唯讀的意思是**看得到但不准改**，不是什麼都看不到。
_claude唯讀工具 = "Read,Grep,Glob"


def _claude權限參數(選項: 呼叫選項) -> list[str]:
    """三級權限各自要哪幾條旗標。抽出來是為了讓 `_claude組參數` 的分支數壓在門檻內。

    可編輯這一級**三條缺一不可**，每一條都是被實測咬出來的：

    | 旗標 | 少了它會怎樣 |
    |---|---|
    | `--tools <清單>` | 沒有 Write／Edit 可用 |
    | `--allowedTools <同一份清單>` | 隔離設定之下卡在「pending approval」，一個字都寫不出來 |
    | `--restricted --add-dir <工作目錄>` | 自己猜路徑，實測寫進了 nova 的 repo 根目錄 |

    `--restricted` 的 help 原文寫明它 **refuses bypassPermissions**，
    所以全開那一級不能帶它。
    """
    if 選項.權限 is 權限.全開:
        return ["--tools", _claude可編輯工具, "--dangerously-skip-permissions"]
    界線 = ["--restricted"]
    if 選項.工作目錄 is not None:
        # 沒有工作目錄就沒有正確的值可填——寧可不加，也不要拿 cwd 去猜。
        界線 += ["--add-dir", str(選項.工作目錄)]
    if 選項.權限 is 權限.唯讀:
        # 唯讀也要 `--restricted`：它把**檔案工具**關在工作目錄裡，Read 也算。
        # 不給 `--allowedTools`——實測唯讀那三個工具不需要核准就跑得動。
        return [*界線, "--tools", _claude唯讀工具]
    return [
        *界線,
        "--tools",
        _claude可編輯工具,
        "--allowedTools",
        _claude可編輯工具,
        "--permission-mode",
        "acceptEdits",
    ]


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
        #
        # `--strict-mcp-config` 是另一半：設定來源關掉了，**MCP server 還是另一條路**。
        # `--tools` 的 help 原文是「from the built-in set」——MCP 工具不是 built-in，
        # 白名單根本沒把它們算進去。`--restricted` 的 help 自己寫明
        # 「add --strict-mcp-config to skip MCP servers too」。
        # 不給 `--mcp-config` 就等於零台，正是想要的結果。
        參數 += ["--setting-sources", "", "--strict-mcp-config"]
    if 選項.續接:
        參數 += ["--resume", 選項.續接]
    參數 += _claude權限參數(選項)
    參數 += ["--system-prompt", ""]  # 順便終結上面的變長參數，不要調換順序
    if 選項.模型:
        參數 += ["--model", 選項.模型]
    if 選項.思考深度:
        參數 += ["--effort", 選項.思考深度]
    return [*參數, 提示]


#: codex 只用這兩個型號（使用者裁定）。luna 是常用的，sol 是高階推理。
codex常用模型 = "gpt-5.6-luna"
codex高階模型 = "gpt-5.6-sol"
#: 目前只有一顆；只給派工表斷言使用。
高階模型們 = frozenset({codex高階模型})


def 決定逾時秒(選項: 呼叫選項) -> float:
    """保留的接縫：原樣採用呼叫端的逾時，不依模型名稱加長或縮短。"""
    return 選項.逾時秒


#: 開網路的設定鍵。**只對 `workspace-write` 有效**——`read-only` 沒有這個概念。
codex網路設定 = "sandbox_workspace_write.network_access"


#: codex **沒有** `--effort` 旗標（實測 `codex exec --help`），推理強度走設定覆寫。
#: 值要是合法的 TOML，所以字串得再包一層引號。
codex推理強度 = "max"


def _codex共通參數(選項: 呼叫選項) -> list[str]:
    """`exec` 與 `exec resume` 都吃的那幾條。"""
    # **取代寫死那條，不是再加一條**：兩條 `-c` 同一個鍵，
    # 哪一條贏是 codex 的實作細節，那等於沒有保證。
    深 = 選項.思考深度 or codex推理強度
    參數 = ["--json", "--skip-git-repo-check", "-c", f'model_reasoning_effort="{深}"']
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
        # **不要換成 `--approve-for-me`**（那兩條互斥，一起給會 exit 2）。
        # 它的 help 原文是「Route approval requests through automatic review using
        # the workspace-write sandbox」——**自動審核**，不是不准：實測叫它
        # `printf > ~/x.txt`，模型說「這在工作區外需要額外權限」然後自己核准，exit 0。
        # `--sandbox workspace-write` 才是真邊界（同一條指令 operation not permitted），
        # 而且是三家裡唯一的 OS 層邊界。代價是沙箱同時關掉網路——裝套件要用全開。
        # 沙箱**同時**關掉網路（實測 `curl` 回 `000`）。研究類的委派沒有網路等於廢的，
        # 而這一條把網路打開之後檔案邊界照樣在（同一條 `printf > ~/x.txt` 還是
        # operation not permitted）——**這家開網路沒有代價**，所以是預設不是旗標。
        共通 += ["--sandbox", "workspace-write", "-c", f"{codex網路設定}=true"]
    else:
        # 全開才用這條——它連沙箱都拿掉。
        共通 += ["--dangerously-bypass-approvals-and-sandbox"]
    return ["exec", *共通, 提示]


#: 只有這一族的深度包在型號後綴裡。claude／gpt 那些是 agy 代跑的，型號要原樣送。
_agy有深度後綴的族 = "gemini-"

#: agy 的推理強度包在型號裡（`agy models` 實測），不是另一個旗標。
agy預設模型 = "gemini-3.7-flash-high"


def _agy型號(選項: 呼叫選項) -> str:
    """agy 的深度**是型號的一部分**，所以旋鈕轉的是型號後綴。

    後綴不存在就補上去（`gemini-3.1-pro` → `gemini-3.1-pro-low`），
    已經有就換掉——不換的話 `--模型 …-high --思考深度 low` 會安靜地照 high 跑。

    **但只有 gemini 那一族是這個規則。** agy 也代跑 claude 與 gpt 的型號
    （`agy models` 實測列得出 `claude-sonnet-4-6`、`claude-opus-4-6-thinking`、
    `gpt-oss-120b-medium`），那些型號**沒有深度後綴這回事**——
    補上去就送出一個不存在的型號。而那條通道的額度是**獨立的一池**，
    走不到等於整池浪費。
    """
    型 = 選項.模型 or agy預設模型
    if not 型.startswith(_agy有深度後綴的族):
        return 型
    組好 = _agy後綴.sub("", 型) + f"-{選項.思考深度}" if 選項.思考深度 else 型
    if 組好 != agy預設模型:
        訊息 = (
            f"agy 的 gemini 只准 {agy預設模型}，你給的是 {組好}"
            "——那一族共用同一份額度，換型號只會用更貴的單價吃同一池。"
            "claude／gpt 那些是另一個池，不受這條限制"
        )
        raise ValueError(訊息)
    return 組好


def _agy組參數(提示: str, 選項: 呼叫選項) -> list[str]:
    # agy 查不到設定隔離的旗標（見設計文件 02 缺口），所以 隔離設定 對它是 no-op。
    模式 = "plan" if 選項.權限 is 權限.唯讀 else "accept-edits"
    參數 = ["--output-format", "json", "--mode", 模式]
    if 選項.權限 is not 權限.唯讀:
        # agy 的 `read_url`（網路）被 headless 權限系統 auto-deny，唯一的開關就是這條。
        #
        # **代價是真的**：auto-deny 正是 agy 唯一的越界保護
        # （`--sandbox` 與 `--mode plan` 都擋不住寫，三種組合都實測過）。
        # 打開它，agy 的可編輯就跟全開一樣沒有邊界——使用者裁定接受這個交換，
        # 由 `test_agy的可編輯沒有邊界這是已知事實` 誠實釘住，不假裝有保證。
        參數 += ["--dangerously-skip-permissions"]
    if 選項.工作目錄 is not None:
        # `--add-dir` 決定 agy 動得到哪個目錄，**而不是 cwd**。實測三件事：
        #
        # 1. 不給它：檔案工具寫到 `~/.gemini/antigravity-cli/scratch/`，而且照樣
        #    回報 SUCCESS——模型沒說謊，它真的寫了，只是寫到別的地方。
        # 2. 不給它而叫它讀 cwd 的檔案：工具被 headless 的權限系統 auto-deny，
        #    回一個空的 response（`_成功但沒話說算未知` 會把它降成結果未知）。
        # 3. 給它：讀寫都進 cwd。**但 `--mode plan` 擋不住寫**（實測，見設計文件 02）。
        #
        # 三種權限都給。一度為了 3 而讓唯讀不給 `--add-dir`——那條保證是真的
        # （動不到工作目錄），但它把唯讀的用途一起換掉了：連讀都讀不到，
        # 而 nova 唯一的唯讀呼叫端是工作流的審查員。理由寫在
        # `test_agy三種權限都要給add_dir` 的 docstring 裡。
        參數 += ["--add-dir", str(選項.工作目錄)]
    參數 += ["--model", _agy型號(選項)]
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


#: 逾時的時候最多帶回多少字的部分輸出。實測 codex 被殺當下有 20,865 字元，
#: 整包塞進回應會把終端機洗掉——而真正有用的（sid、前幾步在做什麼）都在開頭。
部分輸出上限 = 12_000


def _逾時診斷(耗時秒: float | None, 上限秒: float | None) -> str:
    """有完整計時資料時才產生逾時診斷，否則保留舊的回應文字。"""
    if 耗時秒 is None or 上限秒 is None:
        return ""
    return f"結果未知：這次呼叫跑了 {耗時秒:.1f} 秒，上限 {上限秒:g} 秒；不准重跑，去看工作區。\n"


def 逾時的回應(
    解析: 解析型,
    部分標準輸出: str,
    部分標準錯誤: str = "",
    *,
    耗時秒: float | None = None,
    上限秒: float | None = None,
) -> 回應:
    """逾時是**結果未知**——但子程序已經吐出來的東西不該一起丟掉。

    **終局、失敗代碼、原始結束碼、用量一律不從解析結果來。**
    解析得動不等於跑完了：半途的輸出照樣解析得出東西，
    讓它決定終局就是拿半成品當成品——而結果未知在可編輯下不准自動重跑，
    「成功」卻會被當成做完了。所以這裡只從半成品抄兩樣：**對話識別碼與文字**。
    耗時與上限都是選配；沒有它們時不加診斷前綴，以保留直接呼叫的舊回應形狀。

    對話識別碼是整條路的關鍵：有它才 `--續接` 得了，
    才談得上「接著剛剛的思考做下去」而不是從頭重做。
    """
    逾時訊息 = _逾時診斷(耗時秒, 上限秒) + _逾時標準錯誤(部分標準輸出, 部分標準錯誤)
    逾時回應 = 回應(
        文字=逾時訊息,
        終局=終局判定(失敗代碼.逾時),
        失敗代碼=失敗代碼.逾時,
        原始結束碼=-1,
        對話識別碼=None,
        用量=用量(輸入token=0, 輸出token=0),
    )
    if not 部分標準輸出.strip():
        return 逾時回應
    部分回應 = 解析(部分標準輸出, -1, 部分標準錯誤)
    return replace(
        逾時回應,
        對話識別碼=部分回應.對話識別碼 or 撿對話識別碼(部分標準輸出),
        文字=逾時訊息 + (部分回應.文字 or 部分標準輸出)[:部分輸出上限],
    )


def _逾時標準錯誤(部分標準輸出: str, 部分標準錯誤: str) -> str:
    """標準輸出全空時，留下子程序最後的標準錯誤。"""
    if 部分標準輸出.strip():
        return ""
    標準錯誤 = 部分標準錯誤.strip()
    if not 標準錯誤:
        return ""

    最後一行 = 標準錯誤.splitlines()[-1]
    訊息 = f"子程序最後印出（不代表停在這裡）：{最後一行}\n"
    if 標準錯誤 == "Reading additional input from stdin...":
        訊息 += "子程序沒有實質回應；這次只收到開場白。\n"
    return 訊息


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
        實際逾時秒 = 決定逾時秒(選項)
        開始時間 = monotonic()
        try:
            結果 = 跑cli(
                self.執行檔,
                self.組參數(提示, 選項),
                工作目錄=選項.工作目錄,
                逾時秒=實際逾時秒,
                環境=環境,
            )
        except 執行逾時 as 錯:
            return 逾時的回應(
                self.解析,
                錯.部分標準輸出,
                錯.部分標準錯誤,
                耗時秒=monotonic() - 開始時間,
                上限秒=實際逾時秒,
            )
        答 = self.解析(結果.標準輸出, 結果.結束碼, 結果.標準錯誤)
        return _補上認證提示(答, self.名稱, 選項)


def 建立(
    家: 家族,
    *,
    執行檔: Path | None = None,
    記: 記一筆 | None = None,
) -> 語言模型:
    """做一個轉接器。`執行檔` 不給就照 `找執行檔` 的順序找。

    `local` 走的是 HTTP 不是子程序，所以它不吃 `執行檔`——
    **不准為了三家對稱而假裝它有執行檔**，那會讓 `--執行檔` 看起來有效卻沒效。
    """
    if 家 == 本地家族名:
        if 執行檔 is not None:
            訊息 = f"{本地家族名} 走 HTTP 不吃 --執行檔，網址請用 {網址環境變數}"
            raise ValueError(訊息)
        return 本地腦(網址=預設本地網址(), 記=記)
    return 建命令列(家, 執行檔=執行檔)


#: 思考深度的統一詞彙。**順序就是深淺**，最後一個最深。
#: 值走 ASCII（要原樣傳進三家的 CLI，CLAUDE.md 的跨程序例外）。
思考深度們 = ("low", "medium", "high", "xhigh", "max")

#: agy 沒有旗標，深度是型號後綴（`agy models` 實測），而它只有三階。
#: **不足的那幾階不准默默降級**——降了使用者會以為叫到最深，
#: 帳照付、深度沒開、沒有訊息。
agy有的深度 = ("low", "medium", "high")
_agy後綴 = re.compile(r"-(?:low|medium|high)$")


def _檢查深度(家: str, 深: str | None) -> None:
    """統一介面先擋一次：不認得的值當場炸，訊息指得回 nova。

    傳下去的話報錯的是 CLI，而它的訊息說不出「nova 收了一個打錯的旗標」。
    """
    if 深 is None:
        return
    if 深 not in 思考深度們:
        訊息 = f"不認得的思考深度 {深!r}——只准 {'、'.join(思考深度們)}"
        raise ValueError(訊息)
    if 家 == "agy" and 深 not in agy有的深度:
        訊息 = (
            f"agy 只有 {'、'.join(agy有的深度)} 三階（深度是型號後綴，不是旗標），"
            f"給不了 {深!r}。**不自動降級**：降了你會以為叫到最深，"
            f"而帳照付、深度沒開。要更深就換一家"
        )
        raise ValueError(訊息)


def 建命令列(家: 家族, *, 執行檔: Path | None = None) -> 命令列模型:
    """只做 CLI 那三家。**回的是具體型別不是 Protocol。**

    `命令列模型.詢問` 比 `語言模型` 多收一個 `環境`（整份取代子程序的環境），
    而那是 CLI 才有的概念——本地模型走 HTTP，沒有子程序可以給環境。
    需要那個參數（或 `組參數`）的呼叫端要明講自己要的是 CLI 這一種形狀，
    **不要用 cast 從 `建立` 的回傳值硬轉**：那等於把型別檢查關掉。
    """
    if 家 not in _規格:
        可用 = "、".join(sorted([*_規格, 本地家族名]))
        訊息 = f"不認得的 LLM CLI：{家}（可用：{可用}）"
        raise ValueError(訊息)
    組, 析 = _規格[家]

    def 組並先擋(提示: str, 選項: 呼叫選項) -> list[str]:
        """**擋在組參數這一層**，不是在命令列那一層。

        擋在上面的話，任何繞過命令列直接建腦的呼叫端都會漏掉這道檢查——
        而漏掉的症狀是「安靜地沒有生效」，那是最難發現的一種。
        """
        _檢查深度(家, 選項.思考深度)
        return 組(提示, 選項)

    return 命令列模型(名稱=家, 執行檔=執行檔 or 找執行檔(家), 組參數=組並先擋, 解析=析)


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


def 建立或缺席(
    家: 家族,
    *,
    執行檔: Path | None,
    可以缺席: bool,
    記: 記一筆 | None = None,
) -> 語言模型:
    """建一顆腦；`可以缺席` 時，沒裝的那家降級成 `缺席腦` 而不是丟例外。

    **只有在鏈上才可以缺席。** 只指定一家卻沒裝是明確的設定錯誤，
    早點炸比較好；一串裡少一家則正是接力要處理的事。
    """
    try:
        return 建立(家, 執行檔=執行檔, 記=記)
    except FileNotFoundError as 錯:
        if not 可以缺席:
            raise
        return 缺席腦(名稱=家, 原因=str(錯))
