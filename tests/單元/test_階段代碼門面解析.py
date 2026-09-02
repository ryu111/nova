"""階段代碼門面解析的單元測試（CLI-04）。

目標：
把使用者要記的固定動詞收斂成正典 `階段代碼`，不是再做一個角色系統。
解析時直接使用 enum／既有階段表，避免中文名稱、工作種類或 research 的「對抗」另成第二套詞彙。

驗收點：
1. 公開動作全集恰來自 `階段代碼.value`（test, verify-red, impl, verify-green,
   refactor, verify-refactor, review）。
2. 階段代碼增減時，門面清單直接連動，不可能只更新 parser 走散。
3. 階段動作規格（action spec）只包含 stage code 與窄介面必要輸入
   （題目/提示檔、工作目錄、帳本選項），絕不把模型、思考深度、權限、預算常數塞進第二份表。
4. 七個 stage code 都能被 parser 正確解析，verify-* 是判準階段而非需要模型的角色；
   未知 stage 或缺少必要輸入在建腦/發模型前就失敗，且禁止猜測名稱或默認到 impl。
5. nova 問 仍保留低階 20+ 旗標；不新增 實作/測試/對抗 等中文別名；
   既有 重構 若存在只能是 refactor 薄別名。
6. 架構邊界：AST/路徑斷言不新增 src/nova/圖/、節點註冊表、編排 DSL，也不修改 語言模型 Protocol。
"""

import ast
import dataclasses
from pathlib import Path

import pytest

from nova.契約.工作流 import 種類, 階段代碼
from nova.載體.剖析器 import (
    公開階段動作全集,
    建剖析器,
    解析階段動作,
    階段動作規格,
)
from nova.迴圈.狀態機 import TDD階段表

專案根 = Path(__file__).resolve().parents[2]


class Test階段代碼正典門面全集:
    """公開動作名稱全集且只來自 `階段代碼.value`。"""

    def test_公開動作全集恰為階段代碼七個值(self) -> None:
        """公開動作全集必須直接對齊 `階段代碼`，不能多也不能少。"""
        預期全集 = frozenset(
            {
                "test",
                "verify-red",
                "impl",
                "verify-green",
                "refactor",
                "verify-refactor",
                "review",
            }
        )
        assert frozenset(代碼.value for 代碼 in 階段代碼) == 預期全集
        assert 公開階段動作全集 == 預期全集

    def test_門面動作清單直接源自階段代碼enum(self) -> None:
        """enum 新增/刪除 stage 時，門面動作全集會動態連動，不可獨立維護第二份字串清單。"""
        assert 公開階段動作全集 == frozenset(代碼.value for 代碼 in 階段代碼)

    def test_不接受中文別名也不接受對抗詞彙(self) -> None:
        """不新增 實作/測試/對抗 等中文別名，保持正典 ASCII 階段代碼。"""
        非法動作們 = ("測試", "實作", "重構", "審查", "對抗", "驗證紅", "驗證綠", "驗證重構")
        for 非法 in 非法動作們:
            assert 非法 not in 公開階段動作全集
            with pytest.raises((ValueError, SystemExit)):
                解析階段動作([非法, "一些題目"])


class Test階段動作規格契約:
    """只含 stage code / 必要輸入的 action spec，供 CLI-05 使用。"""

    def test_階段動作規格欄位只收必要輸入(self) -> None:
        """action spec 只能包含階段代碼與窄介面必要輸入，不得塞進模型或預算常數。"""
        欄位名們 = {欄位.name for 欄位 in dataclasses.fields(階段動作規格)}
        預期必要欄位 = {"階段", "題目", "提示檔", "工作目錄", "帳本目錄", "不記帳"}
        assert 欄位名們 == 預期必要欄位

        # 明確禁止塞入第二份模型、思考深度、權限、預算常數
        禁止欄位們 = {
            "模型",
            "思考深度",
            "權限",
            "預算token",
            "預算美金",
            "預算幾小時",
            "逾時",
            "用",
            "審查用",
        }
        for 禁止 in 禁止欄位們:
            assert 禁止 not in 欄位名們, f"階段動作規格不准含有常數或模型配置欄位：{禁止}"

    def test_階段動作規格不可變且型別嚴格(self) -> None:
        """規格物件必須是 frozen dataclass，避免傳遞過程被竄改。"""
        規格 = 階段動作規格(
            階段=階段代碼.測試,
            題目="寫測試",
            提示檔=None,
            工作目錄=Path("var/work"),
            帳本目錄=Path("var/ledger"),
            不記帳=False,
        )
        with pytest.raises((dataclasses.FrozenInstanceError, TypeError)):
            規格.題目 = "改題目"  # type: ignore[misc]


