"""固定負控的可執行登記。

這裡只放 typed operation 與它們的組合；執行流程在同目錄的 runner。
"""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


def _雜湊(內容: bytes) -> str:
    return hashlib.sha256(內容).hexdigest()


def _套用文字(目標檔: Path, 原文: str, 變成: str) -> tuple[str, str]:
    文字 = 目標檔.read_text(encoding="utf-8")
    次數 = 文字.count(原文)
    assert 次數 == 1, f"錨點應恰好出現一次，實際 {次數} 次：{原文!r}"
    前 = _雜湊(目標檔.read_bytes())
    目標檔.write_text(文字.replace(原文, 變成, 1), encoding="utf-8")
    後 = _雜湊(目標檔.read_bytes())
    assert 前 != 後, "變異前後 SHA256 相同，代表變異沒有生效"
    return 前, 後


class 變異操作(Protocol):
    """一個可在副本上套用的變異。"""

    @property
    def 錨點(self) -> str: ...

    def 套用(self, 目標檔: Path) -> tuple[str, str]: ...


@dataclass(frozen=True, slots=True)
class 替換一次:
    """把唯一錨點替換一次。"""

    原文: str
    變成: str

    @property
    def 錨點(self) -> str:
        return self.原文

    def 套用(self, 目標檔: Path) -> tuple[str, str]:
        return _套用文字(目標檔, self.原文, self.變成)


@dataclass(frozen=True, slots=True)
class 刪除一次:
    """刪除唯一錨點。"""

    原文: str

    @property
    def 錨點(self) -> str:
        return self.原文

    def 套用(self, 目標檔: Path) -> tuple[str, str]:
        return _套用文字(目標檔, self.原文, "")


@dataclass(frozen=True, slots=True)
class 刪檔:
    """確認錨點後刪除整個檔案。"""

    原文: str

    @property
    def 錨點(self) -> str:
        return self.原文

    def 套用(self, 目標檔: Path) -> tuple[str, str]:
        文字 = 目標檔.read_text(encoding="utf-8")
        assert 文字.count(self.原文) == 1, f"錨點不是一次：{self.原文!r}"
        前 = _雜湊(目標檔.read_bytes())
        目標檔.unlink()
        後 = _雜湊(b"")
        assert 前 != 後, "刪檔後 SHA256 相同，代表變異沒有生效"
        return 前, 後


@dataclass(frozen=True, slots=True)
class 設定mtime:
    """只改檔案時間，供需要重現快取負控的登記使用。"""

    原文: str
    mtime: float

    @property
    def 錨點(self) -> str:
        return self.原文

    def 套用(self, 目標檔: Path) -> tuple[str, str]:
        文字 = 目標檔.read_text(encoding="utf-8")
        assert 文字.count(self.原文) == 1, f"錨點不是一次：{self.原文!r}"
        前 = _雜湊(目標檔.read_bytes())
        os.utime(目標檔, (self.mtime, self.mtime))
        後 = _雜湊(目標檔.read_bytes())
        assert 前 == 後, "設定 mtime 不應改變檔案內容"
        return 前, 後


@dataclass(frozen=True, slots=True)
class 預期掛住:
    """標記一個預期由 runner 逾時收掉的操作。"""

    原文: str
    秒: float

    @property
    def 錨點(self) -> str:
        return self.原文

    def 套用(self, 目標檔: Path) -> tuple[str, str]:
        文字 = 目標檔.read_text(encoding="utf-8")
        assert 文字.count(self.原文) == 1, f"錨點不是一次：{self.原文!r}"
        前 = _雜湊(目標檔.read_bytes())
        後 = _雜湊(目標檔.read_bytes())
        assert 前 == 後, "預期掛住不應改變檔案內容"
        return 前, 後


@dataclass(frozen=True, slots=True)
class 變異:
    """一筆可重播的負控規格。"""

    識別: str
    目標檔: Path
    操作: 變異操作
    該紅: tuple[str, ...]
    最多秒: float
    # None 是交給操作推導；顯式空集合只保留給沒有可追 coverage 的合法特例。
    必須覆蓋: frozenset[int] | None = None
    平台: str = "任何平台"
    預期掛住: bool = False

    @property
    def 目標(self) -> Path:
        return self.目標檔


