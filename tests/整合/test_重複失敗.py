"""同一類失敗第二次出現要被指出來——不要等人自己撞到。

`docs/設計/09-接下來往哪走.md` 第 2 階的判準：「同一類失敗第二次出現 →
自動落票／落一支探針」。`載體/閘紅成票.py` 做掉了閘紅那半，**模型失敗那半沒有**：
一顆腦連續在同一階摔、工具回合用完、輸出解析不出來，現在只留在帳本裡沒人回頭看。

這個檔背書：
1. `載體/重複失敗.py` 的**唯讀查詢**那一格：讀跨專案帳本，挑出同一類出現兩次以上的失敗。
2. `載體/已處理.py` 的 `查重複失敗`：從成果帳本查詢同一張票是否一直失敗、燒了多少。

碰檔案（真的寫帳本檔進 tmp_path），所以住整合層。
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from nova.契約.工作流 import 結束代碼
from nova.契約.成果 import 成果
from nova.契約.遮罩 import 已經遮過了
from nova.載體.已處理 import 查重複失敗, 歸檔
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


def _造成果(
    識別碼: str,
    任務內容: str,
    *,
    收場: str = 結束代碼.護欄.value,
    退出碼: int = 4,
    **額外: Any,
) -> 成果:
    token = int(額外.get("token", 6_350_000))
    成本 = float(額外["成本"]) if 額外.get("成本") is not None else 0.5
    步數 = int(額外.get("步數", 20))
    起 = str(額外.get("起", "2026-08-31T13:00:00Z"))
    迄 = str(額外.get("迄", "2026-08-31T13:15:00Z"))
    return 成果(
        執行識別碼=識別碼,
        任務=已經遮過了(任務內容, 因為="測試資料，裡面沒有祕密"),
        收場=收場,
        退出碼=退出碼,
        起=起,
        迄=迄,
        走了幾階=步數,
        總token=token,
        總成本美金=成本,
    )


class Test查重複失敗:
    """測試從成果帳本查詢同題目的重複失敗歷史與花費。"""

    def test_真實八次護欄紀錄查得出重複失敗與累積花費(self, tmp_path: Path) -> None:
        """真實案例：同一題目因佇列複本被執行 8 次護欄，累積 56.11M token。

        不准造簡化案例——真實資料中兩份拷貝的 task 內容是逐字相同的，
        查詢必須機械地認出同題目，並如實加總失敗次數與消耗。
        """
        題目 = (
            "重構實線閘補兩格\n\n"
            "## 輸入\n- src/nova/載體/已處理.py\n"
            "## 輸出\n- src/nova/載體/已處理.py\n"
            "## 驗收\n<!--nova:驗收 uv run pytest tests/整合/test_已處理.py -q-->\n"
            "## 停止\n步數上限 20"
        )

        八次數據 = [
            (
                "20260831T130405Z-001",
                6_350_000,
                0.51,
                20,
                "2026-08-31T13:04:05Z",
                "2026-08-31T13:18:00Z",
            ),
            (
                "20260831T131920Z-002",
                6_690_000,
                0.54,
                20,
                "2026-08-31T13:19:20Z",
                "2026-08-31T13:34:00Z",
            ),
            (
                "20260831T133510Z-003",
                7_710_000,
                0.62,
                20,
                "2026-08-31T13:35:10Z",
                "2026-08-31T13:52:00Z",
            ),
            (
                "20260831T143035Z-004",
                11_100_000,
                0.89,
                20,
                "2026-08-31T14:30:35Z",
                "2026-08-31T14:50:00Z",
            ),
            (
                "20260831T145210Z-005",
                13_580_000,
                1.09,
                16,
                "2026-08-31T14:52:10Z",
                "2026-08-31T15:08:00Z",
            ),
            (
                "20260831T151000Z-006",
                3_880_000,
                0.31,
                11,
                "2026-08-31T15:10:00Z",
                "2026-08-31T15:25:00Z",
            ),
            (
                "20260831T153000Z-007",
                4_000_000,
                0.32,
                20,
                "2026-08-31T15:30:00Z",
                "2026-08-31T15:48:00Z",
            ),
            (
                "20260831T155000Z-008",
                2_800_000,
                0.22,
                15,
                "2026-08-31T15:50:00Z",
                "2026-08-31T16:05:00Z",
            ),
        ]

        for 識別碼, tokens, 成本, 步數, 起, 迄 in 八次數據:
            歸檔(
                _造成果(
                    識別碼,
                    題目,
                    收場=結束代碼.護欄.value,
                    退出碼=4,
                    token=tokens,
                    成本=成本,
                    步數=步數,
                    起=起,
                    迄=迄,
                ),
                目錄=tmp_path,
            )

        紀錄 = 查重複失敗(題目, 目錄=tmp_path)

        assert 紀錄.失敗次數 == 8
        assert 紀錄.總次數 == 8
        assert 紀錄.總token == 56_110_000
        assert 紀錄.總成本美金 == pytest.approx(4.50)
        assert 紀錄.重複失敗 is True
        assert 紀錄.最近收場 == 結束代碼.護欄.value
        assert 紀錄.最近退出碼 == 4

    def test_單次護欄不算一直失敗(self, tmp_path: Path) -> None:
        """反向保證：護欄是正常的停止規則生效，單次發生不算重複失敗。

        若單次護欄就被報成重複失敗，會把每一次正常的護欄都報成問題，
        使監控失去意義。
        """
        題目 = "一般任務撞步數上限"
        歸檔(
            _造成果(
                "20260831T100000Z-single",
                題目,
                收場=結束代碼.護欄.value,
                退出碼=4,
                token=100_000,
                成本=0.01,
            ),
            目錄=tmp_path,
        )

        紀錄 = 查重複失敗(題目, 目錄=tmp_path)

        assert 紀錄.失敗次數 == 1
        assert 紀錄.總次數 == 1
        assert 紀錄.總token == 100_000
        assert 紀錄.重複失敗 is False
        assert 紀錄.最近收場 == 結束代碼.護欄.value
        assert 紀錄.最近退出碼 == 4

    def test_不同題目分得開不准互相干擾(self, tmp_path: Path) -> None:
        """題目 A 失敗多次，不准算到題目 B 頭上。"""
        題目A = "題目甲：改壞了"
        題目B = "題目乙：沒事"

        歸檔(
            _造成果("20260831T100000Z-a1", 題目A, 收場=結束代碼.護欄.value, 退出碼=4),
            目錄=tmp_path,
        )
        歸檔(
            _造成果("20260831T101000Z-a2", 題目A, 收場=結束代碼.護欄.value, 退出碼=4),
            目錄=tmp_path,
        )
        歸檔(
            _造成果("20260831T102000Z-a3", 題目A, 收場=結束代碼.護欄.value, 退出碼=4),
            目錄=tmp_path,
        )
        歸檔(
            _造成果("20260831T103000Z-b1", 題目B, 收場=結束代碼.完成.value, 退出碼=0, token=500),
            目錄=tmp_path,
        )

        紀錄A = 查重複失敗(題目A, 目錄=tmp_path)
        紀錄B = 查重複失敗(題目B, 目錄=tmp_path)

        assert 紀錄A.失敗次數 == 3
        assert 紀錄A.重複失敗 is True

        assert 紀錄B.失敗次數 == 0
        assert 紀錄B.總次數 == 1
        assert 紀錄B.重複失敗 is False

    def test_最新一次已成功完成時不算重複失敗(self, tmp_path: Path) -> None:
        """如果過去曾經失敗過，但最新一輪已經成功收尾，則不應判定為重複失敗。"""
        題目 = "先失敗後成功的任務"
        歸檔(
            _造成果(
                "20260831T090000Z-fail1",
                題目,
                收場=結束代碼.護欄.value,
                退出碼=4,
                起="2026-08-31T09:00:00Z",
            ),
            目錄=tmp_path,
        )
        歸檔(
            _造成果(
                "20260831T091500Z-fail2",
                題目,
                收場=結束代碼.護欄.value,
                退出碼=4,
                起="2026-08-31T09:15:00Z",
            ),
            目錄=tmp_path,
        )
        歸檔(
            _造成果(
                "20260831T093000Z-succ",
                題目,
                收場=結束代碼.完成.value,
                退出碼=0,
                起="2026-08-31T09:30:00Z",
            ),
            目錄=tmp_path,
        )

        紀錄 = 查重複失敗(題目, 目錄=tmp_path)

        assert 紀錄.總次數 == 3
        assert 紀錄.最近收場 == 結束代碼.完成.value
        assert 紀錄.最近退出碼 == 0
        assert 紀錄.重複失敗 is False

    def test_沒有歷史紀錄時回傳空統計不炸掉(self, tmp_path: Path) -> None:
        """第一次跑或目錄不存在時，回傳次數為 0 的正常紀錄。"""
        紀錄 = 查重複失敗("全新任務", 目錄=tmp_path / "不存在的目錄")

        assert 紀錄.失敗次數 == 0
        assert 紀錄.總次數 == 0
        assert 紀錄.總token == 0
        assert 紀錄.總成本美金 is None
        assert 紀錄.重複失敗 is False
