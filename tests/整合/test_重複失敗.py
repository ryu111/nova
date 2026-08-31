"""同一類失敗第二次出現要被指出來——不要等人自己撞到。

`docs/設計/09-接下來往哪走.md` 第 2 階的判準：「同一類失敗第二次出現 →
自動落票／落一支探針」。`載體/閘紅成票.py` 做掉了閘紅那半，**模型失敗那半沒有**：
一顆腦連續在同一階摔、工具回合用完、輸出解析不出來，現在只留在帳本裡沒人回頭看。

這個檔背書的是 `載體/重複失敗.py` 的**唯讀查詢**那一格：讀跨專案帳本，
挑出同一類出現兩次以上的失敗。**落票是下一格的事**，所以這裡也背書「只讀不寫」。

碰檔案（真的寫帳本檔進 tmp_path），所以住整合層。
"""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from nova.載體.重複失敗 import 找出重複失敗, 重複門檻


@dataclass(frozen=True, slots=True)
class 一種摔法:
    """測資這邊對「同一類」的定義：階段＋失敗代碼＋供應商，**沒有執行與時間**。"""

    階段: str = "impl"
    失敗代碼: str = "timeout"
    供應商: str = "codex"


#: 沒特別指定就用這一種摔法：codex 在 impl 逾時。
預設摔法 = 一種摔法()


def 專案帳本目錄(狀態根: Path, 專案識別: str) -> Path:
    """`預設帳本目錄(專案)` 的落點形狀，測試這邊自己拼一次。"""
    return 狀態根 / "專案" / 專案識別 / "帳本"


def 寫一次執行(
    帳本目錄: Path,
    執行識別碼: str,
    *,
    摔法: 一種摔法 = 預設摔法,
    接力幾顆: int = 1,
    時戳: str = "2026-08-31T09:00:00Z",
) -> Path:
    """寫一本真的帳：一個階段裡叫了 `接力幾顆` 顆腦，每一顆都以同一種方式摔。

    形狀照 `載體/階段記帳.py` 與 `載體/模型/記帳.py` 實際落盤的樣子：
    階段事件帶 `stage`，呼叫事件帶 `family`／`attempt`／`failure_code`，
    **呼叫事件自己不帶 `stage`**——階段要靠外層那對事件圈出來。
    """
    帳本目錄.mkdir(parents=True, exist_ok=True)
    共通 = {"run": 執行識別碼, "ts": 時戳}
    事件們: list[dict[str, object]] = [
        {**共通, "seq": 1, "event": "stage_started", "call": 1, "stage": 摔法.階段}
    ]
    for 第幾顆 in range(1, 接力幾顆 + 1):
        編號 = 1 + 第幾顆
        事件們.append(
            {
                **共通,
                "seq": len(事件們) + 1,
                "event": "call_started",
                "call": 編號,
                "family": 摔法.供應商,
                "attempt": 第幾顆,
            }
        )
        事件們.append(
            {
                **共通,
                "seq": len(事件們) + 1,
                "event": "call_finished",
                "call": 編號,
                "family": 摔法.供應商,
                "attempt": 第幾顆,
                "outcome": "failed",
                "failure_code": 摔法.失敗代碼,
            }
        )
    事件們.append(
        {
            **共通,
            "seq": len(事件們) + 1,
            "event": "stage_finished",
            "call": 1,
            "stage": 摔法.階段,
            "outcome": "failed",
        }
    )
    檔 = 帳本目錄 / f"{執行識別碼}.jsonl"
    檔.write_text(
        "".join(json.dumps(事, ensure_ascii=False) + "\n" for 事 in 事件們), encoding="utf-8"
    )
    return 檔


def 鍵們(狀態根: Path) -> list[tuple[str, str, str]]:
    """把結果收斂成可比對的鍵，**不綁排序**——排序不是這個檔要定的行為。"""
    return sorted((筆.階段, 筆.失敗代碼, 筆.供應商) for 筆 in 找出重複失敗(狀態根))


def test_門檻是二() -> None:
    """**第一次是雜訊，第二次才是模式。**

    門檻寫成常數是為了說得出理由：1 等於每個失敗都落票（失敗是 TDD 的正常狀態，
    收件匣當天就淹掉），3 以上等於同一顆腦要摔滿三次才有人知道。
    """
    assert 重複門檻 == 2


def test_只出現一次的不算(tmp_path: Path) -> None:
    """一次失敗不成模式——這一格就是防「收件匣被 TDD 的正常紅淹掉」。"""
    寫一次執行(專案帳本目錄(tmp_path, "nova-wt-路線-13ac9f02"), "20260831T090000Z-甲")

    assert list(找出重複失敗(tmp_path)) == []


def test_不同執行不同時間的同類失敗算成同一類(tmp_path: Path) -> None:
    """**鍵不含執行識別碼與時間戳。**

    含了的話每一筆都是獨一無二的，「第二次」永遠不會發生，整個查詢等於死程式碼。
    所以兩次不同執行、不同時戳、甚至不同專案的同類失敗，要收斂成一筆、次數是 2。
    """
    額度用光 = 一種摔法(階段="verify-red", 失敗代碼="quota-exhausted", 供應商="claude")
    寫一次執行(
        專案帳本目錄(tmp_path, "nova-wt-路線-13ac9f02"),
        "20260831T090000Z-甲",
        摔法=額度用光,
        時戳="2026-08-31T09:00:00Z",
    )
    寫一次執行(
        專案帳本目錄(tmp_path, "nova-wt-四欄-52dabea7"),
        "20260831T113000Z-乙",
        摔法=額度用光,
        時戳="2026-08-31T11:30:00Z",
    )

    (筆,) = 找出重複失敗(tmp_path)
    assert (筆.階段, 筆.失敗代碼, 筆.供應商) == ("verify-red", "quota-exhausted", "claude")
    assert 筆.次數 == 2
    assert sorted(筆.執行們) == ["20260831T090000Z-甲", "20260831T113000Z-乙"]