登記 = (
    變異(
        識別="派工深度不得省略",
        目標檔=Path("src/nova/契約/派工.py"),
        操作=替換一次("思考深度: str", '思考深度: str = "high"'),
        該紅=("tests/單元/test_派工表.py::test_派法必須明確指定思考深度",),
        最多秒=2.0,
    ),
    變異(
        識別="例行深度改錯",
        目標檔=Path("src/nova/載體/派工表.py"),
        操作=替換一次(
            '工作種類.例行: 派法(腦們=("claude", "agy"), 思考深度="high")',
            '工作種類.例行: 派法(腦們=("claude", "agy"), 思考深度="low")',
        ),
        該紅=("tests/單元/test_派工表.py::test_例行工作的思考深度是high",),
        最多秒=2.0,
    ),
    變異(
        識別="推理深度改錯",
        目標檔=Path("src/nova/載體/派工表.py"),
        操作=替換一次(
            '工作種類.推理: 派法(腦們=("codex", "claude"), 思考深度="max", 模型=codex高階模型)',
            '工作種類.推理: 派法(腦們=("codex", "claude"), 思考深度="low", 模型=codex高階模型)',
        ),
        該紅=("tests/單元/test_派工表.py::test_推理工作的思考深度是max",),
        最多秒=2.0,
    ),
    變異(
        識別="角色深度不轉遞",
        目標檔=Path("src/nova/載體/角色.py"),
        操作=替換一次("思考深度=self.思考深度,", "思考深度=None,"),
        該紅=("tests/單元/test_角色.py::Test固定提示角色::test_思考深度會傳進呼叫選項",),
        最多秒=2.0,
    ),
    變異(
        識別="藍圖深度不轉遞",
        目標檔=Path("src/nova/迴圈/角色工廠.py"),
        操作=替換一次("思考深度=藍圖.思考深度,", "思考深度=None,"),
        該紅=("tests/單元/test_角色工廠.py::test_藍圖的模型與思考深度要傳進角色",),
        最多秒=2.0,
    ),
    變異(
        識別="藍圖模型不轉遞",
        目標檔=Path("src/nova/迴圈/角色工廠.py"),
        操作=替換一次("模型=藍圖.模型,", "模型=None,"),
        該紅=("tests/單元/test_角色工廠.py::test_藍圖的模型與思考深度要傳進角色",),
        最多秒=2.0,
    ),
    變異(
        識別="結果未知少了結果屬性",
        目標檔=Path("src/nova/契約/節點.py"),
        操作=刪除一次(
            "    @property\n"
            "    def 結果(self) -> 結果代碼:\n"
            '        """回傳結果未知終局。"""\n'
            "        return 結果代碼.結果未知\n"
        ),
        該紅=("tests/單元/test_節點契約.py::test_節點結果未知的結果是退出碼三",),
        最多秒=2.0,
    ),
    變異(
        識別="結果未知退出碼改錯",
        目標檔=Path("src/nova/契約/節點.py"),
        操作=替換一次("return 結果代碼.結果未知", "return 結果代碼.確定失敗"),
        該紅=("tests/單元/test_節點契約.py::test_節點結果未知的結果是退出碼三",),
        最多秒=2.0,
    ),
    變異(
        識別="護欄原因少一格",
        目標檔=Path("src/nova/契約/節點.py"),
        操作=刪除一次('    扇出超限 = "fanout-limit"\n'),
        該紅=("tests/單元/test_節點契約.py::test_護欄原因六種且只有這六種",),
        最多秒=2.0,
    ),
    變異(
        識別="節點上下文不再不可變",
        目標檔=Path("src/nova/契約/節點.py"),
        操作=替換一次(
            "@dataclass(frozen=True, slots=True)\nclass 節點上下文:",
            "@dataclass(slots=True)\nclass 節點上下文:",
        ),
        該紅=(
            r"tests/單元/test_節點契約.py::test_節點契約資料類別不可變[\u7bc0\u9ede\u4e0a\u4e0b\u6587]",
        ),
        最多秒=2.0,
    ),
    變異(
        識別="節點上下文不轉遞",
        目標檔=Path("src/nova/契約/節點.py"),
        操作=替換一次(
            "return 節點.執行(輸入, 上下文=上下文, 依賴=依賴)",
            "return 節點.執行(輸入, 上下文=None, 依賴=依賴)",
        ),
        該紅=("tests/單元/test_節點契約.py::test_節點上下文每一格都由呼叫者明傳",),
        最多秒=2.0,
    ),
    變異(
        識別="節點拒絕結構型實作",
        目標檔=Path("src/nova/契約/節點.py"),
        操作=替換一次(
            "return 節點.執行(輸入, 上下文=上下文, 依賴=依賴)",
            'raise TypeError("需要顯式基底")',
        ),
        該紅=("tests/單元/test_節點契約.py::test_執行節點接受不繼承基底的形狀相同物件",),
        最多秒=2.0,
    ),
    變異(
        識別="TDD階段逾時退回單次預設",
        目標檔=Path("src/nova/迴圈/角色工廠.py"),
        操作=替換一次("TDD階段預設逾時秒 = 3600.0", "TDD階段預設逾時秒 = 預設逾時秒"),
        # 這是模組層常數的變異，沒有可再追的執行行；固定測試直接驗值。
        必須覆蓋=frozenset(),
        該紅=("tests/整合/test_工作流逾時.py::test_TDD階段的預設逾時比單次問話長",),
        最多秒=3.0,
    ),
    變異(
        識別="高階模型改寫逾時",
        目標檔=Path("src/nova/載體/模型/轉接.py"),
        操作=替換一次("    return 選項.逾時秒", "    return 3600.0"),
        該紅=(
            "tests/整合/test_模型轉接.py::Test逾時由呼叫端決定::test_呼叫端指定的高低逾時都有效",
        ),
        最多秒=3.0,
    ),
    變異(
        識別="工作流逾時不轉進呼叫選項",
        目標檔=Path("src/nova/載體/命令列.py"),
        操作=替換一次(
            "結果 = [dataclasses.replace(藍圖, 逾時秒=參數.逾時) for 藍圖 in 結果]",
            "結果 = [dataclasses.replace(藍圖, 逾時秒=1800.0) for 藍圖 in 結果]",
        ),
        該紅=("tests/整合/test_工作流逾時.py::test_跑與工作流的逾時真的傳到呼叫選項",),
        最多秒=3.0,
    ),
    變異(
        識別="逾時訊息不帶實際上限",
        目標檔=Path("src/nova/載體/模型/轉接.py"),
        操作=替換一次("上限 {上限秒:g} 秒", "上限 0 秒"),
        該紅=("tests/整合/test_工作流逾時.py::test_逾時訊息要帶實際秒數上限與不准重跑指示",),
        最多秒=3.0,
    ),
    變異(
        識別="逾時診斷退到半成品後面",
        目標檔=Path("src/nova/載體/模型/轉接.py"),
        操作=替換一次(
            "文字=逾時訊息 + (部分回應.文字 or 部分標準輸出)[:部分輸出上限],",
            "文字=(部分回應.文字 or 部分標準輸出)[:部分輸出上限] + 逾時訊息,",
        ),
        該紅=("tests/單元/test_逾時撿回.py::Test逾時的回應::test_逾時診斷要在第一行",),
        最多秒=2.0,
    ),
    變異(
        識別="硬禁令把heredoc內文當命令",
        目標檔=Path("src/nova/載體/禁令.py"),
        操作=替換一次("_去掉heredoc內文(命令),", "命令,"),
        該紅=("tests/單元/test_禁令指令.py::test_heredoc內文提到缺少刪除分支的合併指令仍然放行",),
        最多秒=2.0,
    ),
    變異(
        識別="引號內旗標被當成參數",
        目標檔=Path("src/nova/載體/禁令.py"),
        操作=替換一次("posix=False,", "posix=True,"),
        該紅=("tests/單元/test_禁令指令.py::test_git_commit訊息提到旗標仍然放行",),
        最多秒=2.0,
    ),
    變異(
        識別="環境變數與sudo繞過真正命令判斷",
        目標檔=Path("src/nova/載體/禁令.py"),
        操作=替換一次(
            '    詞列 = _去掉命令前綴(詞列)\n    if not 詞列 or 詞列[0] != "git":',
            '    if not 詞列 or 詞列[0] != "git":',
        ),
        該紅=("tests/單元/test_禁令指令.py::test_命令前綴包住真的git仍然要擋",),
        最多秒=2.0,
    ),
    變異(
        識別="git全域旗標吃掉參數",
        目標檔=Path("src/nova/載體/禁令.py"),
        操作=替換一次("            子命令位置 += 2\n", "            子命令位置 += 1\n"),
        該紅=("tests/單元/test_禁令指令.py::test_命令前綴包住真的git仍然要擋",),
        最多秒=2.0,
    ),
    變異(
        識別="括號內的真正命令被黏住",
        目標檔=Path("src/nova/載體/禁令.py"),
        操作=替換一次('punctuation_chars="|;&()\\n",', 'punctuation_chars="|;&\\n",'),
        該紅=("tests/單元/test_禁令指令.py::test_命令前綴包住真的git仍然要擋",),
        最多秒=2.0,
    ),
    變異(
        識別="逾時訊息丟掉stderr開場白",
        目標檔=Path("src/nova/載體/模型/轉接.py"),
        操作=替換一次(
            ("    if not 部分標準輸出.strip():\n        return 逾時回應\n"),
            (
                "    if not 部分標準輸出.strip():\n"
                "        return replace(逾時回應, 文字=部分標準錯誤)\n"
            ),
        ),
        該紅=("tests/單元/test_逾時撿回.py::Test逾時的回應::test_codex開場白不是停滯位置",),
        最多秒=2.0,
    ),
    變異(
        識別="預設預算少算一輪",
        目標檔=Path("src/nova/契約/工作流.py"),
        操作=替換一次("預設最多token = 6_000_000", "預設最多token = 5_000_000"),
        該紅=(
            "tests/單元/test_工作流.py::Test預設預算要跑得完一輪::test_預設至少涵蓋一階實測成本乘上TDD階段數",
        ),
        最多秒=2.0,
    ),
    變異(
        識別="護欄建議值少算剩餘階數",
        目標檔=Path("src/nova/迴圈/工作流.py"),
        操作=替換一次(
            "剩餘token = 剩餘階數 * 估",
            "剩餘token = 估",
        ),
        該紅=(
            "tests/單元/test_工作流.py::Test預算要事前擋不是事後發現::test_建議值等於已花加剩餘階數乘花費並向上取整",
        ),
        最多秒=2.0,
    ),
    變異(
        識別="推導空集合會被負控抓到",
        目標檔=Path("tests/負控/執行器.py"),
        操作=替換一次("    return 要求\n", "    return frozenset()\n"),
        該紅=(
            "tests/負控/test_登記的變異會被殺.py::test_行號由操作推導且點錯先報WRONG_TEST_正常變異是KILLED",
        ),
        最多秒=5.0,
    ),
    變異(
        識別="跨行推導只取首行會被負控抓到",
        目標檔=Path("tests/負控/執行器.py"),
        操作=替換一次("    return 要求\n", "    return frozenset({首行})\n"),
        該紅=("tests/負控/test_行號錨點.py::test_跨行錨點的每個可執行行都被推導",),
        最多秒=2.0,
    ),
    變異(
        識別="同一批紅測試沒提早停",
        目標檔=Path("src/nova/迴圈/狀態機.py"),
        操作=替換一次("if 連紅次數 >= 卡住門檻:", "if 連紅次數 > 卡住門檻:"),
        該紅=("tests/單元/test_無進展護欄.py::test_同一批失敗測試且工作區未變要提早停",),
        最多秒=2.0,
    ),
    變異(
        識別="正常回頭邊誤判成無進展",
        目標檔=Path("src/nova/迴圈/狀態機.py"),
        操作=替換一次(
            "    次數: dict[tuple[階段代碼, str], int] = {}\n"
            "    for 步 in 軌跡:\n"
            "        if 步.判準綠 is not False:\n"
            "            continue\n"
            "        鍵 = (步.階段, 步.證據)",
            "    次數: dict[tuple[階段代碼, str], int] = {}\n"
            "    for 步 in 軌跡:\n"
            "        鍵 = 步.證據",
        ),
        該紅=("tests/單元/test_工作流.py::Test審查的回頭邊::test_審查一直要求修改會撞到步數上限",),
        最多秒=2.0,
    ),
    變異(
        識別="不可信資料不清除marker",
        目標檔=Path("src/nova/迴圈/工作流.py"),
        操作=刪除一次(
            "    while 開始標記 in 資料 or 結束標記 in 資料:\n"
            '        資料 = 資料.replace(開始標記, "").replace(結束標記, "")\n'
        ),
        該紅=(
            (
                "tests/單元/test_工作流.py::Test不可信上游輸出::"
                "test_前情與上一步證據都被fence且內嵌marker不能提早跳出"
            ),
        ),
        最多秒=2.0,
    ),
    變異(
        識別="格式排除解析被拔掉",
        目標檔=Path("src/nova/載體/豁免登記.py"),
        操作=替換一次(
            '    格式排除 = _展平路徑鍵(格式設定, 表名="format", 鍵們=_排除清單鍵)\n',
            "    格式排除: set[str] = set()\n",
        ),
        該紅=("tests/單元/test_豁免登記.py::test_格式排除要被當成未登記豁免而指名",),
        最多秒=2.0,
    ),
    變異(
        識別="外接設定解析被拔掉",
        目標檔=Path("src/nova/載體/豁免登記.py"),
        操作=替換一次(
            '        所有豁免.add(f"extend:{外接設定路徑}")\n',
            "        pass\n",
        ),
        該紅=("tests/單元/test_豁免登記.py::test_外接設定要被當成未登記豁免而指名",),
        最多秒=2.0,
    ),
    變異(
        識別="頂層排除解析被拔掉",
        目標檔=Path("src/nova/載體/豁免登記.py"),
        操作=替換一次(
            '    頂層排除 = _展平路徑鍵(ruff設定, 表名="", 鍵們=_排除清單鍵)\n',
            "    頂層排除: set[str] = set()\n",
        ),
        該紅=("tests/整合/test_豁免登記接線.py::test_ci閘經建規則表真的會跑ruff豁免",),
        最多秒=2.0,
    ),
    變異(
        識別="舊式頂層豁免解析被拔掉",
        目標檔=Path("src/nova/載體/豁免登記.py"),
        操作=替換一次(
            "    規則豁免 = _展平規則(ruff設定, _規則豁免鍵) | _展平規則(lint設定, _規則豁免鍵)\n"
            "    檔案豁免 = _展平檔案規則(ruff設定, _檔案豁免鍵) | "
            "_展平檔案規則(lint設定, _檔案豁免鍵)\n",
            "    規則豁免 = _展平規則(lint設定, _規則豁免鍵)\n"
            "    檔案豁免 = _展平檔案規則(lint設定, _檔案豁免鍵)\n",
        ),
        該紅=("tests/單元/test_豁免登記.py::test_舊式頂層豁免鍵也會攤平",),
        最多秒=2.0,
    ),
    變異(
        識別="本地腦不得當審查員",
        目標檔=Path("src/nova/載體/模型/本地.py"),
        操作=刪除一次(
            "    if 家族名 in 家們:\n"
            '        return f"{家族名} 沒有審查資格：9B 本地模型不能當審查員"\n'
        ),
        該紅=(
            "tests/整合/test_命令列.py::Test本地腦沒有審查資格::test_本地腦不准當審查員",
            "tests/單元/test_派工門面.py::test_門面不准本地腦當審查員",
        ),
        最多秒=2.0,
    ),
    變異(
        識別="門面漏接本地腦審查護欄",
        目標檔=Path("src/nova/__init__.py"),
        操作=刪除一次(
            "    不合格理由 = 審查資格理由(審查的)\n"
            "    if 不合格理由 is not None:\n"
            "        raise ValueError(不合格理由)\n"
        ),
        該紅=("tests/單元/test_派工門面.py::test_門面不准本地腦當審查員",),
        最多秒=2.0,
    ),
    變異(
        識別="帳本只算success收場的token",
        目標檔=Path("src/nova/載體/帳本讀取.py"),
        操作=替換一次(
            "            if isinstance(值, int):\n",
            '            if isinstance(值, int) and 事.get("outcome") == "success":\n',
        ),
        該紅=(
            "tests/單元/test_帳本讀取.py::Test每一種收場的token都要算::test_unknown收場的token算進總計",
            "tests/單元/test_帳本讀取.py::Test每一種收場的token都要算::test_失敗收場的token也算",
        ),
        最多秒=2.0,
    ),
    變異(
        識別="測試員提示拿掉讀取策略",
        目標檔=Path("src/nova/迴圈/角色提示.py"),
        操作=替換一次(
            "讀取策略：先定位、按需只讀真正需要的檔案，不要把整個工作目錄讀進來。\n"
            "\n專案規矩：繁體中文命名與註解，不准簡體字。測試放在 tests/ 底下。",
            "專案規矩：繁體中文命名與註解，不准簡體字。測試放在 tests/ 底下。",
        ),
        該紅=("tests/單元/test_角色提示.py::Test角色提示讀取策略::test_提示必須包含讀取策略段落",),
        最多秒=2.0,
    ),
    變異(
        識別="例行翻回agy打頭",
        目標檔=Path("src/nova/載體/派工表.py"),
        操作=替換一次(
            '工作種類.例行: 派法(腦們=("claude", "agy")',
            '工作種類.例行: 派法(腦們=("agy", "claude")',
        ),
        該紅=("tests/單元/test_派工表.py::test_例行工作第一順位是claude",),
        最多秒=2.0,
    ),
    變異(
        識別="推理列拿掉備援",
        目標檔=Path("src/nova/載體/派工表.py"),
        操作=替換一次(
            '工作種類.推理: 派法(腦們=("codex", "claude")',
            '工作種類.推理: 派法(腦們=("codex",)',
        ),
        該紅=("tests/單元/test_派工表.py::test_推理工作要有備援",),
        最多秒=2.0,
    ),
    變異(
        識別="接力換家把型號帶著走",
        目標檔=Path("src/nova/載體/模型/接力.py"),
        操作=替換一次("換家選項 = replace(選項, 模型=None)", "換家選項 = 選項"),
        該紅=(
            "tests/單元/test_接力腦.py::Test接力::test_選項原樣傳給每一顆_型號除外",
            "tests/單元/test_接力腦.py::Test型號只給第一家::test_換下一顆時把型號拿掉",
        ),
        最多秒=2.0,
    ),
    變異(
        識別="本地腦混進自動派工",
        目標檔=Path("src/nova/載體/派工表.py"),
        操作=替換一次(
            '工作種類.例行: 派法(腦們=("claude", "agy"), 思考深度="high")',
            '工作種類.例行: 派法(腦們=("claude", "local", "agy"), 思考深度="high")',
        ),
        該紅=("tests/單元/test_本地派工.py::test_能力未量到前本地腦只保留手動指定",),
        最多秒=2.0,
    ),
    變異(
        識別="agy把別家型號也加深度後綴",
        目標檔=Path("src/nova/載體/模型/轉接.py"),
        操作=替換一次(
            "    if not 型.startswith(_agy有深度後綴的族):\n        return 型\n",
            "",
        ),
        該紅=(
            "tests/整合/test_思考深度.py::Test三家各自實作同一個旋鈕::test_agy跑別家型號時不准加深度後綴",
        ),
        最多秒=3.0,
    ),
    變異(
        識別="gemini白名單被拆掉",
        目標檔=Path("src/nova/載體/模型/轉接.py"),
        操作=替換一次("    if 組好 != agy預設模型:", "    if False:"),
        該紅=("tests/單元/test_型號白名單.py::test_gemini族的其他型號一律當場擋[gemini-3.1-pro]",),
        最多秒=3.0,
    ),
    變異(
        識別="模型旗標沒接到藍圖",
        目標檔=Path("src/nova/載體/命令列.py"),
        操作=替換一次(
            '    if getattr(參數, "模型", None):\n'
            "        結果 = [dataclasses.replace(藍圖, 模型=參數.模型) for 藍圖 in 結果]\n",
            "",
        ),
        該紅=("tests/整合/test_模型旗標.py::test_模型旗標真的傳到呼叫選項",),
        最多秒=5.0,
    ),
    變異(
        識別="角色偷偷續接同一個對話",
        目標檔=Path("src/nova/載體/角色.py"),
        操作=替換一次(
            "                權限=self.權限,\n",
            '                權限=self.權限,\n                續接="同一段",\n',
        ),
        該紅=("tests/單元/test_換腦判準.py::test_角色結構上不可能續接到同一個對話",),
        最多秒=3.0,
    ),
    變異(
        識別="本地腦的審查資格檢查被一起放寬",
        目標檔=Path("src/nova/__init__.py"),
        操作=替換一次(
            "    不合格理由 = 審查資格理由(審查的)\n"
            "    if 不合格理由 is not None:\n"
            "        raise ValueError(不合格理由)\n",
            "",
        ),
        該紅=("tests/單元/test_換腦判準.py::test_本地腦仍然不准當審查員",),
        最多秒=3.0,
    ),
    變異(
        識別="工作區有紅卻判定為綠",
        目標檔=Path("src/nova/載體/工作區.py"),
        操作=替換一次(
            "工作區狀態.綠 if not 紅的 else 工作區狀態.紅,",
            "工作區狀態.綠,",
        ),
        該紅=("tests/整合/test_工作區判定.py::test_工作區有紅時指名哪幾支紅",),
        最多秒=2.0,
    ),
    變異(
        識別="工作區未知不准自動往下跑",
        目標檔=Path("src/nova/迴圈/工作流.py"),
        操作=替換一次(
            "if 結果.終局 is 終局.結果未知:",
            "if False and 結果.終局 is 終局.結果未知:",
        ),
        該紅=("tests/整合/test_工作區判定.py::test_判定為綠也不准自動往下執行",),
        最多秒=2.0,
    ),
    變異(
        識別="命令列又用家族名擋同一家",
        目標檔=Path("src/nova/載體/命令列.py"),
        操作=替換一次(
            "    審查家們 = _哪幾家(參數.審查用, 階段代碼.審查)\n",
            "    審查家們 = _哪幾家(參數.審查用, 階段代碼.審查)\n"
            "    if _哪幾家(參數.用, 階段代碼.測試) & 審查家們:\n"
            '        return "審查要換一顆腦"\n',
        ),
        該紅=("tests/整合/test_換腦判準走命令列.py::test_命令列也不再用家族名擋同一家",),
        最多秒=5.0,
    ),
    變異(
        識別="命令列的本地腦資格檢查被拔掉",
        目標檔=Path("src/nova/載體/命令列.py"),
        操作=替換一次(
            "    if (不合格理由 := 審查資格理由(審查家們)) is not None:\n"
            "        return 不合格理由\n",
            "",
        ),
        該紅=("tests/整合/test_換腦判準走命令列.py::test_命令列的本地腦資格檢查沒有被一起放寬",),
        最多秒=5.0,
    ),
    變異(
        識別="線的缺資料分支反向",
        目標檔=Path("src/nova/載體/線.py"),
        操作=替換一次("if 線.上一次 is None:", "if 線.上一次 is not None:"),
        該紅=("tests/整合/test_線.py::test_沒有成果帳本時上一次怎麼收要誠實說查不到",),
        最多秒=3.0,
    ),
    變異(
        識別="線的子命令登記消失",
        目標檔=Path("src/nova/載體/剖析器.py"),
        操作=刪除一次('    線剖析.set_defaults(執行=處理們["線"])\n'),
        該紅=("tests/整合/test_線.py::test_沒有成果帳本時上一次怎麼收要誠實說查不到",),
        最多秒=3.0,
    ),
    變異(
        識別="權限被擋改回結果未知",
        目標檔=Path("src/nova/契約/模型回應.py"),
        操作=替換一次(
            "    失敗代碼.權限被擋: 終局.確定失敗,",
            "    失敗代碼.權限被擋: 終局.結果未知,",
        ),
        該紅=(
            "tests/單元/test_模型回應.py::Test權限被擋是確定失敗::test_所以它的退出碼是確定失敗的那個",
        ),
        最多秒=2.0,
    ),
    變異(
        識別="權限分類與環境診斷被拿掉",
        目標檔=Path("src/nova/載體/模型/解析.py"),
        操作=刪除一次(
            "    if 代碼 is 失敗代碼.權限被擋:\n"
            '        環境說明 = "\\n（環境提示：--add-dir 給的是檔案存取、不涵蓋 command）"\n'
            '        文字 = f"{診斷[:診斷上限]}{環境說明}" if 診斷 else "CLI 回報成功但權限被拒"\n'
            "        首筆 = 答.原始輸出[0] "
            "if 答.原始輸出 and isinstance(答.原始輸出[0], dict) else {}\n"
            '        有跑過輪次 = int(首筆.get("num_turns") or 0) > 0\n'
            "        return replace(\n"
            "            答,\n"
            "            終局=終局.結果未知 if 有跑過輪次 else 終局判定(代碼),\n"
            "            失敗代碼=代碼,\n"
            "            文字=文字,\n"
            "        )\n"
        ),
        該紅=(
            "tests/單元/test_模型解析.py::Test權限被擋要分得出來::test_agy的auto_deny要分成確定失敗",
            "tests/單元/test_模型解析.py::Test權限被擋要分得出來::test_agy的auto_deny訊息要指得出家工具和權限",
        ),
        最多秒=3.0,
    ),
    變異(
        識別="收尾提交不得繞過驗證",
        目標檔=Path("src/nova/載體/命令列.py"),
        操作=替換一次(
            '        ("git", "commit", "-m", 訊息),',
            '        ("git", "commit", "--no-verify", "-m", 訊息),',
        ),
        該紅=("tests/整合/test_收尾紅線.py::Test收尾紅線::test_提交指令不准帶繞過驗證旗標",),
        最多秒=3.0,
    ),
    變異(
        識別="收尾合併不得使用管理員",
        目標檔=Path("src/nova/載體/命令列.py"),
        操作=替換一次(
            '        "--delete-branch",\n    )',
            '        "--delete-branch",\n        "--admin",\n    )',
        ),
        該紅=("tests/整合/test_收尾紅線.py::Test收尾紅線::test_合併指令不准帶管理員旗標",),
        最多秒=3.0,
    ),
    變異(
        識別="收尾合併必須刪除分支",
        目標檔=Path("src/nova/載體/命令列.py"),
        操作=刪除一次('        "--delete-branch",\n'),
        該紅=("tests/整合/test_收尾紅線.py::Test收尾紅線::test_合併指令一定帶刪除分支旗標",),
        最多秒=3.0,
    ),
    變異(
        識別="CI紅時不得走到合併",
        目標檔=Path("src/nova/載體/命令列.py"),
        操作=替換一次(
            (
                '        碼 := _跑並印收尾指令(根, "gh", "pr", "checks", "--required", '
                '"--watch", 逾時秒=參數.等CI秒)\n    ) != 放行:'
            ),
            (
                '        碼 := _跑並印收尾指令(根, "gh", "pr", "checks", "--required", '
                '"--watch", 逾時秒=參數.等CI秒)\n    ) == 放行:'
            ),
        ),
        該紅=("tests/整合/test_收尾紅線.py::Test收尾紅線::test_CI紅時不會組出合併指令",),
        最多秒=3.0,
    ),
    變異(
        識別="閘紅時不得繼續收尾",
        目標檔=Path("src/nova/載體/命令列.py"),
        操作=替換一次(
            "    if (碼 := _收尾閘(參數, 根)) != 放行:",
            "    if (碼 := _收尾閘(參數, 根)) == 放行:",
        ),
        該紅=("tests/整合/test_收尾紅線.py::Test收尾紅線::test_閘紅時後續提交推送開PR都不發生",),
        最多秒=3.0,
    ),
    變異(
        識別="CI逾時是結果未知",
        目標檔=Path("src/nova/載體/命令列.py"),
        操作=替換一次(
            "        return 未知, f\"指令等不到結果（{' '.join(指令)}）\"",
            "        return 閘紅, f\"指令等不到結果（{' '.join(指令)}）\"",
        ),
        該紅=("tests/整合/test_收尾紅線.py::Test收尾紅線::test_等不到CI回結果未知三",),
        最多秒=3.0,
    ),
    變異(
        識別="閘紅時不得自行修改檔案",
        目標檔=Path("src/nova/載體/命令列.py"),
        操作=替換一次(
            "    if (碼 := _收尾閘(參數, 根)) != 放行:\n        return 碼",
            (
                "    if (碼 := _收尾閘(參數, 根)) != 放行:\n"
                '        (根 / "收尾自動修復.txt").write_text(\n'
                '            "閘紅時不應修改\\n", encoding="utf-8"\n'
                "        )\n"
                "        return 碼"
            ),
        ),
        該紅=("tests/整合/test_收尾紅線.py::Test收尾紅線::test_閘紅時只跑閘不修改任何檔案",),
        最多秒=3.0,
    ),
    變異(
        識別="規範落點漏登記",
        目標檔=Path("src/nova/載體/規範落點.py"),
        操作=替換一次(
            "        if 規則.識別 not in 登記集合 and 規則.標籤 not in 登記集合",
            "        if False",
        ),
        該紅=("tests/單元/test_規範落點.py::test_文件多一條規則但登記表沒跟上時會紅",),
        最多秒=2.0,
    ),
    變異(
        識別="非main閘紅不准落票",
        目標檔=Path("src/nova/載體/閘紅成票.py"),
        操作=替換一次('    是main = 現場.分支 == "main"', "    是main = True"),
        該紅=("tests/單元/test_閘紅成票.py::test_不符合現場條件的閘紅絕對不落成票",),
        最多秒=2.0,
    ),
    變異(
        識別="同一閘紅不准重複落票",
        目標檔=Path("src/nova/載體/閘紅成票.py"),
        操作=替換一次(
            "    if _已有同一張閘紅票(目錄, 機器鍵):\n        return None",
            "    # 拿掉重複檢查\n    pass",
        ),
        該紅=("tests/單元/test_閘紅成票.py::test_待處理已有同一條閘紅票不准重複落成",),
        最多秒=2.0,
    ),
)