class Test階段代碼門面解析行為:
    """七個 stage code 都能被解析器辨識，未知字串與缺輸入在發模型前失敗。"""

    def test_七個正典階段代碼皆可正確解析(self) -> None:
        """七個 stage code 都可被 parser 辨識並建出對應的規格。"""
        案例們 = [
            (["test", "題目1"], 階段代碼.測試, "題目1", None),
            (["verify-red"], 階段代碼.驗證紅, None, None),
            (["impl", "--提示檔", "impl_prompt.md"], 階段代碼.實作, None, Path("impl_prompt.md")),
            (["verify-green"], 階段代碼.驗證綠, None, None),
            (["refactor", "重構程式"], 階段代碼.重構, "重構程式", None),
            (["verify-refactor"], 階段代碼.驗證重構, None, None),
            (["review", "審查程式"], 階段代碼.審查, "審查程式", None),
        ]

        for argv, 預期階段, 預期題目, 預期提示檔 in 案例們:
            規格 = 解析階段動作(argv)
            assert 規格.階段 is 預期階段, f"解析 {argv} 得到的階段不符"
            assert 規格.題目 == 預期題目
            assert 規格.提示檔 == 預期提示檔

    def test_驗證階段不需題目且在TDD階段表中為判準種類(self) -> None:
        """verify-* 是機械判準而非模型角色，不吃 prompt 也不需模型。"""
        驗證代碼們 = (階段代碼.驗證紅, 階段代碼.驗證綠, 階段代碼.驗證重構)
        for 代碼 in 驗證代碼們:
            規格 = 解析階段動作([代碼.value])
            assert 規格.階段 is 代碼
            assert 規格.題目 is None
            assert 規格.提示檔 is None

            # 驗證在 TDD階段表中為判準種類
            定義 = next(定 for 定 in TDD階段表 if 定.代碼 is 代碼)
            assert 定義.種類 is 種類.判準, f"{代碼.value} 必須是機械判準種類"

    def test_模型階段缺題目與提示檔時拒絕(self) -> None:
        """需要模型的階段若未提供題目亦無提示檔，必須在發模型前拒絕。"""
        模型階段們 = ("test", "impl", "refactor", "review")
        for 動作 in 模型階段們:
            with pytest.raises((ValueError, SystemExit)):
                解析階段動作([動作])

    def test_未知階段字串拒絕且禁止猜測或默認到impl(self) -> None:
        """打錯字或未知階段必須直接失敗（退出碼/例外），禁止模糊猜測或靜默 fallback 到 impl。"""
        未知字串們 = ("testt", "impll", "foobar", "build", "routine")
        for 未知 in 未知字串們:
            with pytest.raises((ValueError, SystemExit)):
                解析階段動作([未知, "隨便題目"])

    def test_工作目錄與帳本選項正確傳遞(self) -> None:
        """窄介面旗標（工作目錄、帳本目錄、不記帳）正確解析並帶入規格。"""
        規格 = 解析階段動作(
            [
                "impl",
                "實作邏輯",
                "--工作目錄",
                "sub/dir",
                "--帳本目錄",
                "custom/ledger",
                "--不記帳",
            ]
        )
        assert 規格.階段 is 階段代碼.實作
        assert 規格.題目 == "實作邏輯"
        assert 規格.工作目錄 == Path("sub/dir")
        assert 規格.帳本目錄 == Path("custom/ledger")
        assert 規格.不記帳 is True


