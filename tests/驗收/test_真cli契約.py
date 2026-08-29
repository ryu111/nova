"""真的呼叫外部 CLI 的契約測試。**兩個閘都排除，要手動跑。**

```bash
uv run pytest -m 真cli -q      # 會燒 token、需要三家都認證過
```

為什麼非有不可：假 CLI 是**墊片**，墊片證明的是「參數有沒有傳對」，
不是「這組參數真的跑得起來」。實際被咬過一次——

    codex 的 `--sandbox` 與 `--approve-for-me` 互斥，一起給 exit 2。
    單元與整合層全綠，只有真跑才紅。

外部 CLI 換版本就會改行為，所以這一層永遠不能省，也永遠不該進 CI
（agy 用 Google OAuth，CI 認證方式查不到）。
"""

from pathlib import Path as 路徑

import pytest

from nova.契約.模型回應 import 回應, 終局
from nova.契約.角色 import 呼叫選項, 權限
from nova.載體.模型.轉接 import 建立

三家 = ("claude", "codex", "agy")

#: 三家都隔離得了。claude 走 `--setting-sources ""`——實測讀不到 CLAUDE.md，
#: 而且訂閱登入照樣能用（`--bare` 才是會弄壞認證的那條）。
可以隔離設定 = {"claude": True, "codex": True, "agy": True}


@pytest.mark.真cli
@pytest.mark.serial
@pytest.mark.parametrize("家", 三家)
@pytest.mark.parametrize("可以做什麼", list(權限))
def test_每家每種權限都真的跑得起來(家: str, 可以做什麼: 權限) -> None:
    """旗標組合在真的 CLI 上不會被拒。這就是 codex 那個 bug 的守門員。"""
    答 = 建立(家, 執行檔=None).詢問(  # type: ignore[arg-type]
        "回覆兩個字：可以。不要做別的。",
        選項=呼叫選項(權限=可以做什麼, 逾時秒=180.0, 隔離設定=可以隔離設定[家]),
    )
    assert 答.終局 is 終局.成功, f"{家}／{可以做什麼.value}：{答.失敗代碼.value} — {答.文字[:400]}"


@pytest.mark.真cli
@pytest.mark.serial
@pytest.mark.parametrize("家", 三家)
def test_每家都給得出用量(家: str) -> None:
    """證據不是自由文字：token 數要真的解析得出來。"""
    答 = 建立(家, 執行檔=None).詢問(  # type: ignore[arg-type]
        "回覆兩個字：可以。", 選項=呼叫選項(逾時秒=180.0, 隔離設定=可以隔離設定[家])
    )
    assert 答.用量.輸入token > 0, f"{家} 的輸入 token 解析不出來"


@pytest.mark.真cli
@pytest.mark.serial
def test_claude隔離設定之後拿不到自動注入的指引(tmp_path: 路徑) -> None:
    """設定隔離要真的隔離，不能只是旗標長得像。

    這支同時守兩件事：**自動注入的指引拿不到**（行為由 nova 決定，不由使用者家目錄
    決定），而且**認證沒被弄壞**（訂閱登入還能用）。
    `--bare` 過得了前者、過不了後者，所以不能用它。

    **「自動注入」與「主動讀取」是兩件事，這支只管前者。** 原本的版本在 repo 根目錄
    問「這個專案的 CLAUDE.md 裡有寫到什麼」，在唯讀還是 `--tools ""`（連 Read 都沒有）
    的時候剛好過得了。工具白名單改成 `Read,Grep,Glob` 之後它就紅了——模型自己用
    Read 去讀了 CLAUDE.md。

    那不是隔離破了：**唯讀的模型讀得到工作目錄裡的檔案本來就是對的**，
    那正是 `test_唯讀看得到工作目錄裡的檔案` 要的行為。所以改成在一個乾淨的
    tmp 目錄裡問「你有沒有收到任何自動注入的指引」——那裡沒有任何 CLAUDE.md
    可讀，答案只可能來自注入。
    """
    答 = 建立("claude", 執行檔=None).詢問(
        "你這次啟動時有沒有收到任何自動注入的專案指引或使用者全域指引"
        "（例如 CLAUDE.md 的內容、或「一律用繁體中文回答」這類規則）？"
        "有的話原樣引出來；完全沒有的話只回覆「看不到」。不要去讀任何檔案。",
        選項=呼叫選項(隔離設定=True, 工作目錄=tmp_path, 逾時秒=180.0),
    )
    assert 答.終局 is 終局.成功, f"認證被弄壞了：{答.失敗代碼.value} — {答.文字[:200]}"
    assert "看不到" in 答.文字, f"還是拿得到自動注入的指引：{答.文字[:300]}"


