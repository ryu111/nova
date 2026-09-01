"""收尾現場查詢與結果正規化測試。

本測試驗證：
1. 私有且不可變的收尾快照與命令結果資料結構。
2. 狀態觀測：DIRTY、BEHIND、CLEAN、BLOCKED、UNSTABLE、DRAFT 與未知狀態不能互相冒充。
3. 假 gh pr view 各種已知狀態正確正規化，壞 JSON、缺欄位、未知狀態不落入「預設可合併」且回未知碼 3。
4. PR 身分不明或多個 PR 同時開啟時，不靠第一筆猜測，回未知碼 3 並停止。
5. 查詢逾時、工具不存在回未知碼 3，已知失敗回 1，安全前置不滿足回 4。
6. CLI 指令以 argv list 執行，不透過 shell 字串。
7. 明確給定 PR 編號／URL 時直接查該 PR，並以本次工作樹 HEAD 證明目標；
   子程序原始退出碼與 nova 正規化碼分欄保存，不把非零一律壓成 1。
"""

import dataclasses
import json
import os
import stat
import sys
from pathlib import Path
from typing import cast

import pytest

from nova.契約.退出碼 import 放行, 未知, 護欄碼, 閘紅
from nova.載體.收尾現場 import (
    收尾快照,
    收尾指令結果,
    收尾狀態,
    查收尾現場,
    跑收尾指令,
)


def _造假git與gh(專案: Path, 測具: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """在專案外造會依環境變數回傳結構化資料並記錄 argv 的假 `git` 與假 `gh`。"""
    專案.mkdir(parents=True, exist_ok=True)
    執行檔目錄 = 測具 / "假執行檔"
    執行檔目錄.mkdir(parents=True, exist_ok=True)
    紀錄 = 測具 / "收尾指令.jsonl"

    腳本 = f"""#!{sys.executable}
import json
import os
import pathlib
import sys
import time

程式 = pathlib.Path(sys.argv[0]).name
argv = sys.argv[1:]

紀錄檔 = os.environ.get('NOVA_收尾現場紀錄')
if 紀錄檔:
    with open(紀錄檔, 'a', encoding='utf-8') as 檔:
        json.dump({{'程式': 程式, 'argv': argv}}, 檔, ensure_ascii=False)
        檔.write('\\n')

def 造PR(編號, 分支, sha, 狀態='CLEAN'):
    return {{
        'number': 編號,
        'url': 'https://github.com/org/repo/pull/%d' % 編號,
        'headRefName': 分支,
        'headRefOid': sha,
        'baseRefName': 'main',
        'mergeStateStatus': 狀態,
    }}

本地HEAD = 'abc1234567890'
兩個開啟的PR = [
    造PR(101, 'feat/甲', 'sha101dead'),
    造PR(102, 'feat/乙', 本地HEAD),
]

if 程式 == 'gh':
    模式 = os.environ.get('NOVA_GH_模式', '')
    子命令 = argv[1] if argv[:1] == ['pr'] and len(argv) > 1 else ''
    目標 = ''.join(字 for 字 in (argv[2] if len(argv) > 2 else '') if 字.isdigit())

    if 模式 == '逾時':
        time.sleep(30)
    if 模式.startswith('失敗_'):
        sys.stderr.write('gh: command failed\\n')
        sys.exit(int(模式.split('_')[1]))

    if 模式 == '多個PR':
        if 子命令 == 'list':
            sys.stdout.write(json.dumps(兩個開啟的PR))
            sys.exit(0)
        if 子命令 == 'view':
            對上 = [pr for pr in 兩個開啟的PR if str(pr['number']) == 目標]
            if 對上:
                sys.stdout.write(json.dumps(對上[0]))
                sys.exit(0)
            sys.stderr.write('gh: no pull request found\\n')
            sys.exit(1)

    # 其餘模式：list 一律正常回一筆對得上分支的 PR，壞資料只出現在 view 邊界。
    if 子命令 == 'list':
        sys.stdout.write(json.dumps([造PR(123, 'feat/收尾', 本地HEAD)]))
        sys.exit(0)

    if 子命令 == 'view':
        if 模式 == '壞JSON':
            sys.stdout.write('{{invalid json')
            sys.exit(0)
        if 模式 == '缺欄位':
            sys.stdout.write(json.dumps({{'number': 123}}))
            sys.exit(0)
        if 模式 == '未知狀態':
            sys.stdout.write(json.dumps(
                造PR(123, 'feat/收尾', 本地HEAD, 'MYSTERY_STATUS')))
            sys.exit(0)
        if 模式 == 'SHA不符':
            sys.stdout.write(json.dumps(造PR(123, 'feat/收尾', '9999另一顆sha')))
            sys.exit(0)
        if 模式.startswith('狀態_'):
            sys.stdout.write(json.dumps(
                造PR(123, 'feat/收尾', 本地HEAD, 模式.replace('狀態_', ''))))
            sys.exit(0)
        sys.stdout.write(json.dumps(造PR(123, 'feat/收尾', 本地HEAD)))
        sys.exit(0)

if 程式 == 'git':
    if argv[:2] == ['rev-parse', 'HEAD']:
        sys.stdout.write('abc1234567890\\n')
        sys.exit(0)
    if argv[:3] == ['rev-parse', '--abbrev-ref', 'HEAD']:
        sys.stdout.write('feat/收尾\\n')
        sys.exit(0)

sys.exit(0)
"""
    for 名稱 in ("git", "gh"):
        路徑 = 執行檔目錄 / 名稱
        路徑.write_text(腳本, encoding="utf-8")
        路徑.chmod(路徑.stat().st_mode | stat.S_IEXEC)

    monkeypatch.setenv("NOVA_收尾現場紀錄", str(紀錄))
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join((str(執行檔目錄), os.environ.get("PATH", ""))),
    )
    return 紀錄


