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
    必須覆蓋: frozenset[int]
    該紅: tuple[str, ...]
    最多秒: float
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
        必須覆蓋=frozenset({36}),
        該紅=("tests/單元/test_派工表.py::test_派法必須明確指定思考深度",),
        最多秒=2.0,
    ),
    變異(
        識別="例行深度改錯",
        目標檔=Path("src/nova/載體/派工表.py"),
        操作=替換一次(
            '工作種類.例行: 派法(腦們=("agy", "claude"), 思考深度="high")',
            '工作種類.例行: 派法(腦們=("agy", "claude"), 思考深度="low")',
        ),
        必須覆蓋=frozenset({28}),
        該紅=("tests/單元/test_派工表.py::test_例行工作的思考深度是high",),
        最多秒=2.0,
    ),
    變異(
        識別="推理深度改錯",
        目標檔=Path("src/nova/載體/派工表.py"),
        操作=替換一次(
            '工作種類.推理: 派法(腦們=("codex",), 思考深度="max", 模型=codex高階模型)',
            '工作種類.推理: 派法(腦們=("codex",), 思考深度="low", 模型=codex高階模型)',
        ),
        必須覆蓋=frozenset({29}),
        該紅=("tests/單元/test_派工表.py::test_推理工作的思考深度是max",),
        最多秒=2.0,
    ),
    變異(
        識別="角色深度不轉遞",
        目標檔=Path("src/nova/載體/角色.py"),
        操作=替換一次("思考深度=self.思考深度,", "思考深度=None,"),
        必須覆蓋=frozenset({49}),
        該紅=("tests/單元/test_角色.py::Test固定提示角色::test_思考深度會傳進呼叫選項",),
        最多秒=2.0,
    ),
    變異(
        識別="藍圖深度不轉遞",
        目標檔=Path("src/nova/迴圈/角色工廠.py"),
        操作=替換一次("思考深度=藍圖.思考深度,", "思考深度=None,"),
        必須覆蓋=frozenset({42}),
        該紅=("tests/單元/test_角色工廠.py::test_藍圖的模型與思考深度要傳進角色",),
        最多秒=2.0,
    ),
    變異(
        識別="藍圖模型不轉遞",
        目標檔=Path("src/nova/迴圈/角色工廠.py"),
        操作=替換一次("模型=藍圖.模型,", "模型=None,"),
        必須覆蓋=frozenset({41}),
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
        必須覆蓋=frozenset({127}),
        該紅=("tests/單元/test_節點契約.py::test_節點結果未知的結果是退出碼三",),
        最多秒=2.0,
    ),
    變異(
        識別="結果未知退出碼改錯",
        目標檔=Path("src/nova/契約/節點.py"),
        操作=替換一次("return 結果代碼.結果未知", "return 結果代碼.確定失敗"),
        必須覆蓋=frozenset({127}),
        該紅=("tests/單元/test_節點契約.py::test_節點結果未知的結果是退出碼三",),
        最多秒=2.0,
    ),
    變異(
        識別="護欄原因少一格",
        目標檔=Path("src/nova/契約/節點.py"),
        操作=刪除一次('    扇出超限 = "fanout-limit"\n'),
        必須覆蓋=frozenset({34}),
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
        必須覆蓋=frozenset({148}),
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
        必須覆蓋=frozenset({188}),
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
        必須覆蓋=frozenset({188}),
        該紅=("tests/單元/test_節點契約.py::test_執行節點接受不繼承基底的形狀相同物件",),
        最多秒=2.0,
    ),
    變異(
        識別="規範落點漏登記",
        目標檔=Path("src/nova/載體/規範落點.py"),
        操作=替換一次(
            "        if 規則.識別 not in 登記集合 and 規則.標籤 not in 登記集合",
            "        if False",
        ),
        必須覆蓋=frozenset({173}),
        該紅=("tests/單元/test_規範落點.py::test_文件多一條規則但登記表沒跟上時會紅",),
        最多秒=2.0,
    ),
)