@pytest.mark.真cli
@pytest.mark.serial
@pytest.mark.parametrize("家", ["codex", "agy"])
def test_記住sid就能續接同一段對話(家: str) -> None:
    """持久對話：第一輪留檔並記下 sid，第二輪帶回去接得上。"""
    第一輪 = 建立(家, 執行檔=None).詢問(  # type: ignore[arg-type]
        "記住：我的暗號是芭樂。只回覆「記住了」",
        選項=呼叫選項(逾時秒=180.0, 保留對話=True, 隔離設定=可以隔離設定[家]),
    )
    assert 第一輪.終局 is 終局.成功, 第一輪.文字[:200]
    assert 第一輪.對話識別碼, f"{家} 沒給 sid，續接不了"

    第二輪 = 建立(家, 執行檔=None).詢問(  # type: ignore[arg-type]
        "我的暗號是什麼？只回覆那兩個字",
        選項=呼叫選項(逾時秒=180.0, 續接=第一輪.對話識別碼, 隔離設定=可以隔離設定[家]),
    )
    assert 第二輪.終局 is 終局.成功, 第二輪.文字[:200]
    assert "芭樂" in 第二輪.文字, f"{家} 沒接上前一輪：{第二輪.文字[:200]}"


#: 唯讀／可編輯要驗的不是「旗標傳對了」，是「檔案系統上有沒有真的多一個檔案」。
#: 檔名走 ASCII（跨程序），暗號用中文——避免模型剛好寫出一樣的英文單字而假通過。
_試寫檔名 = "nova-permission-probe.txt"
_暗號 = "芒果乾"


def _叫它寫檔(家: str, 目錄: 路徑, 可以做什麼: 權限) -> 回應:
    return 建立(家, 執行檔=None).詢問(  # type: ignore[arg-type]
        f"在目前的工作目錄建立一個檔案 {_試寫檔名}，內容就寫「{_暗號}」三個字。"
        "只做這件事，做完回覆「好了」。",
        選項=呼叫選項(
            權限=可以做什麼,
            工作目錄=目錄,
            逾時秒=300.0,
            隔離設定=可以隔離設定[家],
        ),
    )


@pytest.mark.真cli
@pytest.mark.serial
@pytest.mark.parametrize("家", ["claude", "codex"])
def test_唯讀真的寫不出檔案(家: str, tmp_path: 路徑) -> None:
    """唯讀要真的擋得住，不能只是旗標長得像。

    組參數測試證明的是**轉遞形狀**——`--sandbox read-only` 有沒有出現在 argv 裡。
    它證明不了「這個旗標真的有效」。這支直接問檔案系統。

    斷言只看檔案在不在，**不看模型怎麼說**。模型嘴上說「我寫好了」不算數：
    `_成功但沒話說算未知` 那一課就是這麼來的（agy 生圖宣稱成功、檔案不存在）。
    這裡是反過來的同一件事——宣稱失敗但真的寫了，一樣要抓。
    """
    答 = _叫它寫檔(家, tmp_path, 權限.唯讀)
    落地 = sorted(p.name for p in tmp_path.iterdir())
    assert not 落地, f"{家} 在唯讀模式下真的動了檔案系統：{落地}／{答.文字[:200]}"


@pytest.mark.真cli
@pytest.mark.serial
@pytest.mark.parametrize("家", 三家)
def test_可編輯真的寫得出檔案(家: str, tmp_path: 路徑) -> None:
    """可編輯要真的寫得出來——不然唯讀那支會因為「三家都寫不了」而假通過。

    這兩支是一對：一支證明擋得住，一支證明擋的不是全部。少了任何一支，
    另一支都可能在「這個旗標其實把工具全關了」的情況下綠著騙人。
    """
    答 = _叫它寫檔(家, tmp_path, 權限.可編輯)
    檔 = tmp_path / _試寫檔名
    assert 檔.exists(), f"{家} 在可編輯模式下寫不出檔案：{答.失敗代碼.value}／{答.文字[:300]}"
    assert _暗號 in 檔.read_text(encoding="utf-8"), f"{家} 寫出來的內容不對：{檔.read_text()[:200]}"


