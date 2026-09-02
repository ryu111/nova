"""`nova 線` 的唯讀看板整合測試。

**直接呼叫 `主程式`，不開子程序**：coverage 追不到子程序的行，
變異閘會判成 `WRONG_TEST：沒覆蓋`（`#141` 實測踩過同一個坑）。
底下的 `git` 子程序是**建測試資料**，不是被測對象，所以留著。
"""

import subprocess
from pathlib import Path

import pytest

from nova.載體 import 命令列


def _做一個乾淨的工作樹(專案: Path) -> None:
    專案.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=專案, check=True)
    (專案 / "README.md").write_text("測試用工作樹\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=專案, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=測試",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "初始化",
        ],
        cwd=專案,
        check=True,
    )


def _取出線段落(輸出文字: str, 線名關鍵字: str) -> list[str]:
    段落們 = [段.strip().splitlines() for 段 in 輸出文字.strip().split("\n\n")]
    for 段 in 段落們:
        if 段 and any(線名關鍵字 in 行 for 行 in 段 if 行.startswith("線：")):
            return 段
    pytest.fail(f"輸出中找不到包含 {線名關鍵字} 的線段落：\n{輸出文字}")


def test_沒有成果帳本時上一次怎麼收要誠實說查不到(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """沒有成果帳本時，不准把缺資料編成「成功」或退出碼 0。"""
    專案 = tmp_path / "某條線"
    _做一個乾淨的工作樹(專案)

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "狀態"))
    monkeypatch.chdir(專案)
    碼 = 命令列.主程式(["--根目錄", str(專案), "線"])

    輸出 = capsys.readouterr()
    合起來 = 輸出.out + 輸出.err
    assert 碼 == 0, 合起來
    收場欄 = next(行 for 行 in 輸出.out.splitlines() if "上一次怎麼收的" in 行)
    assert "查不到" in 收場欄, 輸出.out
    assert "成功" not in 收場欄, 收場欄
    assert "退出碼 0" not in 收場欄, 收場欄


