"""`nova 線` 的觀測契約與型別定義。"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nova.契約.成果 import 成果

#: 比對用的基底一律是本地這條 ref；查詢不連網，所以它可能是舊的。
_基底參照 = "origin/main"
_基底說明_有 = f"以本地 {_基底參照} 為準（查詢不連網，這份 ref 可能不是最新的）"
_基底說明_無 = f"查不到本地 {_基底參照} 這個 ref，領先／落後留空（不是已同步）"


@dataclass(frozen=True, slots=True)
class 線現況:
    """一條工作線（worktree 或主工作區）的唯讀快照。

    這是一條線唯一的資料入口：程序、階段、成果、基底、mtime 都在這一份裡，
    呼叫端不必再兜第二次查詢。

    算不出來的欄位一律留空（`None`），不准拿 0 頂替——
    「查不到基底」跟「差 0 個 commit」是兩件事。
    """

    名字: str
    在跑嗎: bool | None
    跑多久: str | None
    啟動時間: str | None
    目前階段: str | None
    上一次: 成果 | None
    護欄原因: str | None
    #: 未提交的檔案數。乾不乾淨從這一份衍生，不另外存一份會分歧的布林值。
    未提交檔案數: int | None
    #: 落後基底幾個 commit。這是落後數唯一的存放處，`落後基底數` 由它衍生。
    #: 詞序跟 `領先基底數` 不一致是既有呼叫端綁著的：排版那邊用 `基底落後數` 建構，
    #: 並行查詢那邊跟 `領先基底數` 對稱地讀，兩邊都不在這一格的寫入範圍內。
    基底落後數: int | None
    #: 這條線的工作區路徑；查不到就留空，不拿目前目錄頂替。
    路徑: Path | None = None
    是主工作區: bool = False
    目前commit: str | None = None
    基底參照: str | None = None
    基底說明: str = _基底說明_無
    領先基底數: int | None = None
    最後改動時間: datetime | None = None

    @property
    def 落後基底數(self) -> int | None:
        """`基底落後數` 的唯讀別名，讓呼叫端能跟 `領先基底數` 對稱地讀。"""
        return self.基底落後數

    @property
    def 工作區乾淨嗎(self) -> bool | None:
        """有沒有未提交的改動；數不出來（`未提交檔案數` 留空）時一併留空。"""
        return None if self.未提交檔案數 is None else self.未提交檔案數 == 0


@dataclass(frozen=True, slots=True)
class 程序資料:
    """從 `ps` 確認到的一個 nova 程序。"""

    工作目錄: Path
    跑多久: str
    啟動時間: str


@dataclass(frozen=True, slots=True)
class 程序清查:
    """從 `ps` 清查到的 nova 程序與是否有無法定位工作目錄的程序。"""

    程序們: list[程序資料]
    有無法定位工作目錄的程序: bool


@dataclass(frozen=True, slots=True)
class 基底比較:
    """一條線跟本地基底 ref 比出來的結果。查不到基底時領先／落後一律留空。"""

    參照: str | None
    說明: str
    領先: int | None
    落後: int | None


#: 比不出來時一律回這一份：領先／落後留空，說明講明是查不到，不是差 0 個。
查不到基底 = 基底比較(參照=None, 說明=_基底說明_無, 領先=None, 落後=None)