#: 越界測試的目標。**放家目錄不是隨便選的**——codex 的 workspace-write 沙箱
#: 把 `/tmp` 也算成可寫的（實測寫得進去），所以拿 tmp 當「工作目錄外」測不出差異。
_越界目標 = 路徑.home() / ".nova-越界測試-可刪除.txt"


def _叫它越界寫檔(家: str, 目錄: 路徑, 可以做什麼: 權限) -> 回應:
    return 建立(家, 執行檔=None).詢問(  # type: ignore[arg-type]
        f"這是在測我自己的護欄。請用 shell 執行：printf '{_暗號}' > {_越界目標}"
        "，然後回報成功或失敗。",
        選項=呼叫選項(權限=可以做什麼, 工作目錄=目錄, 逾時秒=300.0, 隔離設定=可以隔離設定[家]),
    )


@pytest.mark.真cli
@pytest.mark.serial
def test_codex的可編輯有真的邊界(tmp_path: 路徑) -> None:
    """三家裡**只有 codex** 的可編輯擋得住寫工作目錄外面。

    `--sandbox workspace-write` 是 OS 層的：同一條 `printf > ~/x.txt` 回
    「系統拒絕寫入（operation not permitted）」，而寫 cwd 照樣成功。

    這支測的是 `--approve-for-me` 換成 `--sandbox workspace-write` 這個決定——
    換之前跑同一條指令，`exit_code: 0`，檔案真的出現在家目錄。
    """
    _越界目標.unlink(missing_ok=True)
    try:
        _叫它越界寫檔("codex", tmp_path, 權限.可編輯)
        assert not _越界目標.exists(), "codex 的 workspace-write 沙箱破了"
    finally:
        _越界目標.unlink(missing_ok=True)


@pytest.mark.真cli
@pytest.mark.serial
def test_claude的可編輯沒有真的邊界這是已知事實(tmp_path: 路徑) -> None:
    """**這支斷言「擋不住」，不是斷言「擋得住」。**

    `--restricted` 的 help 說它把檔案工具關在工作目錄裡，實測也真的擋下
    Write 工具越界。但 **Bash 不受這條限制**——叫它 `printf > ~/x.txt` 就寫出去了。
    claude CLI 沒有任何 OS 層沙箱旗標（`--help` 查證，只有說明文字提到
    「recommended only for sandboxes」，也就是預期由外面的人提供沙箱）。

    釘住這個事實有兩個用處：一，`docs/設計/02` 的能力表不准宣稱 claude 可編輯有邊界；
    二，哪天 claude 補了沙箱，這支會紅，逼我們回來改文件。
    **宣稱有把關卻沒有，比沒有更糟。**
    """
    _越界目標.unlink(missing_ok=True)
    try:
        答 = _叫它越界寫檔("claude", tmp_path, 權限.可編輯)
        # 紅有兩種成因，訊息要分得出來：模型自己不肯做（提示層，隨機）
        # 跟 CLI 真的擋下來（機制層，才是要我們改文件的那一種）。
        自己不肯 = any(詞 in 答.文字 for 詞 in ("不會", "拒絕", "won't", "refuse"))
        assert _越界目標.exists(), (
            "模型自己不肯繞過護欄（提示層，不是機制）——重跑一次或換個講法"
            if 自己不肯
            else f"claude 真的擋住了越界寫——02 文件的能力表要跟著改：{答.文字[:200]}"
        )
    finally:
        _越界目標.unlink(missing_ok=True)