@pytest.mark.parametrize(
    "第二次",
    [一種摔法(階段="review"), 一種摔法(失敗代碼="upstream"), 一種摔法(供應商="agy")],
    ids=["階段", "失敗代碼", "供應商"],
)
def test_鍵的三格任一不同就不是同一類(tmp_path: Path, 第二次: 一種摔法) -> None:
    """階段、失敗代碼、供應商三格都是鍵的一部分。

    少任何一格，「codex 在 impl 逾時」與「agy 在 review 被上游擋」會被算成同一類，
    落出來的票指不到任何一個能修的東西。
    """
    目錄 = 專案帳本目錄(tmp_path, "nova-wt-路線-13ac9f02")
    寫一次執行(目錄, "20260831T090000Z-甲")
    寫一次執行(目錄, "20260831T091000Z-乙", 摔法=第二次)

    assert list(找出重複失敗(tmp_path)) == []


def test_同一次執行裡接力三顆只算一次(tmp_path: Path) -> None:
    """**接力鏈是同一件事的重試，不是三次獨立的失敗。**

    算成三次的話第一次執行就直接過門檻，門檻等於沒有——而接力本來就是
    「第一顆摔了換第二顆」，三顆一起摔是常見的單一事件（例如額度當天用光）。
    """
    寫一次執行(
        專案帳本目錄(tmp_path, "nova-wt-路線-13ac9f02"),
        "20260831T090000Z-甲",
        接力幾顆=3,
    )

    assert list(找出重複失敗(tmp_path)) == []


def test_一次執行最多貢獻一次(tmp_path: Path) -> None:
    """三顆接力的那次算 1、單顆的那次算 1，合起來是 2 不是 4。

    次數要能拿來排序「哪一類最該先處理」，被接力鏈灌水就排錯。
    """
    寫一次執行(專案帳本目錄(tmp_path, "nova-wt-路線-13ac9f02"), "20260831T090000Z-甲", 接力幾顆=3)
    寫一次執行(專案帳本目錄(tmp_path, "nova-wt-路線-13ac9f02"), "20260831T091000Z-乙", 接力幾顆=1)

    (筆,) = 找出重複失敗(tmp_path)
    assert 筆.次數 == 2
    assert sorted(筆.執行們) == ["20260831T090000Z-甲", "20260831T091000Z-乙"]


def test_兩類各自重複就各自出現(tmp_path: Path) -> None:
    """不同類不准被併成一筆——併了就答不出「該先修哪一個」。"""
    目錄 = 專案帳本目錄(tmp_path, "nova-wt-路線-13ac9f02")
    for 識別 in ("20260831T090000Z-甲", "20260831T091000Z-乙"):
        寫一次執行(目錄, 識別, 摔法=一種摔法(階段="impl", 失敗代碼="timeout", 供應商="codex"))
    for 識別 in ("20260831T092000Z-丙", "20260831T093000Z-丁"):
        寫一次執行(目錄, 識別, 摔法=一種摔法(階段="review", 失敗代碼="upstream", 供應商="agy"))

    assert 鍵們(tmp_path) == [
        ("impl", "timeout", "codex"),
        ("review", "upstream", "agy"),
    ]


def test_成功的呼叫不算失敗(tmp_path: Path) -> None:
    """只有 `outcome=failed` 算。把成功也算進去，這份清單就跟「跑過幾次」同義。"""
    目錄 = 專案帳本目錄(tmp_path, "nova-wt-路線-13ac9f02")
    目錄.mkdir(parents=True, exist_ok=True)
    for 識別 in ("20260831T090000Z-甲", "20260831T091000Z-乙"):
        (目錄 / f"{識別}.jsonl").write_text(
            json.dumps(
                {
                    "run": 識別,
                    "seq": 1,
                    "ts": "2026-08-31T09:00:00Z",
                    "event": "call_finished",
                    "call": 1,
                    "family": "codex",
                    "outcome": "success",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    assert list(找出重複失敗(tmp_path)) == []


def test_一本帳都沒有也不准炸(tmp_path: Path) -> None:
    """**「還沒有帳」不是錯誤。**

    全新的機器上 `$XDG_STATE_HOME/nova/` 根本不存在，炸掉會讓狀態列一直閃紅。
    """
    assert list(找出重複失敗(tmp_path / "根本沒這個目錄")) == []
    assert list(找出重複失敗(tmp_path)) == []


def test_只讀不寫(tmp_path: Path) -> None:
    """這一格**不落票、不碰收件匣**。

    落票是下一格，而且那條路要先想清楚「同一類失敗的票怎麼去重」
    （`閘紅成票.py` 用機器鍵去重）。在想清楚之前先寫檔，等於在收件匣裡
    製造一堆沒有去重策略的重複票。
    """
    目錄 = 專案帳本目錄(tmp_path, "nova-wt-路線-13ac9f02")
    for 識別 in ("20260831T090000Z-甲", "20260831T091000Z-乙"):
        寫一次執行(目錄, 識別)
    之前檔 = {路: 路.read_bytes() for 路 in tmp_path.rglob("*") if 路.is_file()}
    之前目錄 = {路 for 路 in tmp_path.rglob("*") if 路.is_dir()}

    assert len(list(找出重複失敗(tmp_path))) == 1

    assert {路: 路.read_bytes() for 路 in tmp_path.rglob("*") if 路.is_file()} == 之前檔
    assert {路 for 路 in tmp_path.rglob("*") if 路.is_dir()} == 之前目錄
