"""`驗證紅` 要驗的是「這一輪新寫的那幾支測試紅了」，不是整套 suite 非零退出。

## 這支釘的是哪個洞

`迴圈/狀態機.py` 的 `驗證紅` 只問一件事：判準是不是非零退出。而預設判準是**全套**
pytest。所以 repo 本來就有一支紅（flaky／遺留）的時候，`驗證紅` 永遠是紅的
——**新測試從來沒有被證明會紅**：模型寫了一支綠的測試也照樣過關，
而「親眼看到它紅」是最高原則第一條（使用者不看 code，測試是他唯一能信任的代理人）。

順帶的第二個後果：`驗證紅` 退回測試員時，帶回去的是整套 suite 的輸出，
對「哪支測試該紅而沒紅」零指向。所以這裡也釘證據要指名那幾個檔。

## 這支怎麼接線

`測試` 那一階動過哪幾個 `tests/` 檔，由護欄的快照比對（`載體/重構護欄.py` 的
`動到測試了嗎`）算出來，經 `步驟結果.動過的測試檔` 走到 `驗證紅`。
判準本身是真的 pytest 子程序：只驗那幾個檔的話退出碼才會跟全套不一樣，
用假判準的話證不到「檔名真的被接到指令上」。
"""

import dataclasses
import sys
from collections.abc import Mapping
from pathlib import Path

from nova.契約.工作流 import (
    任務,
    判準,
    步驟結果,
    結束,
    階段代碼,
    預設停止,
)
from nova.契約.模型回應 import 回應, 失敗代碼, 用量, 終局
from nova.契約.退出碼 import 未知
from nova.載體.判準 import 可作指定pytest目標, 建判準
from nova.載體.命令列 import _工作流退出碼
from nova.載體.工作區 import 拍工作區快照
from nova.載體.重構護欄 import 動到測試了嗎
from nova.迴圈.工作流 import 建TDD執行器, 工作流結果, 跑工作流

#: 基線就有的那支紅。**它不是這一輪的題目**——遺留或 flaky，全套 suite 因它永遠非零。
既有紅測試 = "tests/test_遺留的紅.py"
既有紅內容 = "def test_遺留() -> None:\n    assert 1 + 1 == 3\n"

#: 測試員這一輪寫的那支。內容由每支測試決定：綠的（作弊／沒測到東西）或真的紅。
新測試 = "tests/test_這輪新寫的.py"
綠的新測試 = "def test_新寫的() -> None:\n    assert True\n"
紅的新測試 = (
    "def 相加(甲, 乙):\n    return 0\n\n\ndef test_新寫的() -> None:\n    assert 相加(1, 2) == 3\n"
)

