"""把祕密從要落盤的文字裡蓋掉。

**方向跟成本那一層相反。** 成本是「不確定就不給數字」（低報比沒有更危險）；
遮罩是「不確定就遮掉」（漏遮比多遮危險得多）。多遮的代價是除錯時少看到幾個字，
漏遮的代價是永久外洩——GitHub 的快取與別人的 clone 收不回來。

**它永遠不會完整。** 沒有任何規則表抓得到所有祕密，所以 `遮掉幾處` 是誠實欄位：
看帳的人要知道自己看到的是不是完整的原文。宣稱「遮乾淨了」比不遮更危險。

## 兩種規則，精準度差很多

1. **環境變數的值**（精準度最高）：nova 知道自己的環境，任何從 `os.environ`
   來的祕密值，不管長得像不像已知 token，出現在文字裡就遮。**它抓得到
   沒有任何特徵的祕密**——那是規則表永遠做不到的。
2. **已知特徵**：只收有明確固定前綴或結構的。來源是 2026-08-30 派 agy 查的
   業界規則庫（gitleaks 的 `gitleaks.toml`、trufflehog 的 `pkg/detectors`）。
   不收「任何 32 位十六進位」那種——那會把雜湊、UUID、commit sha 全部吃掉。
"""

import os
import re
from collections.abc import Mapping

from nova.契約.遮罩 import 已經遮過了, 遮罩結果
from nova.載體.秘密 import 已載入的鍵環境變數

#: 環境變數的鍵長這樣才當它是祕密。純長度判斷會把 `PWD` 跟 `LANG` 也遮掉，
#: 那會讓整份紀錄變成馬賽克。
_祕密的鍵 = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|COOKIE)", re.IGNORECASE)

#: 比這短的環境變數值不遮——短字串會在正常文字裡到處撞到。
#:
#: **主要的閘是鍵名不是長度**（`PWD`、`LANG` 過不了鍵名那關），長度只是防
#: 「值是 `3` 這種東西」的第二道網。所以門檻壓低：本來設 12，
#: 一個 11 個字的中文通關密語就漏掉了——而**漏遮比多遮危險得多**。
_最短的祕密 = 8

#: 這些值就算鍵名看起來像祕密也不遮：它們是佔位符或明顯的假值。
_不是祕密的值 = frozenset({"", "none", "null", "false", "true", "changeme", "xxx", "test"})


def _標記(是什麼: str) -> str:
    return f"[遮罩:{是什麼}]"


#: token 的邊界。**不准用 `\b`。**
#:
#: Python 的 `\w` 把中文也算成單字字元，所以 `\bAKIA…\b` 在
#: 「我讀到AKIAIOSFODNN7EXAMPLE這串」（祕密緊貼中文、沒有空格）**完全不會命中**
#: ——而這在一個中文專案裡是常態。實測：有空格 True、貼中文 False。
#: 改成「前後不是 ASCII token 字元」就對了：中文貼著也照遮，
#: 但不會在更長的英數字串中間亂咬。
#: 由 `test_祕密緊貼中文也要遮掉` 背書。
_前 = r"(?<![A-Za-z0-9_-])"
_後 = r"(?![A-Za-z0-9_-])"

#: （名稱, 樣式）。名稱會出現在遮罩標記裡，所以看得出被遮掉的是哪一種。
#: **順序有意義**：私鑰整塊要在別的規則之前，不然裡面的內容會先被切碎。
_規則: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private-key",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z0-9 ]*PRIVATE KEY-----"
        ),
    ),
    ("aws", re.compile(_前 + r"(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}" + _後)),
    ("github", re.compile(_前 + r"github_pat_[A-Za-z0-9]{22}_[A-Za-z0-9]{59}" + _後)),
    ("github", re.compile(_前 + r"gh[posur]_[A-Za-z0-9]{36,255}" + _後)),
    ("anthropic", re.compile(_前 + r"sk-ant-(?:api[0-9]{2}-)?[A-Za-z0-9_-]{40,200}" + _後)),
    ("openai", re.compile(_前 + r"sk-(?:proj|admin|svcacct)-[A-Za-z0-9_-]{20,200}" + _後)),
    ("openai", re.compile(_前 + r"sk-[a-zA-Z0-9]{48}" + _後)),
    ("google", re.compile(_前 + r"AIza[0-9A-Za-z_-]{35}" + _後)),
    ("slack", re.compile(_前 + r"xox[baprs]-[0-9A-Za-z-]{10,}" + _後)),
    ("slack", re.compile(_前 + r"xapp-[0-9]{1,2}-[A-Za-z0-9]+-[0-9]+-[a-zA-Z0-9]+" + _後)),
    ("stripe", re.compile(_前 + r"[rs]k_(?:live|test)_[0-9a-zA-Z]{24,99}" + _後)),
    (
        "gitlab",
        re.compile(_前 + r"gl(?:pat|ptt|dt|rt|oas|soat|agent|cdo)-[0-9a-zA-Z_-]{20,64}" + _後),
    ),
    ("npm", re.compile(_前 + r"npm_[A-Za-z0-9]{36}" + _後)),
    ("pypi", re.compile(_前 + r"pypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{20,}" + _後)),
    ("huggingface", re.compile(_前 + r"hf_[a-zA-Z0-9]{34,40}" + _後)),
    ("sendgrid", re.compile(_前 + r"SG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43}" + _後)),
    ("shopify", re.compile(_前 + r"shp(?:at|ca|pa|ss)_[a-fA-F0-9]{32}" + _後)),
    # JWT 的誤判風險是三者裡第二高的（公開的 OIDC token 也長這樣），
    # 但漏遮的代價比多遮大，所以照遮。要放寬得先有真的被誤遮的案例。
    (
        "jwt",
        re.compile(_前 + r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ),
)