class Test低階入口與別名相容:
    """nova 問 保留 20+ 低階旗標，nova 重構 若為相容入口只能是 refactor 薄別名。"""

    def test_nova問保留完整低階旗標(self) -> None:
        """nova 問 的低階細粒度旗標數不可被誤砍（至少 20 個選項旗標）。

        這張假處理表要**蓋滿每一個子命令**：`建剖析器` 對登記漏掉的名字是
        當場 `KeyError`（不准安靜地少宣告一個子命令），所以新增子命令時
        這裡也要跟著補一格，否則紅的會是這支跟 nova 問 無關的測試。
        """
        所有處理名稱 = [
            "閘",
            "檢查指令",
            "檢查編輯",
            "繞過",
            "檢查提交訊息",
            "問",
            "重構",
            "工作流",
            "跑",
            "派工",
            "排程",
            "秘密",
            "狀態",
            "線",
            "收件",
            "顧問",
            "收",
            "帳本",
            "已處理",
            "生圖",
            "額度",
            "儀表板",
            "test",
            "verify-red",
            "impl",
            "verify-green",
            "refactor",
            "verify-refactor",
            "review",
        ]
        剖析器 = 建剖析器({名: (lambda _: 0) for 名 in 所有處理名稱})

        問剖析動作們 = [
            action
            for action in 剖析器._actions  # noqa: SLF001
            if getattr(action, "dest", None) == "子命令"
        ]
        assert 問剖析動作們, "必須有子命令剖析器"
        子命令動作 = 問剖析動作們[0]
        assert isinstance(子命令動作.choices, dict), "子命令 choices 必須是字典"
        assert "問" in 子命令動作.choices, "nova 問 子命令必須存在"
        問子剖析 = 子命令動作.choices["問"]

        旗標選項們 = {opt for action in 問子剖析._actions for opt in action.option_strings}  # noqa: SLF001
        預期核心旗標 = {
            "--提示檔",
            "--用",
            "--工作",
            "--模型",
            "--思考深度",
            "--預算token",
            "--預算美金",
            "--預算幾小時",
            "--不記全文",
            "--執行檔",
            "--工作目錄",
            "--逾時",
            "--json",
            "--可編輯",
            "--全開",
            "--續接",
            "--保留對話",
            "--不隔離設定",
            "--帳本目錄",
            "--不記帳",
            "--輸出檔",
            "--背景",
            "--熔斷",
        }
        for 旗標 in 預期核心旗標:
            assert 旗標 in 旗標選項們, f"nova 問 缺少低階旗標：{旗標}"


class Test架構邊界與Protocol防護:
    """以 AST 與路徑斷言不新增 src/nova/圖/、節點註冊表、編排 DSL，也不修改 語言模型 Protocol。"""

    def test_不新增圖目錄與節點註冊表與編排DSL(self) -> None:
        """本票只做階段代碼門面解析，不得引入圖、節點註冊表或編排 DSL。"""
        圖路徑 = 專案根 / "src" / "nova" / "圖"
        assert not 圖路徑.exists(), "禁止新增 src/nova/圖/ 目錄"

        nova原始碼目錄 = 專案根 / "src" / "nova"
        for py檔 in nova原始碼目錄.rglob("*.py"):
            檔名 = py檔.name
            assert "DSL" not in 檔名, f"禁止新增 DSL 相關檔案：{py檔}"
            assert "編排" not in 檔名, f"禁止新增編排相關檔案：{py檔}"
            assert "節點註冊" not in 檔名, f"禁止新增節點註冊相關檔案：{py檔}"

    def test_語言模型Protocol維持原樣未被修改(self) -> None:
        """語言模型 Protocol 僅有 名稱 屬性與 詢問 方法，本票不得修改其簽章或擴充。"""
        角色契約原始碼路徑 = 專案根 / "src" / "nova" / "契約" / "角色.py"
        語法樹 = ast.parse(角色契約原始碼路徑.read_text(encoding="utf-8"))

        語言模型節點: ast.ClassDef | None = None
        for 節點 in 語法樹.body:
            if isinstance(節點, ast.ClassDef) and 節點.name == "語言模型":
                語言模型節點 = 節點
                break

        assert 語言模型節點 is not None, "未在 契約/角色.py 找到 語言模型 ClassDef"

        函式與屬性名們 = {
            子節點.name
            for 子節點 in 語言模型節點.body
            if isinstance(子節點, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        錯誤訊息 = f"語言模型 Protocol 被改動，現有方法為：{函式與屬性名們}"
        assert 函式與屬性名們 == {"名稱", "詢問"}, 錯誤訊息