_真pytest = (sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider")


class _假測試員:
    """走到測試那一階就把 `新測試` 寫進工作區。寫什麼由呼叫端決定。"""

    def __init__(self, 內容: str) -> None:
        self.內容 = 內容

    @property
    def 名稱(self) -> str:
        return "假測試員"

    def 做(self, 提示: str, *, 工作目錄: Path | None = None) -> 回應:
        del 提示
        assert 工作目錄 is not None, "測試員要有工作目錄才寫得出測試"
        (工作目錄 / 新測試).write_text(self.內容, encoding="utf-8")
        return _回應("寫好了")


class _假角色:
    """其餘階段：什麼都不做，一律成功。"""

    def __init__(self, 文字: str = "做好了") -> None:
        self.文字 = 文字

    @property
    def 名稱(self) -> str:
        return "假角色"

    def 做(self, 提示: str, *, 工作目錄: Path | None = None) -> 回應:
        del 提示, 工作目錄
        return _回應(self.文字)


def _回應(文字: str) -> 回應:
    return 回應(
        文字=文字,
        終局=終局.成功,
        失敗代碼=失敗代碼.無,
        原始結束碼=0,
        對話識別碼=None,
        用量=用量(輸入token=1, 輸出token=1),
    )


def _工作區(tmp_path: Path) -> Path:
    """一個基線就有一支紅的工作區。全套 suite 在這裡永遠非零退出。"""
    (tmp_path / "tests").mkdir()
    (tmp_path / 既有紅測試).write_text(既有紅內容, encoding="utf-8")
    return tmp_path


def _只驗這幾支(檔們: tuple[str, ...]) -> 判準:
    """把要驗的那幾個檔接到判準指令後面——產線的組法就是這個形狀。"""
    return 建判準((*_真pytest, *檔們))


def _跑(工作區: Path, 新測試內容: str) -> 工作流結果:
    執行 = 建TDD執行器(
        角色表={
            階段代碼.測試: _假測試員(新測試內容),
            階段代碼.實作: _假角色(),
            階段代碼.重構: _假角色(),
            階段代碼.審查: _假角色("看過了\nREVIEW: PASS"),
        },
        跑判準=建判準(_真pytest),
        建指定測試判準=_只驗這幾支,
        篩選指定測試=可作指定pytest目標,
    )
    return 跑工作流(
        任務(描述="讓 X 變成 Y", 工作目錄=工作區),
        執行一步=執行,
        # 四步就夠看清楚走去哪了：測試 → 驗證紅 → （退回）測試 → 驗證紅。
        # 不設上限的話這支測試要為了同一個答案多跑好幾次真 pytest。
        停止=dataclasses.replace(預設停止, 最多步數=4),
        拍快照=拍工作區快照,
        動到測試了嗎=動到測試了嗎,
    )


class _多檔假測試員:
    """走到測試那一階就把多個檔案寫進工作區。"""

    def __init__(self, 檔案們: Mapping[str, str]) -> None:
        self.檔案們 = 檔案們

    @property
    def 名稱(self) -> str:
        return "多檔假測試員"

    def 做(self, 提示: str, *, 工作目錄: Path | None = None) -> 回應:
        del 提示
        assert 工作目錄 is not None, "測試員要有工作目錄才寫得出測試"
        for 相對路徑, 內容 in self.檔案們.items():
            目標 = 工作目錄 / 相對路徑
            目標.parent.mkdir(parents=True, exist_ok=True)
            目標.write_text(內容, encoding="utf-8")
        return _回應("寫好了")


def _跑多檔(工作區: Path, 檔案們: Mapping[str, str]) -> 工作流結果:
    執行 = 建TDD執行器(
        角色表={
            階段代碼.測試: _多檔假測試員(檔案們),
            階段代碼.實作: _假角色(),
            階段代碼.重構: _假角色(),
            階段代碼.審查: _假角色("看過了\nREVIEW: PASS"),
        },
        跑判準=建判準(_真pytest),
        建指定測試判準=_只驗這幾支,
        篩選指定測試=可作指定pytest目標,
    )
    return 跑工作流(
        任務(描述="讓 X 變成 Y", 工作目錄=工作區),
        執行一步=執行,
        停止=dataclasses.replace(預設停止, 最多步數=4),
        拍快照=拍工作區快照,
        動到測試了嗎=動到測試了嗎,
    )


def _驗證紅那一步(果: 工作流結果) -> 步驟結果:
    紅們 = [步 for 步 in 果.軌跡 if 步.階段 is 階段代碼.驗證紅]
    assert 紅們, f"連驗證紅都沒走到：{[步.階段 for 步 in 果.軌跡]}"
    return 紅們[0]


class Test測試員寫了綠測試不准過:
    def test_基線本來就有一支紅不算這輪的測試紅了(self, tmp_path: Path) -> None:
        """全套 suite 非零退出當「紅」＝拿別人的紅替這一輪的測試背書。"""
        果 = _跑(_工作區(tmp_path), 綠的新測試)

        assert _驗證紅那一步(果).判準綠 is True, "這一輪新寫的測試是綠的，驗證紅不該放行"

    def test_沒紅就不准往下走到實作(self, tmp_path: Path) -> None:
        """放行的話，實作員會拿到一支「已經綠了」的測試——它保證不了任何行為。"""
        果 = _跑(_工作區(tmp_path), 綠的新測試)

        走過的 = [步.階段 for 步 in 果.軌跡]
        assert 階段代碼.實作 not in 走過的, f"綠測試不該讓它往下走：{走過的}"
        assert 走過的[:3] == [階段代碼.測試, 階段代碼.驗證紅, 階段代碼.測試], 走過的

    def test_退回去的證據要指名驗的是哪幾支(self, tmp_path: Path) -> None:
        """整套 suite 的輸出對「哪支測試該紅而沒紅」零指向，退回去等於叫人重猜。"""
        果 = _跑(_工作區(tmp_path), 綠的新測試)

        assert 新測試 in _驗證紅那一步(果).證據, _驗證紅那一步(果).證據


class Test這輪的測試真的紅了才准往下:
    def test_新測試紅了就走到實作(self, tmp_path: Path) -> None:
        """負控：別把護欄做成「驗證紅永遠不過」——那樣七階第一步就死在原地。"""
        果 = _跑(_工作區(tmp_path), 紅的新測試)

        走過的 = [步.階段 for 步 in 果.軌跡]
        assert _驗證紅那一步(果).判準綠 is False, "新測試真的紅了，驗證紅要放行"
        assert 階段代碼.實作 in 走過的, f"該往下走卻沒走：{走過的}"

    def test_只驗那幾支所以基線的紅不會被算進來(self, tmp_path: Path) -> None:
        """證據裡只該有這一輪那個檔——基線那支紅根本不在被驗的清單上。"""
        果 = _跑(_工作區(tmp_path), 紅的新測試)

        證據 = _驗證紅那一步(果).證據
        assert 既有紅測試 not in 證據, f"基線的紅被混進這一輪的判準了：{證據}"


def test_收場不是靜默地什麼都沒發生(tmp_path: Path) -> None:
    """步數上限收在護欄——這支測試靠 `結束` 說得出話，不是靠 trace 猜。"""
    果 = _跑(_工作區(tmp_path), 綠的新測試)

    assert isinstance(果.結束, 結束)
    assert 果.結束.原因, "收場要說得出原因"


class Test負控登記等非測試檔不當指定測試判準:
    """**負控登記檔不是測試檔。**

    `tests/負控/登記們/*.py` 裡面只有登記資料（tuple），沒有 test_* 函式。
    `驗證紅` 拿它當指定測試判準會導致 pytest exit 5（no tests collected）跑不起來。
    判準要排除負控登記、conftest 等非測試檔；濾完若為空則誠實退回全套判準。
    """

    def test_測試階段只動了負控登記檔時退回全套判準(self, tmp_path: Path) -> None:
        """測試員只寫了負控登記檔，驗證紅應排除它並退回全套判準（基線有紅則放行走到實作）。"""
        負控登記檔 = "tests/負控/登記們/全面重構_r01.py"
        負控內容 = "登記 = ()\n"
        果 = _跑多檔(_工作區(tmp_path), {負控登記檔: 負控內容})

        走過的 = [步.階段 for 步 in 果.軌跡]
        assert 階段代碼.實作 in 走過的, f"只動負控登記檔退回全套應放行走到實作：{走過的}"
        assert 負控登記檔 not in _驗證紅那一步(果).證據, _驗證紅那一步(果).證據

    def test_同時動了紅測試與負控登記檔時只驗紅測試(self, tmp_path: Path) -> None:
        """同時動了測試與登記檔，驗證紅只指定測試檔，排除負控登記檔。"""
        負控登記檔 = "tests/負控/登記們/全面重構_r01.py"
        果 = _跑多檔(
            _工作區(tmp_path),
            {新測試: 紅的新測試, 負控登記檔: "登記 = ()\n"},
        )

        走過的 = [步.階段 for 步 in 果.軌跡]
        assert 階段代碼.實作 in 走過的, f"新測試紅了應往下走到實作：{走過的}"
        證據 = _驗證紅那一步(果).證據
        assert 新測試 in 證據, 證據
        assert 負控登記檔 not in 證據, f"負控登記檔不該出現在指定測試清單中：{證據}"


class Test判準跑不起來收場為結果未知:
    def test_判準沒收集到測試時收場為結果未知不是確定失敗(self, tmp_path: Path) -> None:
        """pytest exit 5（沒收集到測試）屬於跑不起來。

        依四值語意是結果未知（3），不是確定失敗（1）。
        """
        (tmp_path / "tests").mkdir()
        # 測試員寫了一個完全沒有測試函式的檔案
        果 = _跑多檔(tmp_path, {"tests/空的.py": "# 沒有任何測試函式\n"})

        assert any(步.終局 is 終局.結果未知 for 步 in 果.軌跡), f"步驟終局應有結果未知：{果.軌跡}"
        assert _工作流退出碼(果.結束, 果.軌跡) == 未知