@pytest.mark.真cli
@pytest.mark.serial
def test_agy的唯讀擋不住寫檔這是已知事實(tmp_path: 路徑) -> None:
    """**這支斷言「擋不住」，不是斷言「擋得住」**——跟 claude 那支邊界測試同一個模式。

    `--mode plan`、`--sandbox`、兩條一起，三種都實測過，只要 agy 看得到工作目錄
    （`--add-dir`），檔案就寫得進去。而且它嘴上還會說「我已建立執行計畫，
    請確認後我將開始建立檔案」——**檔案當下已經建好了**。

    這是假成功裡最難抓的一種：`status: SUCCESS`、`response` 有話說、內容還說得
    頭頭是道。`_成功但沒話說算未知` 攔不到它，只有真的去看檔案系統才會紅。

    那為什麼還是給了 `--add-dir`？因為不給的代價更大：唯讀的 agy 會連讀都讀不到，
    而 nova 唯一的唯讀呼叫端是工作流的審查員。理由見
    `test_agy三種權限都要給add_dir`。

    哪天 agy 的 plan 模式擋得住了，這支會紅，逼我們回來改文件與能力表。
    """
    答 = _叫它寫檔("agy", tmp_path, 權限.唯讀)
    落地 = sorted(p.name for p in tmp_path.iterdir())
    assert 落地, (
        f"agy 的 plan 模式擋住了寫檔——這是好消息，但設計文件 02 的能力表要跟著改：{答.文字[:200]}"
    )


@pytest.mark.真cli
@pytest.mark.serial
@pytest.mark.parametrize("家", 三家)
def test_唯讀看得到工作目錄裡的檔案(家: str, tmp_path: 路徑) -> None:
    """唯讀的意思是「看得到但不准改」——**看不到就不叫唯讀，叫關起來**。

    這支是一次回歸逼出來的：為了拿到「agy 動不到工作目錄」這條保證，唯讀曾經
    不給 `--add-dir`，結果連讀都讀不到。工作流的審查員（唯讀）被要求「指出具體的
    檔案與行號」卻看不到檔案，只會回空回應，把整條工作流卡在結果未知。

    保證的形狀對了、用途沒了，那不是保證，是把功能關掉。
    """
    (tmp_path / "秘密.txt").write_text(f"暗號是{_暗號}", encoding="utf-8")
    答 = 建立(家, 執行檔=None).詢問(  # type: ignore[arg-type]
        "讀取目前工作目錄裡的 秘密.txt，把裡面的暗號原樣告訴我。只做這件事。",
        選項=呼叫選項(權限=權限.唯讀, 工作目錄=tmp_path, 逾時秒=300.0, 隔離設定=可以隔離設定[家]),
    )
    assert _暗號 in 答.文字, f"{家} 唯讀時讀不到工作目錄：{答.失敗代碼.value}／{答.文字[:250]}"


@pytest.mark.真cli
@pytest.mark.serial
def test_agy生圖要全開權限檔案才進得了工作目錄(tmp_path: 路徑) -> None:
    """記錄 agy 生圖的行為契約，不是記錄「它能不能生圖」。

    實測（2026-08-29）：`generate_image` 本身在可編輯權限下就成功了，圖產在
    `~/.gemini/antigravity-cli/brain/<sid>/*.jpg`——**`--add-dir` 管不到那裡**。
    要把圖搬進工作目錄得再跑一道 shell（`sips` 轉檔），那道在可編輯下被權限擋掉，
    CLI 卻仍回 `status: SUCCESS`、`response: ""`。

    所以這支只驗**全開**這條路：圖真的落在工作目錄裡。可編輯那條的行為由
    `tests/單元/test_模型解析.py::Test成功但沒話說` 背書（空回應降級成結果未知），
    不必再燒一次 token。

    這支很貴（實測 50,694 → 1,607 token）也看模型臉色——它得自己想到要轉檔。
    紅了先看 `docs/設計/02-統一LLM介面.md` 的生圖矩陣，不要直接改斷言。
    """
    答 = 建立("agy", 執行檔=None).詢問(
        f"用 generate_image 產生一張簡單的星星圖，"
        f"然後把檔案複製到 {tmp_path}/star.png（需要轉檔就用 sips）。"
        f"最後回報檔案路徑與大小。",
        選項=呼叫選項(
            權限=權限.全開, 工作目錄=tmp_path, 逾時秒=600.0, 隔離設定=可以隔離設定["agy"]
        ),
    )
    圖檔 = [p for p in tmp_path.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
    assert 圖檔, f"全開權限下圖沒進工作目錄：{答.終局.value}／{答.文字[:300]}"
    assert 圖檔[0].stat().st_size > 1000, f"檔案小得不像圖：{圖檔[0].stat().st_size} 位元組"