def test_正在執行階段的線顯示當前階段代碼而非查不到(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """一條線正在 impl 階段時，nova 線 的「現在在哪一階」要顯示 impl，不是「查不到」。"""
    from nova.載體.帳本 import 專案識別
    from nova.載體.狀態 import 狀態根目錄

    主專案 = tmp_path / "主專案"
    _做一個乾淨的工作樹(主專案)

    線名 = "某條線"
    工作樹 = tmp_path / f"nova-wt-{線名}"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(工作樹), "HEAD"],
        cwd=主專案,
        check=True,
    )

    狀態根 = tmp_path / "狀態"
    monkeypatch.setenv("XDG_STATE_HOME", str(狀態根))

    # 派工模組是以「主專案識別＋線名.md」寫入背景輸出檔
    背景目錄 = 狀態根目錄() / "專案" / 專案識別(主專案) / "背景"
    背景目錄.mkdir(parents=True, exist_ok=True)
    (背景目錄 / f"{線名}.md").write_text(
        "→ test          寫一支會紅的測試\n"
        "→ verify-red    親眼看到它紅\n"
        "→ impl          最少的程式碼讓它綠\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(主專案)
    碼 = 命令列.主程式(["--根目錄", str(主專案), "線"])

    輸出 = capsys.readouterr()
    assert 碼 == 0, 輸出.out + 輸出.err

    段落 = _取出線段落(輸出.out, f"nova-wt-{線名}")
    階段欄 = next(行 for 行 in 段落 if "現在在哪一階" in 行)
    assert "impl" in 階段欄, f"預期階段欄要顯示 impl，實際輸出：{階段欄}"
    assert "查不到" not in 階段欄, f"不准把查不到當成答案：{階段欄}"


def test_收在護欄退出碼4的線顯示護欄生效而非還在跑(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """收在護欄（碼 4）的線，現在在哪一階顯示護欄且在跑為否。"""
    from nova.契約.成果 import 成果
    from nova.契約.遮罩 import 已經遮過了
    from nova.載體.已處理 import 已處理目錄, 歸檔
    from nova.載體.帳本 import 專案識別
    from nova.載體.狀態 import 狀態根目錄
    from nova.載體.狀態檔 import 寫下現況, 狀態檔, 現況

    主專案 = tmp_path / "主專案"
    _做一個乾淨的工作樹(主專案)

    線名 = "護欄線"
    工作樹 = tmp_path / f"nova-wt-{線名}"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(工作樹), "HEAD"],
        cwd=主專案,
        check=True,
    )

    狀態根 = tmp_path / "狀態"
    monkeypatch.setenv("XDG_STATE_HOME", str(狀態根))

    # 背景輸出檔可能留著過去執行中的階段
    背景目錄 = 狀態根目錄() / "專案" / 專案識別(主專案) / "背景"
    背景目錄.mkdir(parents=True, exist_ok=True)
    (背景目錄 / f"{線名}.md").write_text(
        "→ test          寫一支會紅的測試\n→ impl          最少的程式碼讓它綠\n",
        encoding="utf-8",
    )

    執行識別 = "20260901T120000Z-abcdef"
    成果紀錄 = 成果(
        執行識別碼=執行識別,
        任務=已經遮過了("測試任務", 因為="單元測試"),
        收場="護欄",
        退出碼=4,
        起="2026-09-01T12:00:00Z",
        迄="2026-09-01T12:01:00Z",
        走了幾階=3,
        總token=5000,
    )
    歸檔(成果紀錄, 目錄=已處理目錄(工作樹))

    寫下現況(
        現況(
            上次醒來="2026-09-01T12:01:00Z",
            上次結果="guardrail",
            上次退出碼=4,
            上次理由="超過最多步數 10 步",
            上次執行識別碼=執行識別,
        ),
        路徑=狀態檔(工作樹),
    )

    monkeypatch.chdir(主專案)
    碼 = 命令列.主程式(["--根目錄", str(主專案), "線"])

    輸出 = capsys.readouterr()
    assert 碼 == 0, 輸出.out + 輸出.err

    段落 = _取出線段落(輸出.out, f"nova-wt-{線名}")
    在跑欄 = next(行 for 行 in 段落 if "在跑嗎" in 行)
    階段欄 = next(行 for 行 in 段落 if "現在在哪一階" in 行)
    收場欄 = next(行 for 行 in 段落 if "上一次怎麼收的" in 行)
    assert "否" in 在跑欄, f"收在護欄的線不該顯示在跑：{在跑欄}"
    assert "護欄" in 階段欄, f"收在護欄的線那一格要顯示護欄：{階段欄}"
    assert "impl" not in 階段欄, f"收在護欄的線不該顯示舊階段：{階段欄}"
    assert "退出碼 4：護欄生效" in 收場欄, f"應顯示護欄生效：{收場欄}"
    assert "超過最多步數 10 步" in 收場欄, f"應顯示護欄原因：{收場欄}"


def test_從來沒跑過的線維持查不到階段(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """從來沒跑過的線，現在在哪一階維持顯示查不到。"""
    主專案 = tmp_path / "主專案"
    _做一個乾淨的工作樹(主專案)

    線名 = "空白線"
    工作樹 = tmp_path / f"nova-wt-{線名}"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(工作樹), "HEAD"],
        cwd=主專案,
        check=True,
    )

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "狀態"))
    monkeypatch.chdir(主專案)
    碼 = 命令列.主程式(["--根目錄", str(主專案), "線"])

    輸出 = capsys.readouterr()
    assert 碼 == 0, 輸出.out + 輸出.err

    段落 = _取出線段落(輸出.out, f"nova-wt-{線名}")
    階段欄 = next(行 for 行 in 段落 if "現在在哪一階" in 行)
    assert "查不到" in 階段欄, f"從未跑過的線應顯示查不到：{階段欄}"
