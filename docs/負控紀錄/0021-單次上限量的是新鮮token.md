# 單次上限量的是「上下文多大」還是「燒了多少」

## 現場

`_單次上限腦` 比的量對三家不是同一個東西：codex 的 `input_tokens` **含**
`cached_input_tokens`（`non_cached_input = input − cached`，
codex-rs/protocol/src/protocol.rs），claude 的 `input_tokens` **不含**快取
（Anthropic：`total_input = cache_read + cache_creation + input`）。於是同一條
上限對 codex 量的是「上下文多大」、對 claude 量的是「燒了多少」。

實測 21 筆被標 `single_token_exceeded` 的呼叫全是 codex，cache_read 佔 input
90%～98%，扣掉快取之後的新鮮量只有 154,360～684,765——**沒有一筆碰到 2,000,000**。
快取讀取按 0.1× 計價、而且跟「這次呼叫做了多少工」無關：30 回合每回合重讀 70k
上下文就是 2.1M cache_read，真正的工只有 output 那兩萬。

兩個新增的保證各配一把刀：語意對齊做在解析器（不是各處自己扣）、新鮮量的公式
只有一份（快取讀取不算、快取建立要算）。登記在
`tests/負控/登記們/單次上限量新鮮token.py`。

## 固定負控

| 破壞什麼 | 預期 | 實際 |
|---|---|---|
| `契約/模型回應.py` 的 `用量.新鮮token` 加回 `+ (self.快取讀取token or 0)` | `test_單次上限量新鮮token.py::test_快取讀取三百萬不算燒錢_不准收手` 要紅 | 紅：`nova.載體.命令列._單次超標: 單次呼叫花費 3050000 token，超過單次上限 2000000`（同檔另兩支照樣綠——刀砍到的正是快取讀取那一邊） |
| `載體/模型/解析.py` 的 codex `輸入token` 改回 `int(用了.get("input_tokens", 0))`（不扣 `cached_input_tokens`） | `test_模型解析.py::Testcodex::test_輸入token是非快取輸入_三家在解析器對齊` 要紅 | 紅：`assert 17972 == 6964`，`用量(輸入token=17972, …, 快取讀取token=11008)`——17,972 裡有 11,008 是快取 |
| `載體/模型/接力.py` 的 `_加總用量` 把每一顆的 `快取建立token` 抹成 `None`（＝退回「任一 `None` 就整體 `None`」） | `test_接力腦.py::Test快取建立要跟著新鮮量走::test_混合接力的快取建立不准整條丟掉` 要紅 | 紅：`聚合後只剩 2380——換腦把 claude 那顆的快取建立吃掉了`（逐顆合計 19,048） |

三把刀砍的都是**公式**而不是欄位：欄位留著、名字留著，只是把量法換回原本那個。
「欄位存在」最容易假綠——`新鮮token` 這個屬性照樣讀得到、`快取讀取token` 照樣
有值，但值一換回去，護欄擋的就從「燒了多少」變回「上下文多大」，
而上面兩支測試當場紅。

刀跑完一律還原（`cp` 備份再覆蓋回去），`git diff --numstat -- src/nova` 逐檔比對，
確認實作一個字都沒留下。

## 紅證據（測試員這一階，實作尚未存在）

```
FAILED tests/單元/test_單次上限量新鮮token.py::test_快取建立兩百一十萬要算新鮮_必須收手
FAILED tests/單元/test_模型解析.py::Testcodex::test_成功
FAILED tests/單元/test_模型解析.py::Testcodex::test_輸入token是非快取輸入_三家在解析器對齊
FAILED tests/整合/test_單次token護欄.py::Test上限比的是新鮮token不是上下文大小::test_快取撐大的呼叫不收護欄
```

審查退回之後補的第三支（實作那一階要修 `_加總用量`）：

```
FAILED tests/單元/test_接力腦.py::Test快取建立要跟著新鮮量走::test_混合接力的快取建立不准整條丟掉
AssertionError: 聚合後只剩 2380——換腦把 claude 那顆的快取建立吃掉了
assert 2380 == 19048
```

整合那一支的紅是
`guardrail：單次呼叫花費 3000050 token，達到單次上限 2000000`——
3M 裡有 2.95M 是快取讀取，新鮮量只有 50,050，卻被收了 4。
