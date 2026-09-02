"""哪一顆型號屬於哪一家，以及送出前的歸屬檢查。

**為什麼型號字串住在這裡而不是各家的轉接函式旁邊**：要回答「這顆屬不屬於你」
就得看得見別家的型號。散在三個地方的話，`--模型 sonnet` 配上 codex 只能等
對方的 CLI 去報錯——那時候已經燒掉一輪 token，而錯誤訊息是對方的格式，
解析不出來就變成 `unknown`。

規則是「**不認得就擋，除非那一家宣告自己接受任意型號**」，不是列白名單：
claude 的型號是開放集合（`sonnet`／`opus`／完整 id 都吃），
本機端點的型號 id 是使用者機器上那顆模型的檔名——這兩家列不完。
"""

#: codex 只用這兩個型號（使用者裁定）。luna 是常用的，sol 是高階推理。
codex常用模型 = "gpt-5.6-luna"
codex高階模型 = "gpt-5.6-sol"

#: agy 的推理強度包在型號裡（`agy models` 實測），不是另一個旗標。
agy預設模型 = "gemini-3.7-flash-high"

#: agy 代跑好幾族，但**認的是 `agy models` 列得出的那幾顆**，不是「看起來像」：
#: 比前綴的話 `gpt-5.6-sol`（codex 的）與 `claude-sonnet-9-9`（沒人上架過）
#: 都會被放行，然後燒一輪 token 換回 agy 格式的錯誤。agy 上架新型號就補這裡。
#: `gemini-3.7-flash` 是同一顆的免後綴寫法；那一族還有額度限制，
#: 由 `轉接._agy型號` 另外把關。
agy認得的型號 = frozenset(
    {
        agy預設模型,
        "gemini-3.7-flash",
        "claude-sonnet-4-6",
        "claude-opus-4-6-thinking",
        "gpt-oss-120b-medium",
    }
)

#: claude 的招牌簡稱。claude 自己接受任意型號，這兩顆列出來是為了讓**別家**
#: 認得「這是 claude 的」——`--用 claude --模型 sonnet` 漏到審查那階就是這樣擋下的。
claude的簡稱 = frozenset({"sonnet", "opus"})

#: 別家指名的型號。本機端點不列白名單（`本地._第一個型號` 那條註解說了為什麼：
#: 型號是使用者自己下載的那顆），但這幾顆一定不是本機跑得動的東西。
_別家指名的型號 = claude的簡稱 | {codex常用模型, codex高階模型}
_別家指名的族 = ("gemini-", "claude-")


def _認得(家: str, 型號: str) -> bool:
    """這一家吃不吃這顆型號。表裡沒有的家當成接受任意型號——家名本身由建腦那層擋。"""
    if 家 == "codex":
        return 型號 in {codex常用模型, codex高階模型}
    if 家 == "agy":
        return 型號 in agy認得的型號
    if 家 == "local":
        return 型號 not in _別家指名的型號 and not 型號.startswith(_別家指名的族)
    return True


def 檢查型號(家: str, 型號: str | None) -> None:
    """型號不屬於這一家就當場炸，不要送出子程序或 HTTP。沒指定型號（`None`）不管。"""
    if 型號 is None or _認得(家, 型號):
        return
    訊息 = f"{型號} 不屬於 {家}：型號的命名空間不交集，送出去只會換到對方格式的錯誤"
    raise ValueError(訊息)