#: 網址裡的帳密。**只遮密碼那一段**——主機名要留著，
#: 不然看不出是哪台機器出的事，而那正是要查的東西。
_網址帳密 = re.compile(r"(?P<前>[a-zA-Z][a-zA-Z0-9+.-]*://[^:/\s@]+:)(?P<密>[^@/\s]+)(?P<後>@)")

#: 網址裡長這樣的密碼是範本不是祕密。`${...}` 與 `{{...}}` 都算。
_是佔位符 = re.compile(r"^(\$\{.*\}|\{\{.*\}\}|\$[A-Za-z_][A-Za-z0-9_]*|<.*>)$")


def 遮罩(文字: str, *, 環境: Mapping[str, str] | None = None) -> 遮罩結果:
    """遮掉文字裡的祕密。回傳遮完的文字與遮掉幾處。

    `環境` 不給就用 `os.environ`。**測試一律明講**，
    不然「本機有某個環境變數所以會過、CI 沒有所以會紅」。
    """
    if not 文字:
        return 遮罩結果(已經遮過了(文字, 因為="空字串沒有東西可以遮"), 0)

    出 = 文字
    次數 = 0

    # 環境變數先做：它精準度最高，而且遮掉之後就不會再被特徵規則切成兩半。
    for 值, 鍵 in _值得遮的環境值(os.environ if 環境 is None else 環境):
        撞到 = 出.count(值)
        if 撞到:
            出 = 出.replace(值, _標記(f"env:{鍵}"))
            次數 += 撞到

    for 名, 樣式 in _規則:
        出, 幾 = 樣式.subn(_標記(名), 出)
        次數 += 幾

    出, 幾 = _網址帳密.subn(_遮掉密碼那段, 出)
    次數 += 幾

    # **這裡就是那個唯一的來源。** `遮罩結果` 的文字型別是 `已遮罩文字`，
    # 而造得出它的只有這一行與 `已經遮過了`——其餘地方硬轉由
    # `test_不准在遮罩以外的地方硬轉` 擋著。
    return 遮罩結果(已經遮過了(出, 因為="這一行剛把祕密遮完"), 次數)


def _遮掉密碼那段(命中: re.Match[str]) -> str:
    """只換掉密碼。佔位符原樣留著——`${DB_PASS}` 是範本不是祕密。"""
    密碼 = 命中.group("密")
    if _是佔位符.match(密碼):
        return 命中.group(0)
    return f"{命中.group('前')}{_標記('url-password')}{命中.group('後')}"


def _值得遮的環境值(環境: Mapping[str, str]) -> list[tuple[str, str]]:
    """挑出該遮的環境變數。**長的排前面。**

    長的先遮是因為短值可能是長值的子字串：先遮短的會把長的切成兩半，
    留下沒被遮到的尾巴。

    兩種來源：

    1. **鍵名看起來是祕密**（`KEY`／`TOKEN`／`SECRET`…）——這是**猜**的，
       猜得中一般情況，猜不中 `MY_THING=sk-...`。
    2. **nova 自己從祕密檔載進去的**（`NOVA_LOADED_SECRETS` 上的名單）——
       這個**不必猜**，是不是祕密在載入的當下就知道了。

    值太短的一律不遮（兩種來源都是）：`A=1` 遮下去會把帳本裡每一個 `1` 都吃掉。

    **名單本身要排除掉。** `NOVA_LOADED_SECRETS` 這個名字撞得上 `_祕密的鍵`
    的 `SECRET`，不排除的話它的值（一串鍵名）也會被遮，
    遮出來的東西還會巢狀套進其他標記裡。鍵名不是祕密。
    """
    自己載的 = {名 for 名 in 環境.get(已載入的鍵環境變數, "").split(",") if 名}
    收 = [
        (值, 鍵)
        for 鍵, 值 in 環境.items()
        if 鍵 != 已載入的鍵環境變數
        and (鍵 in 自己載的 or _祕密的鍵.search(鍵))
        and len(值) >= _最短的祕密
        and 值.strip().lower() not in _不是祕密的值
    ]
    return sorted(收, key=lambda 對: len(對[0]), reverse=True)