def _讀呼叫(紀錄: Path) -> list[tuple[str, list[str]]]:
    """把假 CLI 的 JSONL 紀錄還原成（程式名、argv）。"""
    if not 紀錄.exists():
        return []
    呼叫: list[tuple[str, list[str]]] = []
    for 行 in 紀錄.read_text(encoding="utf-8").splitlines():
        if not 行.strip():
            continue
        資料 = cast(dict[str, object], json.loads(行))
        參數 = [str(值) for 值 in cast(list[object], 資料["argv"])]
        呼叫.append((str(資料["程式"]), 參數))
    return 呼叫


class Test不可變契約與狀態觀測:
    def test_收尾快照不可變(self) -> None:
        """收尾快照必須是 frozen dataclass，不允許在途中被修改。"""
        快照 = 收尾快照(
            PR編號=123,
            PR網址="https://github.com/org/repo/pull/123",
            head分支="feat/收尾",
            head_sha="abc1234567890",
            base分支="main",
            狀態=收尾狀態.CLEAN,
            退出碼=放行,
            證據="",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            快照.狀態 = 收尾狀態.DIRTY  # type: ignore[misc]

    def test_收尾指令結果不可變(self) -> None:
        """收尾指令結果必須是不可變的資料結構。"""
        結果 = 收尾指令結果(
            argv=("git", "status"),
            退出碼=放行,
            stdout="clean",
            stderr="",
            逾時=False,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            結果.退出碼 = 閘紅  # type: ignore[misc]

    def test_狀態值皆為ASCII且涵蓋所有觀測值(self) -> None:
        """收尾狀態值需跨程序傳遞，必須為 ASCII 且各狀態不能互相冒充。"""
        所有狀態 = {成員.value for 成員 in 收尾狀態}
        期望狀態 = {"DIRTY", "BEHIND", "CLEAN", "BLOCKED", "UNSTABLE", "DRAFT", "UNKNOWN"}
        assert 所有狀態 == 期望狀態
        for 成員 in 收尾狀態:
            assert 成員.value.isascii()


class Test現場查詢與結果正規化:
    @pytest.mark.parametrize(
        ("狀態名稱", "預期狀態"),
        [
            ("CLEAN", 收尾狀態.CLEAN),
            ("DIRTY", 收尾狀態.DIRTY),
            ("BEHIND", 收尾狀態.BEHIND),
            ("BLOCKED", 收尾狀態.BLOCKED),
            ("UNSTABLE", 收尾狀態.UNSTABLE),
            ("DRAFT", 收尾狀態.DRAFT),
        ],
    )
    def test_假gh回已知狀態時快照保留原始狀態與SHA(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        狀態名稱: str,
        預期狀態: 收尾狀態,
    ) -> None:
        """假 gh pr view 回已知狀態時，快照保留原始狀態與 head SHA，退出碼為放行 0。"""
        專案 = tmp_path / "專案"
        _造假git與gh(專案, tmp_path / "測具", monkeypatch)
        monkeypatch.setenv("NOVA_GH_模式", f"狀態_{狀態名稱}")

        快照 = 查收尾現場(專案, 分支="feat/收尾")

        assert 快照.PR編號 == 123
        assert 快照.PR網址 == "https://github.com/org/repo/pull/123"
        assert 快照.head分支 == "feat/收尾"
        assert 快照.head_sha == "abc1234567890"
        assert 快照.base分支 == "main"
        assert 快照.狀態 == 預期狀態
        assert 快照.退出碼 == 放行

    def test_壞JSON回未知三且包含目前不知道(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回壞 JSON 時不能當作可合併，必須回傳未知碼 3 並附帶「目前不知道」證據。"""
        專案 = tmp_path / "專案"
        _造假git與gh(專案, tmp_path / "測具", monkeypatch)
        monkeypatch.setenv("NOVA_GH_模式", "壞JSON")

        快照 = 查收尾現場(專案, 分支="feat/收尾")

        assert 快照.退出碼 == 未知
        assert 快照.狀態 == 收尾狀態.UNKNOWN
        assert "目前不知道" in 快照.證據

    def test_缺欄位回未知三且不落入預設可合併(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回傳資料缺少必要欄位時，不能落入預設可合併，必須回傳未知碼 3。"""
        專案 = tmp_path / "專案"
        _造假git與gh(專案, tmp_path / "測具", monkeypatch)
        monkeypatch.setenv("NOVA_GH_模式", "缺欄位")

        快照 = 查收尾現場(專案, 分支="feat/收尾")

        assert 快照.退出碼 == 未知
        assert 快照.狀態 == 收尾狀態.UNKNOWN
        assert "目前不知道" in 快照.證據

    def test_未定義狀態回未知三且不落入預設可合併(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回傳未定義的狀態字串時，必須判定為未知狀態並回傳未知碼 3。"""
        專案 = tmp_path / "專案"
        _造假git與gh(專案, tmp_path / "測具", monkeypatch)
        monkeypatch.setenv("NOVA_GH_模式", "未知狀態")

        快照 = 查收尾現場(專案, 分支="feat/收尾")

        assert 快照.退出碼 == 未知
        assert 快照.狀態 == 收尾狀態.UNKNOWN
        assert "目前不知道" in 快照.證據

    def test_多個開啟PR且身分不明時回未知三不猜測(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PR 身分不明時不准靠第一筆猜測，兩個開啟 PR 且無法比對分支時回未知 3。"""
        專案 = tmp_path / "專案"
        紀錄 = _造假git與gh(專案, tmp_path / "測具", monkeypatch)
        monkeypatch.setenv("NOVA_GH_模式", "多個PR")

        快照 = 查收尾現場(專案, 分支="未知分支")

        assert 快照.退出碼 == 未知
        assert 快照.狀態 == 收尾狀態.UNKNOWN
        assert "目前不知道" in 快照.證據

        # 未知之後不發任何會改遠端的指令（如 merge 或 push）
        呼叫 = _讀呼叫(紀錄)
        assert not any(
            名稱 == "gh" and len(參數) >= 2 and 參數[:2] == ["pr", "merge"] for 名稱, 參數 in 呼叫
        )

    def test_查詢逾時回未知三且附帶目前不知道(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """查詢 timeout 回傳未知碼 3 並記錄「目前不知道」，外圈不准重跑。"""
        專案 = tmp_path / "專案"
        _造假git與gh(專案, tmp_path / "測具", monkeypatch)
        monkeypatch.setenv("NOVA_GH_模式", "逾時")

        快照 = 查收尾現場(專案, 分支="feat/收尾", 逾時秒=0.05)

        assert 快照.退出碼 == 未知
        assert 快照.狀態 == 收尾狀態.UNKNOWN
        assert "目前不知道" in 快照.證據

    def test_工具不存在回未知三(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """gh 或 git 執行檔不存在時回未知碼 3。"""
        專案 = tmp_path / "專案"
        專案.mkdir(parents=True, exist_ok=True)
        # 設定 PATH 為空目錄以模擬指令不存在
        空目錄 = tmp_path / "空目錄"
        空目錄.mkdir()
        monkeypatch.setenv("PATH", str(空目錄))

        快照 = 查收尾現場(專案, 分支="feat/收尾")

        assert 快照.退出碼 == 未知
        assert "目前不知道" in 快照.證據


class Test明確PR目標與HEAD證明:
    """PR 身分要能由呼叫端明確指定，並以本次工作樹的 HEAD 證明查到的是同一顆 commit。"""

    @pytest.mark.parametrize(
        "PR目標",
        [102, "https://github.com/org/repo/pull/102"],
    )
    def test_明確給PR目標時直接查它不靠分支清單猜(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        PR目標: int | str,
    ) -> None:
        """兩個 PR 同時開啟時，給定 PR 編號或 URL 就直接 view 它，不得先 list 再挑第一個。"""
        專案 = tmp_path / "專案"
        紀錄 = _造假git與gh(專案, tmp_path / "測具", monkeypatch)
        monkeypatch.setenv("NOVA_GH_模式", "多個PR")

        快照 = 查收尾現場(
            專案,
            分支="feat/乙",
            PR目標=PR目標,
            HEAD_SHA="abc1234567890",
        )

        assert 快照.PR編號 == 102
        assert 快照.head_sha == "abc1234567890"
        assert 快照.base分支 == "main"
        assert 快照.狀態 == 收尾狀態.CLEAN
        assert 快照.退出碼 == 放行
        assert 快照.目標已證明 is True

        呼叫 = _讀呼叫(紀錄)
        assert any(名稱 == "gh" and 參數[:2] == ["pr", "view"] for 名稱, 參數 in 呼叫)
        assert not any(名稱 == "gh" and 參數[:2] == ["pr", "list"] for 名稱, 參數 in 呼叫)

    def test_headRefOid與工作樹HEAD不符時回未知三且不動遠端(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """headRefOid 不是本次工作樹的 HEAD 就證明不了目標：回未知 3，保留原始 SHA。"""
        專案 = tmp_path / "專案"
        紀錄 = _造假git與gh(專案, tmp_path / "測具", monkeypatch)
        monkeypatch.setenv("NOVA_GH_模式", "SHA不符")

        快照 = 查收尾現場(
            專案,
            分支="feat/收尾",
            PR目標=123,
            HEAD_SHA="abc1234567890",
        )

        assert 快照.目標已證明 is False
        assert 快照.退出碼 == 未知
        assert 快照.head_sha == "9999另一顆sha"
        assert "目前不知道" in 快照.證據

        呼叫 = _讀呼叫(紀錄)
        assert not any(
            名稱 == "gh" and 參數[:2] in (["pr", "merge"], ["pr", "edit"]) for 名稱, 參數 in 呼叫
        )


class Test指令執行正規化:
    def test_執行指令以參數串列執行且回傳不可變結果(self, tmp_path: Path) -> None:
        """收尾指令必須以 argv list 執行，不透過 shell 字串。"""
        專案 = tmp_path / "專案"
        專案.mkdir(parents=True, exist_ok=True)

        結果 = 跑收尾指令(專案, "echo", "hello")

        assert isinstance(結果, 收尾指令結果)
        assert 結果.argv == ("echo", "hello")
        assert 結果.退出碼 == 放行
        assert "hello" in 結果.stdout

    def test_確定失敗保留子程序原始退出碼且nova碼為閘紅一(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """子程序退出 7 時，nova 碼正規化成閘紅 1，但原始 7 必須分欄留著供後續判斷。"""
        專案 = tmp_path / "專案"
        _造假git與gh(專案, tmp_path / "測具", monkeypatch)
        monkeypatch.setenv("NOVA_GH_模式", "失敗_7")

        結果 = 跑收尾指令(專案, "gh", "pr", "view", "123")

        assert 結果.子程序退出碼 == 7
        assert 結果.退出碼 == 閘紅
        assert "command failed" in 結果.stderr or "command failed" in 結果.stdout

    def test_安全前置不滿足回護欄碼四(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """明確安全前置不滿足時（例如目標狀態為衝突 DIRTY 卻試圖推進），回傳護欄碼 4。"""
        專案 = tmp_path / "專案"
        _造假git與gh(專案, tmp_path / "測具", monkeypatch)
        monkeypatch.setenv("NOVA_GH_模式", "狀態_DIRTY")

        快照 = 查收尾現場(專案, 分支="feat/收尾", 要求可合併=True)

        assert 快照.退出碼 == 護欄碼
        assert 快照.狀態 == 收尾狀態.DIRTY
