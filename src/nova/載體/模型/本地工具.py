"""給本地模型的工具箱。

本地腦原本只會回文字，`_做不到的地方` 直接擋掉可編輯權限，理由寫著
「本地模型沒有工具」。2026-08-31 驗到那句話是錯的：端點吃 OpenAI 相容的
`tools` 參數，27B 會回 `tool_calls`，也吃得下 `role: "tool"` 的結果再收尾。
缺的一直是 nova 這一側。

**沒有 exec。** TDD 的驗證紅／驗證綠是機械判準階段（帳本裡是 `verify-red`，
0 token），模型從頭到尾不需要自己跑 pytest。不給 exec 就沒有沙箱問題要解。

**路徑一律圈在工作目錄裡。** 模型指揮的路徑是不可信輸入，而 repo 是 public。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nova.契約.角色 import 權限

#: 一次工具呼叫最多回這麼多字元。本地模型的 context 比雲端小，
#: 讀兩個大檔就爆——而爆掉的樣子是「模型突然開始胡言亂語」，
#: 看起來像模型笨，不像工具壞了。
結果上限 = 8_000

#: grep 最多回幾行。同上理由，而且 grep 打到大檔時行數會爆。
搜尋上限 = 60

#: 一次 `write_file` 最多寫這麼多字元。
#:
#: **本地跑不燒 API 額度，所以風險不在 usage，在資源控管**：模型寫一個超大的
#: content 就吃掉磁碟，而且不會有帳單來提醒你。
單檔寫入上限 = 200_000

#: 一個工具箱最多寫幾個檔案。工具箱只服務一次 `詢問`，所以這就是
#: 「這一輪最多動幾個檔」。
#:
#: 沒有這條的話，模型可以在回合上限內把整個工作目錄覆蓋掉——
#: **每一次寫入本身都合法，合起來是災難。**
單輪寫檔上限 = 12


class 工具錯誤(Exception):
    """工具做不到這件事。**訊息會原樣回給模型**，所以要講得出下一步。"""


def _規格(名稱: str, 說明: str, 參數: dict[str, str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": 名稱,
            "description": 說明,
            "parameters": {
                "type": "object",
                "properties": {
                    名: {"type": "string", "description": 述} for 名, 述 in 參數.items()
                },
                "required": list(參數),
            },
        },
    }


@dataclass(frozen=True, slots=True)
class 工具箱:
    """一個工作目錄 ＋ 一組權限，決定模型拿得到哪些工具。

    **權限決定給什麼工具，不是給了工具再檢查權限**——給了 write 再在執行時擋，
    等於讓模型每一輪撞一次牆、每一次都燒 token。唯讀就不要把那把刀放在桌上。
    （執行時仍然再擋一次：模型硬叫一個沒給它的工具時不准真的寫下去。）
    """

    #: `None` ＝ **沒有指定範圍**，那時候一把工具都不給（fail-closed）。
    #:
    #: 原本寫成「沒給就用 `Path.cwd()`」——`nova 問 --用 local` 隨手一問，
    #: 模型就拿到讀取當前所在目錄的能力，而使用者以為自己只是問了一句話。
    #: **「沒指定範圍」不該被解讀成「範圍是這裡」。**
    工作目錄: Path | None
    可以做什麼: 權限
    #: 這些子樹底下**讀得到但寫不進去**。
    #:
    #: 「實作員不准改測試檔」原本只寫在角色提示裡——那是懇求。測試是驗收機制，
    #: 讓實作階段的模型改得到它，等於自己給自己發及格證。工具箱不給那把刀，
    #: 模型「不用知道、不用記得、也違反不了」。
    #:
    #: 讀要留著：實作員得看測試在斷言什麼才寫得出實作。**擋的是寫不是讀。**
    不准寫: tuple[str, ...] = ()
    #: 這一輪已經寫過的檔案。`frozen` 擋的是欄位重綁，不是容器內容。
    _寫過的: list[str] = field(default_factory=list)

    @property
    def 寫過檔了嗎(self) -> bool:
        """催收尾的觸發條件——**已經在寫的就別吵它**。"""
        return bool(self._寫過的)

    @property
    def _可以寫(self) -> bool:
        return self.可以做什麼 is not 權限.唯讀

    def 規格(self, *, 只留寫入: bool = False) -> list[dict[str, Any]]:
        """OpenAI 相容的 `tools` 陣列。**沒有工作目錄就一把都不給。**

        少了工具模型只是回得笨一點；多了工具卻沒有範圍，是它讀得到你剛好
        `cd` 進去的任何地方。

        `只留寫入` 是收尾用的：回合快用完時，把找東西的工具收掉。
        **倒數提醒是懇求，收掉工具才是保證**——模型連發出那個呼叫的形狀
        都沒有。唯讀角色這時會拿到空陣列，那是對的：唯讀的產出本來就是
        文字報告，不是檔案。
        """
        if self.工作目錄 is None:
            return []
        工具們 = (
            []
            if 只留寫入
            else [
                _規格("read_file", "讀取工作目錄下的一個檔案", {"path": "相對於工作目錄的路徑"}),
                _規格(
                    "grep",
                    "在工作目錄裡搜尋字串，回符合的檔案與行。先用它定位，不要整包讀。",
                    {"pattern": "要找的字串"},
                ),
            ]
        )
        if self._可以寫:
            工具們.append(
                _規格(
                    "write_file",
                    "把內容寫進工作目錄下的檔案（整份覆蓋）",
                    {"path": "相對於工作目錄的路徑", "content": "完整的檔案內容"},
                )
            )
        return 工具們

    def 執行(self, 名稱: str, 參數: dict[str, Any]) -> str:
        """跑一個工具，回給模型看的文字。做不到就 `工具錯誤`。"""
        if 名稱 == "read_file":
            return self._讀(str(參數.get("path", "")))
        if 名稱 == "grep":
            return self._搜(str(參數.get("pattern", "")))
        if 名稱 == "write_file":
            if not self._可以寫:
                訊息 = "這一輪是唯讀，不能寫檔案。只回報你會怎麼改，不要嘗試寫入。"
                raise 工具錯誤(訊息)
            return self._寫(str(參數.get("path", "")), str(參數.get("content", "")))
        訊息 = f"沒有 {名稱} 這個工具"
        raise 工具錯誤(訊息)

    def _圈在裡面(self, 路徑字串: str) -> Path:
        if self.工作目錄 is None:
            訊息 = "這一輪沒有指定工作目錄，任何檔案都不准碰。"
            raise 工具錯誤(訊息)
        """把模型給的路徑解析成真實路徑，**確認它沒有跑出工作目錄**。

        判斷要在解析**之後**做：`工作目錄/../../etc/passwd` 字串上看起來在裡面，
        解析完才看得出它跑出去了。而只比對字串前綴會被 `/tmp/區-偷` 這種
        同前綴的兄弟目錄騙過去——所以用 `is_relative_to` 比路徑節點，不比字元。
        """
        根 = self.工作目錄.resolve()
        目標 = (根 / 路徑字串).resolve()
        if not 目標.is_relative_to(根):
            訊息 = f"{路徑字串} 在工作目錄外面，不准碰。路徑要相對於工作目錄。"
            raise 工具錯誤(訊息)
        return 目標

    def _截(self, 文字: str) -> str:
        """**截斷了就要講**——不講的話模型會以為自己讀完了，然後根據半份檔案下判斷。"""
        if len(文字) <= 結果上限:
            return 文字
        return f"{文字[:結果上限]}\n\n[已截斷：原文 {len(文字)} 字，只給前 {結果上限} 字]"

    def _讀(self, 路徑字串: str) -> str:
        目標 = self._圈在裡面(路徑字串)
        if not 目標.is_file():
            訊息 = f"{路徑字串} 不是一個檔案（可能不存在，或它是目錄）"
            raise 工具錯誤(訊息)
        return self._截(目標.read_text(encoding="utf-8", errors="replace"))

    def _寫(self, 路徑字串: str, 內容: str) -> str:
        if len(內容) > 單檔寫入上限:
            訊息 = (
                f"內容太大（{len(內容)} 字，上限 {單檔寫入上限}）。分次寫，或只寫真的要改的部分。"
            )
            raise 工具錯誤(訊息)
        if len(self._寫過的) >= 單輪寫檔上限:
            訊息 = (
                f"這一輪已經寫了 {len(self._寫過的)} 個檔案，到上限了。"
                f"先回報你改了什麼，下一輪再繼續。"
            )
            raise 工具錯誤(訊息)
        目標 = self._圈在裡面(路徑字串)
        self._擋下不准寫的(目標, 路徑字串)
        目標.parent.mkdir(parents=True, exist_ok=True)
        目標.write_text(內容, encoding="utf-8")
        self._寫過的.append(路徑字串)
        return f"已寫入 {路徑字串}（{len(內容)} 字）"

    def _擋下不准寫的(self, 目標: Path, 路徑字串: str) -> None:
        """`tests` 擋住時 `tests-資料` 不該跟著被擋——**比路徑節點，不比字元**。"""
        if self.工作目錄 is None:
            return
        根 = self.工作目錄.resolve()
        for 子樹 in self.不准寫:
            if 目標.is_relative_to((根 / 子樹).resolve()):
                訊息 = (
                    f"{路徑字串} 在 {子樹}/ 底下，這一輪不准寫。讀得到，但要改的話是別的階段的事。"
                )
                raise 工具錯誤(訊息)

    def _搜(self, 樣式: str) -> str:
        if not 樣式:
            訊息 = "grep 要給 pattern"
            raise 工具錯誤(訊息)
        if self.工作目錄 is None:
            訊息 = "這一輪沒有指定工作目錄，不能搜尋。"
            raise 工具錯誤(訊息)
        根 = self.工作目錄.resolve()
        命中: list[str] = []
        for 檔 in sorted(根.rglob("*")):
            if len(命中) >= 搜尋上限:
                break
            命中.extend(_檔裡的命中(檔, 根, 樣式, 還能收=搜尋上限 - len(命中)))
        if not 命中:
            return f"找不到「{樣式}」"
        尾 = f"\n[只列前 {搜尋上限} 筆]" if len(命中) >= 搜尋上限 else ""
        return self._截("\n".join(命中) + 尾)


def _檔裡的命中(檔: Path, 根: Path, 樣式: str, *, 還能收: int) -> list[str]:
    """一個檔案裡符合的行。讀不動的（二進位、權限）安靜跳過——

    grep 撞到一個 .png 就整個爆掉的話，模型會以為是自己的 pattern 有問題。
    """
    if not 檔.is_file():
        return []
    try:
        內容 = 檔.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    收: list[str] = []
    for 號, 行 in enumerate(內容.splitlines(), 1):
        if len(收) >= 還能收:
            break
        if 樣式 in 行:
            收.append(f"{檔.relative_to(根)}:{號}:{行.strip()[:160]}")
    return 收
