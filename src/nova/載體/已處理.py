"""已處理／：成果帳本的落點、寫端與讀取端。

**沒有讀取端就不准宣稱補了成果帳本**——只有寫端的話那是寫檔案給沒人看
（`docs/設計/04-載體要長什麼樣.md` 對 State 那一格的判準，這裡同理）。

落點跟事件帳本同一條規則：**歸屬是索引問題，不是存放位置問題**——
存在專案外面、用專案當鍵。存在專案裡面就等於交到執行者手上，
而成果是要拿來當證據的東西。理由的完整版在 `帳本.預設帳本目錄` 的表。
"""

import json
from dataclasses import dataclass
from pathlib import Path

from nova.契約.工作流 import 結束代碼
from nova.契約.成果 import 字典轉成果, 成果, 成果轉字典
from nova.載體.帳本 import 專案識別
from nova.載體.狀態 import 狀態根目錄

_預設上限 = 20
_連續非完成門檻 = 2
_完成收場值 = 結束代碼.完成.value


def 已處理目錄(專案: Path | None = None) -> Path:
    """成果帳本住哪。跟事件帳本是同一個專案目錄底下的兩個資料夾。

    走散了就對不回去——成果上的 `執行識別碼` 就是事件帳本那個
    `<執行識別碼>.jsonl` 的檔名。
    """
    底 = 狀態根目錄()
    return 底 / "已處理" if 專案 is None else 底 / "專案" / 專案識別(專案) / "已處理"


def 歸檔(一筆: 成果, *, 目錄: Path | None = None) -> Path:
    """把一筆成果寫下去。檔名就是執行識別碼，所以 `ls` 就是時序。

    **同號寫第二次當場炸，不准靜默覆寫**：`write_text` 是覆寫，
    而成果是拿來當證據的東西——被蓋掉的那一次就永遠說不出它做了什麼。

    炸在這裡是安全的：呼叫端 `_歸檔成果` 接住 `OSError` 只印 stderr，
    所以**工作結果不會被一筆記不下來的帳吃掉**。
    """
    在哪 = 目錄 or 已處理目錄()
    在哪.mkdir(parents=True, exist_ok=True)
    落點 = 在哪 / f"{一筆.執行識別碼}.json"
    with 落點.open("x", encoding="utf-8") as 檔:
        檔.write(json.dumps(成果轉字典(一筆), ensure_ascii=False, indent=2) + "\n")
    return 落點


def 列出成果(目錄: Path | None = None, *, 上限: int | None = _預設上限) -> list[成果]:
    """最近的排前面。目錄不存在就是空的——第一次跑的時候本來就還沒有。

    **讀不動的那筆跳過，不准把整本帳帶走。** 一筆壞掉就整本看不了
    等於沒有帳本。
    """
    在哪 = 目錄 or 已處理目錄()
    if not 在哪.is_dir():
        return []
    收集: list[成果] = []
    for 檔 in sorted(在哪.glob("*.json"), reverse=True):
        一筆 = _讀一筆(檔)
        if 一筆 is not None:
            收集.append(一筆)
        if 上限 is not None and len(收集) >= 上限:
            break
    return 收集


@dataclass(frozen=True, slots=True)
class 重複失敗紀錄:
    """單一題目在成果帳上的非完成統計與重複模式。"""

    連續非完成次數: int = 0
    總次數: int = 0
    總token: int = 0
    總成本美金: float | None = None
    重複失敗: bool = False
    最近收場: str | None = None
    最近退出碼: int | None = None

    @property
    def 非完成次數(self) -> int:
        """相容既有呼叫端；這裡是最新連續非完成次數，不是歷史累計。"""
        return self.連續非完成次數

    @property
    def 失敗次數(self) -> int:
        """相容既有呼叫端；護欄也算非完成，不代表故障。"""
        return self.連續非完成次數


def 查重複失敗(任務: str, *, 目錄: Path | None = None) -> 重複失敗紀錄:
    """查詢特定題目在成果帳上的執行歷史、累計消耗與重複失敗狀態。

    題目辨識採用去頭尾空白的機械字串比對：
    - 理由：佇列複本或重複派工的任務文字是逐字相同的，機械比對確定且無外部模型依賴。
    - 侷限：若題目文字被微調或註解變更，機械比對無法識別為同一題目（避免誤判不同任務）。

    判定標準：
    - `guardrail` 不是故障，但它是一次非完成；單次非完成不算重複失敗。
    - 只看最新一段連續非完成，達 2 次才判定為 `重複失敗`。
    """
    成果們 = 列出成果(目錄, 上限=None)
    同題成果 = _找出同題成果(成果們, 任務)
    if not 同題成果:
        return 重複失敗紀錄()

    return _彙整重複失敗紀錄(同題成果)


def _找出同題成果(成果們: list[成果], 任務: str) -> list[成果]:
    return [一筆 for 一筆 in 成果們 if _是同一題目(一筆, 任務)]


def _彙整重複失敗紀錄(成果們: list[成果]) -> 重複失敗紀錄:
    最新成果 = 成果們[0]
    連續非完成次數 = _計算連續非完成次數(成果們)

    return 重複失敗紀錄(
        連續非完成次數=連續非完成次數,
        總次數=len(成果們),
        總token=sum(筆.總token for 筆 in 成果們),
        總成本美金=_計算總成本(成果們),
        重複失敗=連續非完成次數 >= _連續非完成門檻,
        最近收場=最新成果.收場,
        最近退出碼=最新成果.退出碼,
    )


def _計算連續非完成次數(成果們: list[成果]) -> int:
    次數 = 0
    for 一筆 in 成果們:
        if not _是非完成(一筆):
            break
        次數 += 1
    return 次數


def _計算總成本(成果們: list[成果]) -> float | None:
    if any(一筆.總成本美金 is None for 一筆 in 成果們):
        return None
    return sum(一筆.總成本美金 for 一筆 in 成果們 if 一筆.總成本美金 is not None)


def _是同一題目(一筆: 成果, 目標題目: str) -> bool:
    return 一筆.任務.strip() == 目標題目.strip()


def _是非完成(一筆: 成果) -> bool:
    return 一筆.收場 != _完成收場值


def _讀一筆(檔: Path) -> 成果 | None:
    try:
        原始 = json.loads(檔.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(原始, dict):
        return None
    return 字典轉成果(原始)
