> **這是外部套件的觀察筆記，不是 nova 的設計決定。** 讀法見 [README](README.md)。
>
> - 產出者：codex `gpt-5.6-sol`（思考深度 max），由 `nova 問` 派出，
>   工作目錄是官方 marketplace 抄過來的副本（只抄 workflow 腳本與 agent 定義）
> - 日期：2026-08-30
> - 問法：使用者說「graph 去參考完官方 workflow 一共有幾種用法，然後有幾種 agent，
>   怎麼調度使用」——盤點題不是設計題，要的是數字與出處
> - 範圍：7 支 workflow 腳本、34 份 agent 定義、1 份 advanced-workflows 參考文件。
>   全文 659 處 `檔案:行號` 出處（293 個不重複），模型自己回頭驗過每一個行號都存在。**版本會變**，這是 2026-08-30 那份快取的樣子。
> - 第四題（對照 nova）那一段模型看不到 nova 的原始碼，
>   所以它把 nova 現況一律標成「查不到」、推論一律標成「推測」——那是對的做法。

# 一、workflow 一共有幾種「用法」？

## 盤點範圍

本題的 workflow 母體是 **7 支**腳本；逐檔清單如下（每一項均以該檔第一行作為檔案存在與內容起點的出處）：`plugins/claude-security/workflows/scan.js:1`、`plugins/code-modernization/workflows/extract-rules.js:1`、`plugins/code-modernization/workflows/harden-scan.js:1`、`plugins/code-modernization/workflows/portfolio-assess.js:1`、`plugins/code-modernization/workflows/reimagine-scaffold.js:1`、`plugins/code-modernization/workflows/uplift-deltas.js:1`、`plugins/code-modernization/workflows/uplift-migrate.js:1`。

1. `plugins/claude-security/workflows/scan.js:1`
2. `plugins/code-modernization/workflows/extract-rules.js:1`
3. `plugins/code-modernization/workflows/harden-scan.js:1`
4. `plugins/code-modernization/workflows/portfolio-assess.js:1`
5. `plugins/code-modernization/workflows/reimagine-scaffold.js:1`
6. `plugins/code-modernization/workflows/uplift-deltas.js:1`
7. `plugins/code-modernization/workflows/uplift-migrate.js:1`

## 分類結論：5 種可組合的執行形狀

這 7 支腳本共出現 **5 種可組合的執行形狀**；這裡數的是控制流形狀，不把「固定 N／資料 N／預算 N」另算成形狀，而在下一節把 N 的來源逐段列清楚。五種形狀的代表控制點分別在 `plugins/code-modernization/workflows/reimagine-scaffold.js:61`、`plugins/claude-security/workflows/scan.js:1`、`plugins/code-modernization/workflows/extract-rules.js:192`、`plugins/code-modernization/workflows/uplift-migrate.js:275`、`plugins/code-modernization/workflows/harden-scan.js:138`。

計數口徑再限定兩點：單獨 `await agent(...)` 是 N=1 的退化單階扇出，不另立第六種（實例是 DTO tail：`plugins/code-modernization/workflows/extract-rules.js:343`）；「固定／資料／預算」是 fan-out cardinality 的來源軸，不是另一個同步形狀（固定 5、資料 N、budget stop 的代表分別在 `plugins/code-modernization/workflows/harden-scan.js:97`、`plugins/code-modernization/workflows/harden-scan.js:161`、`plugins/code-modernization/workflows/extract-rules.js:193`）。

| # | 形狀 | 判準 | 實例與出處 |
|---|---|---|---|
| 1 | 單階扇出＋屏障 | 先建立一組 task，以 `await parallel(...)` 等整組完成，之後才彙整或進下一階。 | scaffold 的 `parallel` 後才算 skipped：`plugins/code-modernization/workflows/reimagine-scaffold.js:61`、`plugins/code-modernization/workflows/reimagine-scaffold.js:88`；harden 的 Find／Verify 也是兩個分開的 `await parallel`：`plugins/code-modernization/workflows/harden-scan.js:106`、`plugins/code-modernization/workflows/harden-scan.js:161`。 |
| 2 | 跨項目管線 | 同一項目完成前階即可進自己的後階，不等其他項目越過全域階段屏障。 | security scan 明說「modeling each component, then dispatching its researchers as soon as its model lands」，並以二階 `pipeline` 實作；原檔是單行：`plugins/claude-security/workflows/scan.js:1`。 |
| 3 | 收斂／回饋迴圈 | 後一輪是否再跑由前一輪的新資料量或驗證結果決定；有明確停止條件。 | extract 以 `dryRounds < 2 && round < maxRounds` 迴圈，零 fresh 才累加 dry round，有 fresh 就歸零：`plugins/code-modernization/workflows/extract-rules.js:190`、`plugins/code-modernization/workflows/extract-rules.js:192`、`plugins/code-modernization/workflows/extract-rules.js:240`、`plugins/code-modernization/workflows/extract-rules.js:244`。 |
| 4 | 依賴波次／批次迴圈 | 只有依賴已成功的項目可進本批；本批有屏障，結果決定下一批 eligibility、回饋與是否斷路。它是「跑完 DAG 或中止」，不是模型判定收斂。 | eligibility、batch slice、整批 `parallel`、斷路器分別在 `plugins/code-modernization/workflows/uplift-migrate.js:275`、`plugins/code-modernization/workflows/uplift-migrate.js:280`、`plugins/code-modernization/workflows/uplift-migrate.js:287`、`plugins/code-modernization/workflows/uplift-migrate.js:301`、`plugins/code-modernization/workflows/uplift-migrate.js:350`。 |
| 5 | 對抗式複核／投票 | 原結論交給刻意找反例的獨立 reviewer；若同一結論同時送給多名 reviewer，程式以回傳票數決定。 | security scan 對每候選固定 3 票且至少 2 票 TRUE_POSITIVE 才留；max 還可重投與 red-team：`plugins/claude-security/workflows/scan.js:1`。extract 對每個 P0 排兩個不同 lens：`plugins/code-modernization/workflows/extract-rules.js:287`、`plugins/code-modernization/workflows/extract-rules.js:291`、`plugins/code-modernization/workflows/extract-rules.js:295`。harden 先以 refuter 複核每項，再對 Critical／High 加一名獨立 confirmer：`plugins/code-modernization/workflows/harden-scan.js:138`、`plugins/code-modernization/workflows/harden-scan.js:184`。 |

`portfolio-assess` 雖使用 `pipeline(...)`，但只傳一個 stage function，因此沒有可觀察的「項目跨多階段前進」；執行形狀等同單階資料扇出，待所有 row 回來後才計算 failed 與 COCOMO：`plugins/code-modernization/workflows/portfolio-assess.js:63`、`plugins/code-modernization/workflows/portfolio-assess.js:84`、`plugins/code-modernization/workflows/portfolio-assess.js:96`。

## 7 支腳本逐支執行圖

### 1. `modernize-portfolio-assess`

```text
systems（N = systems.length）
  ├─ system 1 ── pipeline 的唯一 stage：survey agent ── row 1
  ├─ system 2 ── pipeline 的唯一 stage：survey agent ── row 2
  └─ system N ── pipeline 的唯一 stage：survey agent ── row N
                          │
                    [等 rows 回傳]
                          ▼
         filter null／列 unmeasured → 程式算 COCOMO → sort → return
```

圖據：`plugins/code-modernization/workflows/portfolio-assess.js:63`、`plugins/code-modernization/workflows/portfolio-assess.js:81`、`plugins/code-modernization/workflows/portfolio-assess.js:84`、`plugins/code-modernization/workflows/portfolio-assess.js:96`、`plugins/code-modernization/workflows/portfolio-assess.js:103`。

扇出 N 完全由輸入 `systems` 的資料長度決定；腳本只要求非空陣列，**沒有數值上限**：`plugins/code-modernization/workflows/portfolio-assess.js:16`、`plugins/code-modernization/workflows/portfolio-assess.js:18`、`plugins/code-modernization/workflows/portfolio-assess.js:63`。單一 agent 回傳 null 不會丟掉整批；腳本 filter 掉 null，將找不到 row 的 system 放進 `unmeasured`：`plugins/code-modernization/workflows/portfolio-assess.js:81`、`plugins/code-modernization/workflows/portfolio-assess.js:84`、`plugins/code-modernization/workflows/portfolio-assess.js:85`、`plugins/code-modernization/workflows/portfolio-assess.js:103`。

### 2. `modernize-reimagine-scaffold`

```text
approved services（N = services.length）
  ├─ scaffold service 1 ─┐
  ├─ scaffold service 2 ─┼─ parallel ── [整組屏障] ── filter null
  └─ scaffold service N ─┘                            └─ totals／notScaffolded
```

圖據：`plugins/code-modernization/workflows/reimagine-scaffold.js:59`、`plugins/code-modernization/workflows/reimagine-scaffold.js:61`、`plugins/code-modernization/workflows/reimagine-scaffold.js:88`、`plugins/code-modernization/workflows/reimagine-scaffold.js:94`。

扇出 N 由核准後的 `services` 資料長度決定；腳本明說「no cap」，只由 runtime 依其 concurrency limit 排隊，來源沒有給該 runtime limit 的數字：`plugins/code-modernization/workflows/reimagine-scaffold.js:4`、`plugins/code-modernization/workflows/reimagine-scaffold.js:59`、`plugins/code-modernization/workflows/reimagine-scaffold.js:61`。失敗／跳過的 null 被 filter，並列入 `notScaffolded`，不拖垮彙整：`plugins/code-modernization/workflows/reimagine-scaffold.js:88`、`plugins/code-modernization/workflows/reimagine-scaffold.js:89`、`plugins/code-modernization/workflows/reimagine-scaffold.js:94`。

### 3. `modernize-harden-scan`

```text
5 個固定 vulnerability classes
  └─ parallel finder × 5
          │ [屏障]
          ▼
      flatten + 以 source::CWE 去重
          │
          └─ parallel refuter × 每個 deduped finding（資料 N）
                  │ [屏障]
                  ▼
             real? ─ no → refuted
               │yes
               ▼
             survivors
               └─ Critical/High only：parallel confirmer × 每項（資料 N）
                           │ [屏障]
                           ▼
                    disagree → 保留但降為 Medium，交人工 triage
                    agree    → 保留／只允許向下校準 severity
```

圖據：`plugins/code-modernization/workflows/harden-scan.js:97`、`plugins/code-modernization/workflows/harden-scan.js:106`、`plugins/code-modernization/workflows/harden-scan.js:129`、`plugins/code-modernization/workflows/harden-scan.js:161`、`plugins/code-modernization/workflows/harden-scan.js:171`、`plugins/code-modernization/workflows/harden-scan.js:184`、`plugins/code-modernization/workflows/harden-scan.js:186`、`plugins/code-modernization/workflows/harden-scan.js:195`。

第一階 N 寫死為 **5** 個 class：`plugins/code-modernization/workflows/harden-scan.js:97`、`plugins/code-modernization/workflows/harden-scan.js:104`、`plugins/code-modernization/workflows/harden-scan.js:106`。第二階 N 是去重後 finding 數，第三階 N 是 surviving Critical／High 數；兩者都由資料決定且腳本沒有數值 cap：`plugins/code-modernization/workflows/harden-scan.js:129`、`plugins/code-modernization/workflows/harden-scan.js:135`、`plugins/code-modernization/workflows/harden-scan.js:161`、`plugins/code-modernization/workflows/harden-scan.js:184`、`plugins/code-modernization/workflows/harden-scan.js:186`。

這是條件式對抗複核，不是多數決：第一名 refuter 回 `real:false` 就刪除；對已通過且為 Critical／High 的項目，第二名 confirmer 若反對，程式**不刪除**而是降為 Medium 並標註 human triage：`plugins/code-modernization/workflows/harden-scan.js:171`、`plugins/code-modernization/workflows/harden-scan.js:176`、`plugins/code-modernization/workflows/harden-scan.js:178`、`plugins/code-modernization/workflows/harden-scan.js:195`、`plugins/code-modernization/workflows/harden-scan.js:198`、`plugins/code-modernization/workflows/harden-scan.js:201`。

### 4. `modernize-extract-rules`

```text
round = 0, dryRounds = 0, maxRounds = clamp(input/default 4, 1..8)
  │
  ├─ while dryRounds < 2 AND round < maxRounds
  │    ├─ 若 total budget 存在且 remaining < 60,000 tokens → break
  │    ├─ parallel extractor × 3 固定 lenses
  │    │          │ [屏障]
  │    │          ▼
  │    ├─ dedup → fresh
  │    ├─ fresh = 0 → dryRounds++ ───────────────┐
  │    └─ fresh > 0 → dryRounds = 0             │
  │          └─ parallel referee × fresh rules  │
  │                    │ [屏障]                 │
  │                    └─ confirm/reject ───────┘
  │
  ├─ parallel P0 panel ×（P0 rules × 2 lenses）→ [屏障] → 程式計票
  └─ single DTO agent → return
```

圖據：`plugins/code-modernization/workflows/extract-rules.js:165`、`plugins/code-modernization/workflows/extract-rules.js:192`、`plugins/code-modernization/workflows/extract-rules.js:204`、`plugins/code-modernization/workflows/extract-rules.js:240`、`plugins/code-modernization/workflows/extract-rules.js:247`、`plugins/code-modernization/workflows/extract-rules.js:287`、`plugins/code-modernization/workflows/extract-rules.js:295`、`plugins/code-modernization/workflows/extract-rules.js:341`。

收斂條件是 **連續 2 輪沒有 fresh rule**；有 fresh rule 就把 dry counter 歸零：`plugins/code-modernization/workflows/extract-rules.js:190`、`plugins/code-modernization/workflows/extract-rules.js:192`、`plugins/code-modernization/workflows/extract-rules.js:240`、`plugins/code-modernization/workflows/extract-rules.js:244`。硬上限是 `maxRounds` 預設 **4**、最小 **1**、最大 **8**；另有預算停止條件 `budget.total && budget.remaining() < 60000`：`plugins/code-modernization/workflows/extract-rules.js:32`、`plugins/code-modernization/workflows/extract-rules.js:33`、`plugins/code-modernization/workflows/extract-rules.js:193`、`plugins/code-modernization/workflows/extract-rules.js:195`。

每輪 extractor N 固定 **3**（calculations、validations、lifecycle）；referee N 由該輪 fresh rule 數決定且無項目 cap；P0 panel 的排程 N 是 P0 rule 數乘 **2**：`plugins/code-modernization/workflows/extract-rules.js:166`、`plugins/code-modernization/workflows/extract-rules.js:182`、`plugins/code-modernization/workflows/extract-rules.js:204`、`plugins/code-modernization/workflows/extract-rules.js:247`、`plugins/code-modernization/workflows/extract-rules.js:291`、`plugins/code-modernization/workflows/extract-rules.js:297`。

P0 的「票數」不是 2 票多數決：程式收集實際有回傳的 verdict，`vs.length > 0` 且**所有已回傳票**的 `p0Justified` 都為 true 才維持 P0；faithful 也用同一個 all-returned-true 規則。因此排程 2 人，但若只回 1 張贊成票，仍會通過；0 張才不通過：`plugins/code-modernization/workflows/extract-rules.js:320`、`plugins/code-modernization/workflows/extract-rules.js:322`、`plugins/code-modernization/workflows/extract-rules.js:327`、`plugins/code-modernization/workflows/extract-rules.js:330`、`plugins/code-modernization/workflows/extract-rules.js:331`。

### 5. `modernize-uplift-deltas`

```text
4 個固定 delta categories
  └─ parallel finder × 4
          │ [屏障]
          ▼
      flatten + 以 source_site::name 去重
          │
          └─ parallel referee × 每個 deduped delta（資料 N）
                    │ [屏障]
                    ▼
          confirmed／wrong-site corrected／dropped → deterministic stats
```

圖據：`plugins/code-modernization/workflows/uplift-deltas.js:91`、`plugins/code-modernization/workflows/uplift-deltas.js:115`、`plugins/code-modernization/workflows/uplift-deltas.js:136`、`plugins/code-modernization/workflows/uplift-deltas.js:144`、`plugins/code-modernization/workflows/uplift-deltas.js:153`、`plugins/code-modernization/workflows/uplift-deltas.js:156`、`plugins/code-modernization/workflows/uplift-deltas.js:177`。

第一階 N 寫死為 **4** 個 category；第二階 N 是 deduped delta 數，沒有腳本內數值 cap：`plugins/code-modernization/workflows/uplift-deltas.js:91`、`plugins/code-modernization/workflows/uplift-deltas.js:113`、`plugins/code-modernization/workflows/uplift-deltas.js:115`、`plugins/code-modernization/workflows/uplift-deltas.js:144`、`plugins/code-modernization/workflows/uplift-deltas.js:150`、`plugins/code-modernization/workflows/uplift-deltas.js:156`。每項只有 finder 加一名 referee，沒有把同一 delta 同時送給多名 verifier，因此不是票決型 panel：`plugins/code-modernization/workflows/uplift-deltas.js:153`、`plugins/code-modernization/workflows/uplift-deltas.js:157`。

### 6. `modernize-uplift-migrate`

```text
units + deps → 驗證路徑互斥、驗證 DAG 無 cycle
  │
  └─ while remaining && !aborted
       ├─ eligible = deps 全部已 built（或是 fan-out 外部 dep）
       ├─ 本批 N = min(16, FIRST_BATCH × [1, 2, 4, 4, ...])
       ├─ parallel migrator × 本批 N
       │          │ [本批屏障]
       │          ▼
       ├─ null → 明確合成 built:false 結果
       ├─ 收集 playbookGaps → 傳給下一批 prompt
       └─ measurable build rate
             ├─ 0 人能 build → circuit break
             ├─ < 2/3 built → circuit break
             └─ ≥ 2/3 → 下一批
  │
  └─ 分成 built／failed／blocked／remaining，回傳可重送清單
```

圖據：`plugins/code-modernization/workflows/uplift-migrate.js:120`、`plugins/code-modernization/workflows/uplift-migrate.js:139`、`plugins/code-modernization/workflows/uplift-migrate.js:260`、`plugins/code-modernization/workflows/uplift-migrate.js:275`、`plugins/code-modernization/workflows/uplift-migrate.js:280`、`plugins/code-modernization/workflows/uplift-migrate.js:301`、`plugins/code-modernization/workflows/uplift-migrate.js:314`、`plugins/code-modernization/workflows/uplift-migrate.js:337`、`plugins/code-modernization/workflows/uplift-migrate.js:350`、`plugins/code-modernization/workflows/uplift-migrate.js:400`。

這個迴圈的 N 同時由輸入、資料與 cap 決定：`FIRST_BATCH` 由 caller 的 `batchSize` 決定，預設 **4**，但 clamp 到 `MAX_BATCH = 16`；後續倍率依批次為 1、2、4，最後仍以 **16** 封頂：`plugins/code-modernization/workflows/uplift-migrate.js:137`、`plugins/code-modernization/workflows/uplift-migrate.js:141`、`plugins/code-modernization/workflows/uplift-migrate.js:284`、`plugins/code-modernization/workflows/uplift-migrate.js:287`。實際 batch 還只取當時 eligible 的前 N 項，因此也受依賴圖與剩餘資料量決定：`plugins/code-modernization/workflows/uplift-migrate.js:280`、`plugins/code-modernization/workflows/uplift-migrate.js:281`、`plugins/code-modernization/workflows/uplift-migrate.js:287`。

它沒有「語意收斂」條件；正常終點是 remaining 清空，另可因沒有 eligible、整批無可量測 build，或本批可量測 build rate 低於 2/3 而停：`plugins/code-modernization/workflows/uplift-migrate.js:275`、`plugins/code-modernization/workflows/uplift-migrate.js:282`、`plugins/code-modernization/workflows/uplift-migrate.js:350`、`plugins/code-modernization/workflows/uplift-migrate.js:354`。批間狀態不是隱含對話記憶：`knownGaps` 由上一批結果彙入，最多取 6,000 字放進下一批 prompt：`plugins/code-modernization/workflows/uplift-migrate.js:266`、`plugins/code-modernization/workflows/uplift-migrate.js:291`、`plugins/code-modernization/workflows/uplift-migrate.js:297`、`plugins/code-modernization/workflows/uplift-migrate.js:333`。

### 7. `claude-security scan`

```text
args／effort／diff-size／scope-size gate
  │
  ├─ empty diff/scope → 直接回空結果
  ├─ low 或 medium-small → 1 個 whole-target component，跳過 inventory/threat model
  └─ 其他 → inventory agent（失敗可 retry；不完整可再提交一次）
                 │
                 └─ components（normal cap 12；high/max cap 24；失敗 fallback 1）

每個 component 自己走二階 pipeline（不同 component 間沒有全域 phase barrier）：
  component i ── threat-model i ── parallel category researchers i ── item done
       component i 一拿到 model 就進 research，不等所有 model
                              │
                   [所有 component pipeline 完成]
                              ▼
                 parallel sweep 0..3 → [屏障]
                              ▼
        candidates → severity/confidence sort → raw cap 400 → dedup
                              ▼
                    verification cap 45
                              │
每個 candidate 自己走 pipeline：
  ┌─ parallel 3 voters（REACHABILITY／IMPACT／DEFENSES）─ [項目內屏障]
  │       └─ exactly 3 returned AND TRUE_POSITIVE ≥ 2 才 kept
  └─ max effort 且 kept：
          ├─ 若首輪恰 2/3：再 parallel 3 voters；完整且 <2 票才推翻
          └─ 若仍 kept：single red-team refuter；FALSE_POSITIVE 才推翻
```

圖據（原檔壓成單行）：`plugins/claude-security/workflows/scan.js:1`。

以上所有 `scan.js` 數字與分支均在壓成一行的原檔：effort gate、small diff（≤5 files 且 ≤300 lines）、small scope（≤5 files）、component cap 12／24、raw candidate cap 400、verification cap 45、3-voter 規則、max repanel 與 red-team 都在 `plugins/claude-security/workflows/scan.js:1`。

完整形狀的 component 數是 inventory 資料決定、normal 最多 **12**、high/max 最多 **24**；每 component 的研究格有 4 類，但純 managed language 會剪掉 memory 類剩 3 類；normal 每格 1 人、high/max 每格 2 人。low 或 medium-small 則壓成 1 component × 1 位全類別 researcher。這些 gate、category 陣列、managed-language pruning 與 multiplicity 均在 `plugins/claude-security/workflows/scan.js:1`。

sweep N 是 tier／focus 決定：collapsed/low 為 0，normal 為 1，high/max 為 2；attack-surface focus 且非 range 時另加 1 個 secrets sweep，所以最大 **3**。panel N 是資料（去重後 candidate）決定但最多 **45 項 × 3 人 = 135 位 logical voters**；max effort 的 repanel 最多再 135 人，red-team 最多再 45 人：`plugins/claude-security/workflows/scan.js:1`。

首輪計票是嚴格的 `voters === 3 && true >= 2`，少任何一票即丟棄；max 的 repanel 若少票則沿用首輪、若完整而 true < 2 才丟棄；red-team 無回票也沿用前判，只有回 `FALSE_POSITIVE` 才丟棄：`plugins/claude-security/workflows/scan.js:1`。

## 扇出 N 的總表

| workflow／段落 | N 的來源 | 腳本內上限 | 出處 |
|---|---|---:|---|
| portfolio survey | 資料：`systems.length` | 查不到（無 cap） | `plugins/code-modernization/workflows/portfolio-assess.js:16`、`plugins/code-modernization/workflows/portfolio-assess.js:63` |
| scaffold | 資料：`services.length` | 查不到；原文是 no cap，runtime 排隊 | `plugins/code-modernization/workflows/reimagine-scaffold.js:4`、`plugins/code-modernization/workflows/reimagine-scaffold.js:59` |
| harden Find | 寫死 5 classes | 5 | `plugins/code-modernization/workflows/harden-scan.js:97`、`plugins/code-modernization/workflows/harden-scan.js:106` |
| harden Verify／Confirm | 資料：deduped findings／Critical+High survivors | 查不到 | `plugins/code-modernization/workflows/harden-scan.js:161`、`plugins/code-modernization/workflows/harden-scan.js:184`、`plugins/code-modernization/workflows/harden-scan.js:186` |
| extract 每輪 Extract | 寫死 3 lenses | 每輪 3 | `plugins/code-modernization/workflows/extract-rules.js:166`、`plugins/code-modernization/workflows/extract-rules.js:204` |
| extract Verify／P0 | 資料：fresh；資料 × 寫死 2 lenses | 單輪項目數查不到；round 最多 8，且 remaining budget <60,000 時停 | `plugins/code-modernization/workflows/extract-rules.js:33`、`plugins/code-modernization/workflows/extract-rules.js:193`、`plugins/code-modernization/workflows/extract-rules.js:247`、`plugins/code-modernization/workflows/extract-rules.js:291`、`plugins/code-modernization/workflows/extract-rules.js:295` |
| uplift-deltas Find | 寫死 4 categories | 4 | `plugins/code-modernization/workflows/uplift-deltas.js:92`、`plugins/code-modernization/workflows/uplift-deltas.js:115` |
| uplift-deltas Verify | 資料：deduped deltas | 查不到 | `plugins/code-modernization/workflows/uplift-deltas.js:150`、`plugins/code-modernization/workflows/uplift-deltas.js:156` |
| uplift-migrate 每批 | caller `batchSize`／預設 4，再受 eligible 資料量限制 | 16 | `plugins/code-modernization/workflows/uplift-migrate.js:139`、`plugins/code-modernization/workflows/uplift-migrate.js:141`、`plugins/code-modernization/workflows/uplift-migrate.js:281`、`plugins/code-modernization/workflows/uplift-migrate.js:286` |
| security component | inventory 資料；effort tier 決定 cap | normal 12；high/max 24 | `plugins/claude-security/workflows/scan.js:1` |
| security research cell | category（3/4）× effort redundancy（1/2）；low/small 改成每 component 1 | 完整形狀每 component 最多 8 | `plugins/claude-security/workflows/scan.js:1` |
| security sweep | effort／focus | 3 | `plugins/claude-security/workflows/scan.js:1` |
| security panel | 資料：deduped candidates；每項固定 3 票 | 45 candidates、135 首輪 voters | `plugins/claude-security/workflows/scan.js:1` |

在「由預算決定」這一欄，材料中只有兩種明文機制：security scan 的 caller-provided `effort` tier 改變 component cap 與每格 researcher 數；extract 則不改單輪 3 人，而是在剩餘 token budget 低於 60,000 時停止新增 round：`plugins/claude-security/workflows/scan.js:1`、`plugins/code-modernization/workflows/extract-rules.js:193`。

# 二、agent 一共有幾種？

## 精確口徑

材料是 **34 份 agent 定義**。原始碼沒有共同的 `type` 或 `kind` 欄位可供再分官方語意上的「agent 類型」；按最外層格式是 **2 類**：**31 份有 YAML-style frontmatter**，另 **3 份是純 Markdown prompt、完全沒有 frontmatter**。後三份都直接從 H1 開始：`plugins/skill-creator/skills/skill-creator/agents/analyzer.md:1`、`plugins/skill-creator/skills/skill-creator/agents/comparator.md:1`、`plugins/skill-creator/skills/skill-creator/agents/grader.md:1`。若把「種類」定義成**欄位 presence signature（不計欄位順序）**，則精確是 **7 種**；逐種如下，逐檔明細再見下一張母表。

欄位統計採**文字盤點口徑**：只數檔首 `---` 區段中未縮排的 `key:`；不把「某個 strict YAML parser 是否接受整段」混入欄位出現次數。例示的 frontmatter 邊界可見 `plugins/claude-security/agents/claude-security.md:1`、`plugins/claude-security/agents/claude-security.md:9`，而長單行 description 仍按行首欄位計數的例子是 `plugins/pr-review-toolkit/agents/silent-failure-hunter.md:1`、`plugins/pr-review-toolkit/agents/silent-failure-hunter.md:6`。

| 欄位 presence signature | 份數 | 成員與出處 |
|---|---:|---|
| 無 frontmatter | 3 | `plugins/skill-creator/skills/skill-creator/agents/analyzer.md:1`、`plugins/skill-creator/skills/skill-creator/agents/comparator.md:1`、`plugins/skill-creator/skills/skill-creator/agents/grader.md:1` |
| `name, description, model` | 4 | `plugins/agent-sdk-dev/agents/agent-sdk-verifier-py.md:2`、`plugins/agent-sdk-dev/agents/agent-sdk-verifier-ts.md:2`、`plugins/code-simplifier/agents/code-simplifier.md:2`、`plugins/pr-review-toolkit/agents/code-simplifier.md:2` |
| `name, description, model, effort, color, tools, initialPrompt` | 1 | `plugins/claude-security/agents/claude-security.md:2`、`plugins/claude-security/agents/claude-security.md:8` |
| `name, description, model, effort, color, tools` | 6 | `plugins/claude-security/agents/explore.md:2`、`plugins/claude-security/agents/patch-generator.md:2`、`plugins/claude-security/agents/patch-verifier.md:2`、`plugins/claude-security/agents/scan-inventory.md:2`、`plugins/claude-security/agents/scan-researcher.md:2`、`plugins/claude-security/agents/scan-verifier.md:2` |
| `name, description, tools` | 8 | `plugins/code-modernization/agents/architecture-critic.md:2`、`plugins/code-modernization/agents/business-rules-extractor.md:2`、`plugins/code-modernization/agents/legacy-analyst.md:2`、`plugins/code-modernization/agents/scaffolder.md:2`、`plugins/code-modernization/agents/security-auditor.md:2`、`plugins/code-modernization/agents/test-engineer.md:2`、`plugins/code-modernization/agents/uplift-migrator.md:2`、`plugins/code-modernization/agents/version-delta-analyst.md:2` |
| `name, description, model, color, tools` | 7 | `plugins/feature-dev/agents/code-architect.md:2`、`plugins/feature-dev/agents/code-explorer.md:2`、`plugins/feature-dev/agents/code-reviewer.md:2`、`plugins/hookify/agents/conversation-analyzer.md:2`、`plugins/plugin-dev/agents/agent-creator.md:2`、`plugins/plugin-dev/agents/plugin-validator.md:2`、`plugins/plugin-dev/agents/skill-reviewer.md:2` |
| `name, description, model, color` | 5 | `plugins/pr-review-toolkit/agents/code-reviewer.md:2`、`plugins/pr-review-toolkit/agents/comment-analyzer.md:2`、`plugins/pr-review-toolkit/agents/pr-test-analyzer.md:2`、`plugins/pr-review-toolkit/agents/silent-failure-hunter.md:2`、`plugins/pr-review-toolkit/agents/type-design-analyzer.md:2` |

## 34 份逐檔欄位母表

`D` 代表 `description`；`T1`～`T12` 是下一小節列出的完整 `tools` 取值，不是省略未統計的欄位；兩欄的原始寫法可見 `plugins/claude-security/agents/claude-security.md:3`、`plugins/claude-security/agents/claude-security.md:7`。

| # | 定義 | frontmatter 欄位／值 | 出處 |
|---:|---|---|---|
| 1 | `agent-sdk-verifier-py` | `name, D, model=sonnet` | `plugins/agent-sdk-dev/agents/agent-sdk-verifier-py.md:2`、`plugins/agent-sdk-dev/agents/agent-sdk-verifier-py.md:4` |
| 2 | `agent-sdk-verifier-ts` | `name, D, model=sonnet` | `plugins/agent-sdk-dev/agents/agent-sdk-verifier-ts.md:2`、`plugins/agent-sdk-dev/agents/agent-sdk-verifier-ts.md:4` |
| 3 | `claude-security` | `name, D, model=opus, effort=xhigh, color=purple, tools=T7, initialPrompt="/claude-security:claude-security"` | `plugins/claude-security/agents/claude-security.md:2`、`plugins/claude-security/agents/claude-security.md:8` |
| 4 | `explore` | `name, D, model=sonnet, effort=xhigh, color=cyan, tools=T1` | `plugins/claude-security/agents/explore.md:2`、`plugins/claude-security/agents/explore.md:7` |
| 5 | `patch-generator` | `name, D, model=inherit, effort=xhigh, color=green, tools=T6` | `plugins/claude-security/agents/patch-generator.md:2`、`plugins/claude-security/agents/patch-generator.md:7` |
| 6 | `patch-verifier` | `name, D, model=inherit, effort=xhigh, color=blue, tools=T3` | `plugins/claude-security/agents/patch-verifier.md:2`、`plugins/claude-security/agents/patch-verifier.md:7` |
| 7 | `scan-inventory` | `name, D, model=sonnet, effort=medium, color=green, tools=T5` | `plugins/claude-security/agents/scan-inventory.md:2`、`plugins/claude-security/agents/scan-inventory.md:7` |
| 8 | `scan-researcher` | `name, D, model=inherit, effort=xhigh, color=red, tools=T3` | `plugins/claude-security/agents/scan-researcher.md:2`、`plugins/claude-security/agents/scan-researcher.md:7` |
| 9 | `scan-verifier` | `name, D, model=inherit, effort=xhigh, color=orange, tools=T3` | `plugins/claude-security/agents/scan-verifier.md:2`、`plugins/claude-security/agents/scan-verifier.md:7` |
| 10 | `architecture-critic` | `name, D, tools=T1` | `plugins/code-modernization/agents/architecture-critic.md:2`、`plugins/code-modernization/agents/architecture-critic.md:4` |
| 11 | `business-rules-extractor` | `name, D, tools=T1` | `plugins/code-modernization/agents/business-rules-extractor.md:2`、`plugins/code-modernization/agents/business-rules-extractor.md:4` |
| 12 | `legacy-analyst` | `name, D, tools=T1` | `plugins/code-modernization/agents/legacy-analyst.md:2`、`plugins/code-modernization/agents/legacy-analyst.md:4` |
| 13 | `scaffolder` | `name, D, tools=T4` | `plugins/code-modernization/agents/scaffolder.md:2`、`plugins/code-modernization/agents/scaffolder.md:4` |
| 14 | `security-auditor` | `name, D, tools=T1` | `plugins/code-modernization/agents/security-auditor.md:2`、`plugins/code-modernization/agents/security-auditor.md:4` |
| 15 | `test-engineer` | `name, D, tools=T8` | `plugins/code-modernization/agents/test-engineer.md:2`、`plugins/code-modernization/agents/test-engineer.md:4` |
| 16 | `uplift-migrator` | `name, D, tools=T4` | `plugins/code-modernization/agents/uplift-migrator.md:2`、`plugins/code-modernization/agents/uplift-migrator.md:4` |
| 17 | `version-delta-analyst` | `name, D, tools=T1` | `plugins/code-modernization/agents/version-delta-analyst.md:2`、`plugins/code-modernization/agents/version-delta-analyst.md:4` |
| 18 | `code-simplifier`（code-simplifier plugin） | `name, D, model=opus` | `plugins/code-simplifier/agents/code-simplifier.md:2`、`plugins/code-simplifier/agents/code-simplifier.md:4` |
| 19 | `code-architect` | `name, D, tools=T2, model=sonnet, color=green` | `plugins/feature-dev/agents/code-architect.md:2`、`plugins/feature-dev/agents/code-architect.md:6` |
| 20 | `code-explorer` | `name, D, tools=T2, model=sonnet, color=yellow` | `plugins/feature-dev/agents/code-explorer.md:2`、`plugins/feature-dev/agents/code-explorer.md:6` |
| 21 | `code-reviewer`（feature-dev） | `name, D, tools=T2, model=sonnet, color=red` | `plugins/feature-dev/agents/code-reviewer.md:2`、`plugins/feature-dev/agents/code-reviewer.md:6` |
| 22 | `conversation-analyzer` | `name, D, model=inherit, color=yellow, tools=T11` | `plugins/hookify/agents/conversation-analyzer.md:2`、`plugins/hookify/agents/conversation-analyzer.md:6` |
| 23 | `agent-creator` | `name, D, model=sonnet, color=magenta, tools=T12` | `plugins/plugin-dev/agents/agent-creator.md:2`、`plugins/plugin-dev/agents/agent-creator.md:34` |
| 24 | `plugin-validator` | `name, D, model=inherit, color=yellow, tools=T9` | `plugins/plugin-dev/agents/plugin-validator.md:2`、`plugins/plugin-dev/agents/plugin-validator.md:36` |
| 25 | `skill-reviewer` | `name, D, model=inherit, color=cyan, tools=T10` | `plugins/plugin-dev/agents/skill-reviewer.md:2`、`plugins/plugin-dev/agents/skill-reviewer.md:35` |
| 26 | `code-reviewer`（pr-review-toolkit） | `name, D, model=opus, color=green` | `plugins/pr-review-toolkit/agents/code-reviewer.md:2`、`plugins/pr-review-toolkit/agents/code-reviewer.md:5` |
| 27 | `code-simplifier`（pr-review-toolkit） | `name, D, model=opus` | `plugins/pr-review-toolkit/agents/code-simplifier.md:2`、`plugins/pr-review-toolkit/agents/code-simplifier.md:40` |
| 28 | `comment-analyzer` | `name, D, model=inherit, color=green` | `plugins/pr-review-toolkit/agents/comment-analyzer.md:2`、`plugins/pr-review-toolkit/agents/comment-analyzer.md:5` |
| 29 | `pr-test-analyzer` | `name, D, model=inherit, color=cyan` | `plugins/pr-review-toolkit/agents/pr-test-analyzer.md:2`、`plugins/pr-review-toolkit/agents/pr-test-analyzer.md:5` |
| 30 | `silent-failure-hunter` | `name, D, model=inherit, color=yellow` | `plugins/pr-review-toolkit/agents/silent-failure-hunter.md:2`、`plugins/pr-review-toolkit/agents/silent-failure-hunter.md:5` |
| 31 | `type-design-analyzer` | `name, D, model=inherit, color=pink` | `plugins/pr-review-toolkit/agents/type-design-analyzer.md:2`、`plugins/pr-review-toolkit/agents/type-design-analyzer.md:5` |
| 32 | Post-hoc Analyzer | 無 frontmatter | `plugins/skill-creator/skills/skill-creator/agents/analyzer.md:1` |
| 33 | Blind Comparator | 無 frontmatter | `plugins/skill-creator/skills/skill-creator/agents/comparator.md:1` |
| 34 | Grader | 無 frontmatter | `plugins/skill-creator/skills/skill-creator/agents/grader.md:1` |

## 欄位出現次數與取值分布

逐檔母表只出現 **7 個欄位**，分布如下；沒有列出的欄位在這 34 份材料中就是 0 次。七欄全集可在唯一全欄位定義的 `plugins/claude-security/agents/claude-security.md:2`、`plugins/claude-security/agents/claude-security.md:3`、`plugins/claude-security/agents/claude-security.md:4`、`plugins/claude-security/agents/claude-security.md:5`、`plugins/claude-security/agents/claude-security.md:6`、`plugins/claude-security/agents/claude-security.md:7`、`plugins/claude-security/agents/claude-security.md:8` 核對；全體 absence／presence 則見上方 34 列母表。

| 欄位 | 出現（缺省） | 取值分布 | 出處 |
|---|---:|---|---|
| `name` | 31（3） | 29 個 distinct 值；`code-reviewer` 2 次、`code-simplifier` 2 次，其餘 27 個名字各 1 次 | 兩個 `code-reviewer`：`plugins/feature-dev/agents/code-reviewer.md:2`、`plugins/pr-review-toolkit/agents/code-reviewer.md:2`；兩個 `code-simplifier`：`plugins/code-simplifier/agents/code-simplifier.md:2`、`plugins/pr-review-toolkit/agents/code-simplifier.md:2`；全體見上方逐檔母表。 |
| `description` | 31（3） | 31 個自由文字值，各不相同 | 每份 frontmatter 的 `description` 位置均在上方逐檔母表所引範圍內；三份無 frontmatter 的出處是 `plugins/skill-creator/skills/skill-creator/agents/analyzer.md:1`、`plugins/skill-creator/skills/skill-creator/agents/comparator.md:1`、`plugins/skill-creator/skills/skill-creator/agents/grader.md:1`。 |
| `model` | 23（11） | `inherit` 11、`sonnet` 8、`opus` 4 | 各檔值見上方逐檔母表；三種實例分別為 `plugins/claude-security/agents/patch-generator.md:4`、`plugins/agent-sdk-dev/agents/agent-sdk-verifier-py.md:4`、`plugins/claude-security/agents/claude-security.md:4`。 |
| `effort` | 7（27） | `xhigh` 6、`medium` 1 | 7 份全在 claude-security：`plugins/claude-security/agents/claude-security.md:5`、`plugins/claude-security/agents/explore.md:5`、`plugins/claude-security/agents/patch-generator.md:5`、`plugins/claude-security/agents/patch-verifier.md:5`、`plugins/claude-security/agents/scan-inventory.md:5`、`plugins/claude-security/agents/scan-researcher.md:5`、`plugins/claude-security/agents/scan-verifier.md:5`。 |
| `color` | 19（15） | green 5、yellow 4、cyan 3、red 2、blue 1、magenta 1、orange 1、pink 1、purple 1 | 19 個逐檔值見上方母表；各 singleton 的直接出處：`plugins/claude-security/agents/patch-verifier.md:6`、`plugins/plugin-dev/agents/agent-creator.md:33`、`plugins/claude-security/agents/scan-verifier.md:6`、`plugins/pr-review-toolkit/agents/type-design-analyzer.md:5`、`plugins/claude-security/agents/claude-security.md:6`。 |
| `tools` | 22（12） | 共 12 種完整取值組合；見下一表 | 22 個逐檔值及行號見下一表。 |
| `initialPrompt` | 1（33） | `"/claude-security:claude-security"` 1 | `plugins/claude-security/agents/claude-security.md:8` |

`tools` 的 12 種完整取值組合如下；順序保留原檔，`Agent(...)` 也保留為一個帶參數的 tool declaration。最寬組合與 agent-as-tool 語法見 `plugins/claude-security/agents/claude-security.md:7`，最窄的兩-tool 組合見 `plugins/hookify/agents/conversation-analyzer.md:6`、`plugins/plugin-dev/agents/agent-creator.md:34`；12 種的完整逐值出處在緊接的表內。

| ID | 次數 | `tools` 原值 | 出處 |
|---|---:|---|---|
| T1 | 6 | `Read, Glob, Grep, Bash` | `plugins/claude-security/agents/explore.md:7`、`plugins/code-modernization/agents/architecture-critic.md:4`、`plugins/code-modernization/agents/business-rules-extractor.md:4`、`plugins/code-modernization/agents/legacy-analyst.md:4`、`plugins/code-modernization/agents/security-auditor.md:4`、`plugins/code-modernization/agents/version-delta-analyst.md:4` |
| T2 | 3 | `Glob, Grep, LS, Read, NotebookRead, WebFetch, TodoWrite, WebSearch, KillShell, BashOutput` | `plugins/feature-dev/agents/code-architect.md:4`、`plugins/feature-dev/agents/code-explorer.md:4`、`plugins/feature-dev/agents/code-reviewer.md:4` |
| T3 | 3 | `Read, Glob, Grep, Bash, Agent(claude-security:explore)` | `plugins/claude-security/agents/patch-verifier.md:7`、`plugins/claude-security/agents/scan-researcher.md:7`、`plugins/claude-security/agents/scan-verifier.md:7` |
| T4 | 2 | `Read, Glob, Grep, Write, Edit, Bash` | `plugins/code-modernization/agents/scaffolder.md:4`、`plugins/code-modernization/agents/uplift-migrator.md:4` |
| T5 | 1 | `Read, Glob, Grep` | `plugins/claude-security/agents/scan-inventory.md:7` |
| T6 | 1 | `Read, Glob, Grep, Bash, Edit, Write, Agent(claude-security:explore)` | `plugins/claude-security/agents/patch-generator.md:7` |
| T7 | 1 | `Read, Glob, Grep, Bash, Write, Edit, AskUserQuestion, Workflow, Workflow(claude-security:scan), TaskCreate, TaskGet, TaskList, TaskUpdate, TaskOutput, TaskStop, Agent(claude-security:scan-inventory, claude-security:scan-researcher, claude-security:scan-verifier, claude-security:patch-generator, claude-security:patch-verifier, claude-security:explore)` | `plugins/claude-security/agents/claude-security.md:7` |
| T8 | 1 | `Read, Write, Edit, Glob, Grep, Bash` | `plugins/code-modernization/agents/test-engineer.md:4` |
| T9 | 1 | `["Read", "Grep", "Glob", "Bash"]` | `plugins/plugin-dev/agents/plugin-validator.md:36` |
| T10 | 1 | `["Read", "Grep", "Glob"]` | `plugins/plugin-dev/agents/skill-reviewer.md:35` |
| T11 | 1 | `["Read", "Grep"]` | `plugins/hookify/agents/conversation-analyzer.md:6` |
| T12 | 1 | `["Write", "Read"]` | `plugins/plugin-dev/agents/agent-creator.md:34` |

## agent 被另一個 agent 當工具呼叫

直接的 agent-to-agent 邊只寫在 frontmatter 的 **`tools` 欄位**，語法是 `Agent(plugin:agent, ...)`：`plugins/claude-security/agents/claude-security.md:7`、`plugins/claude-security/agents/patch-generator.md:7`、`plugins/claude-security/agents/patch-verifier.md:7`、`plugins/claude-security/agents/scan-researcher.md:7`、`plugins/claude-security/agents/scan-verifier.md:7`。

| 被呼叫的 agent | 不重複上游 agent 數 | 上游 | 出處 |
|---|---:|---|---|
| `claude-security:explore` | **5** | `claude-security`、`patch-generator`、`patch-verifier`、`scan-researcher`、`scan-verifier` | `plugins/claude-security/agents/claude-security.md:7`、`plugins/claude-security/agents/patch-generator.md:7`、`plugins/claude-security/agents/patch-verifier.md:7`、`plugins/claude-security/agents/scan-researcher.md:7`、`plugins/claude-security/agents/scan-verifier.md:7` |
| `claude-security:scan-inventory` | 1 | `claude-security` | `plugins/claude-security/agents/claude-security.md:7` |
| `claude-security:scan-researcher` | 1 | `claude-security` | `plugins/claude-security/agents/claude-security.md:7` |
| `claude-security:scan-verifier` | 1 | `claude-security` | `plugins/claude-security/agents/claude-security.md:7` |
| `claude-security:patch-generator` | 1 | `claude-security` | `plugins/claude-security/agents/claude-security.md:7` |
| `claude-security:patch-verifier` | 1 | `claude-security` | `plugins/claude-security/agents/claude-security.md:7` |

所以，以「被不同 agent 的 `tools` 欄位共用」為口徑，最被共用的是 **`claude-security:explore`，5 個不同上游**；其他 5 個被當 agent tool 暴露的定義都只有 1 個上游：`plugins/claude-security/agents/claude-security.md:7`、`plugins/claude-security/agents/patch-generator.md:7`、`plugins/claude-security/agents/patch-verifier.md:7`、`plugins/claude-security/agents/scan-researcher.md:7`、`plugins/claude-security/agents/scan-verifier.md:7`。

若把「上游」改成 7 支 workflow 的 `agentType`（這不是 agent-to-agent `tools` 邊），最被不同 workflow 共用的是 `code-modernization:legacy-analyst`，共 **2 支**：portfolio survey 一支、extract-rules 的 Verify／DTO 一支：`plugins/code-modernization/workflows/portfolio-assess.js:76`、`plugins/code-modernization/workflows/extract-rules.js:261`、`plugins/code-modernization/workflows/extract-rules.js:348`。其餘 workflow `agentType` 都只出現在各自一支 workflow：`plugins/code-modernization/workflows/reimagine-scaffold.js:79`、`plugins/code-modernization/workflows/harden-scan.js:113`、`plugins/code-modernization/workflows/extract-rules.js:215`、`plugins/code-modernization/workflows/uplift-deltas.js:127`、`plugins/code-modernization/workflows/uplift-migrate.js:304`、`plugins/claude-security/workflows/scan.js:1`。

## 明說「不准單獨叫」的 agent

明文包含 **`not for direct invocation`** 的正好 **5 份**，而且原句都在 `description` 欄位：`plugins/claude-security/agents/scan-inventory.md:3`、`plugins/claude-security/agents/scan-researcher.md:3`、`plugins/claude-security/agents/scan-verifier.md:3`、`plugins/claude-security/agents/patch-generator.md:3`、`plugins/claude-security/agents/patch-verifier.md:3`。

1. `scan-inventory` 原句：「Restricted read-only repository cartographer dispatched by the Claude Security scan workflow to partition the tree into components and account for every top-level directory; **not for direct invocation or vulnerability research.**」`plugins/claude-security/agents/scan-inventory.md:3`
2. `scan-researcher` 原句：「Restricted read-only vulnerability researcher dispatched by the Claude Security scan workflow; **not for direct invocation or general exploration.**」`plugins/claude-security/agents/scan-researcher.md:3`
3. `scan-verifier` 原句：「Restricted read-only verifier dispatched by the Claude Security scan workflow to vote on one candidate finding; **not for direct invocation.**」`plugins/claude-security/agents/scan-verifier.md:3`
4. `patch-generator` 原句：「Implements the fix for one finding inside a scratch workspace clone, staged for review and delivery as a patch file; **dispatched by the fix job, not for direct invocation.**」`plugins/claude-security/agents/patch-generator.md:3`
5. `patch-verifier` 原句：「The single verifier per fix round — reviews the workspace's staged diff against the finding, runs the tests, and states the three confidence claims a patch file must earn; **dispatched by the fix job, not for direct invocation.**」`plugins/claude-security/agents/patch-verifier.md:3`

`uplift-migrator` 的限制是「Use only AFTER a pilot unit has been migrated and its playbook written」，它限制前置時機，沒有寫「不得直接呼叫」，因此不計入上述 5 份：`plugins/code-modernization/agents/uplift-migrator.md:3`。

# 三、調度是怎麼做的？

## 誰決定下一步：分界在 `agent(..., { schema })` 的回傳邊界

```text
caller／human 提供 args、核准點
            │
            ▼
JS workflow：驗參數、切 N、排 parallel/pipeline、設 cap
            │
            ├── agent(prompt, { agentType, schema })
            │          │
            │          └── 模型讀程式／產生有欄位的結果
            │
            ▼
JS workflow：filter／dedup／if／while／票數／sort／公式／circuit breaker
            │
            └── 確定下一個 agent 集合或 return
```

**腳本決定控制流。** `parallel`／`pipeline` 的位置、迴圈條件、slice cap、票數與斷路器全是 JS；例如 extract 的 while 與 dry counter 在程式中判定，uplift-migrate 的 eligibility 與 2/3 breaker 也由算式判定：`plugins/code-modernization/workflows/extract-rules.js:190`、`plugins/code-modernization/workflows/extract-rules.js:192`、`plugins/code-modernization/workflows/extract-rules.js:240`、`plugins/code-modernization/workflows/uplift-migrate.js:275`、`plugins/code-modernization/workflows/uplift-migrate.js:280`、`plugins/code-modernization/workflows/uplift-migrate.js:354`。

**模型決定資料內容。** 每個 `agent(...)` 讀 prompt 後回傳 components、findings、rules、verdict 或 build status；腳本再用這些欄位走既定分支。harden 的模型回 `real`，但 survivor／refuted／demotion 是 JS；migrate 的模型回 `buildRan`、`built`，但腳本把 `built` clamp 成 `r.built && r.buildRan`：`plugins/code-modernization/workflows/harden-scan.js:83`、`plugins/code-modernization/workflows/harden-scan.js:171`、`plugins/code-modernization/workflows/harden-scan.js:195`、`plugins/code-modernization/workflows/uplift-migrate.js:149`、`plugins/code-modernization/workflows/uplift-migrate.js:308`、`plugins/code-modernization/workflows/uplift-migrate.js:310`。

因此模型可以**間接改變下一步的資料 N**（例如多報一條 fresh rule 就多排一名 referee），但不能自行改掉 `maxRounds ≤ 8`、batch `≤ 16`、panel 2-of-3 等程式條件：`plugins/code-modernization/workflows/extract-rules.js:33`、`plugins/code-modernization/workflows/extract-rules.js:247`、`plugins/code-modernization/workflows/uplift-migrate.js:139`、`plugins/code-modernization/workflows/uplift-migrate.js:286`、`plugins/claude-security/workflows/scan.js:1`。

caller／human 的分界在 invocation 外：scaffold 只在架構已由 human 核准後接收 approved services；uplift-migrate 只在 pilot 已做且 human 核准 fan-out 後接收 units：`plugins/code-modernization/workflows/reimagine-scaffold.js:4`、`plugins/code-modernization/workflows/reimagine-scaffold.js:6`、`plugins/code-modernization/workflows/uplift-migrate.js:5`、`plugins/code-modernization/workflows/uplift-migrate.js:6`。

## 分支失敗會不會拖垮整階？

就腳本有明寫的 **null／falsy（skipped、died、errored）回傳路徑**而言，答案是通常**不會**：各腳本在屏障後 filter、continue、標成未完成，或 retry；代表控制點在 `plugins/code-modernization/workflows/portfolio-assess.js:84`、`plugins/code-modernization/workflows/extract-rules.js:272`、`plugins/code-modernization/workflows/uplift-migrate.js:314`、`plugins/claude-security/workflows/scan.js:1`。各支的精確語意如下。

| workflow | 單一分支無結果時 | 是否仍繼續／結果如何記 | 出處 |
|---|---|---|---|
| portfolio | `.then` 將 falsy 轉 null | 繼續；filter 掉並列入 `unmeasured` | `plugins/code-modernization/workflows/portfolio-assess.js:81`、`plugins/code-modernization/workflows/portfolio-assess.js:84`、`plugins/code-modernization/workflows/portfolio-assess.js:85`、`plugins/code-modernization/workflows/portfolio-assess.js:103` |
| scaffold | 結果 falsy | 繼續；列入 `notScaffolded` | `plugins/code-modernization/workflows/reimagine-scaffold.js:88`、`plugins/code-modernization/workflows/reimagine-scaffold.js:91`、`plugins/code-modernization/workflows/reimagine-scaffold.js:94` |
| harden | finder falsy 被 filter；refuter falsy `continue`；confirmer falsy `continue` | 整批繼續；finder 無結果不產候選，refuter 無結果的候選不進 survivor/refuted，confirmer 無結果則不改原 survivor | `plugins/code-modernization/workflows/harden-scan.js:123`、`plugins/code-modernization/workflows/harden-scan.js:127`、`plugins/code-modernization/workflows/harden-scan.js:173`、`plugins/code-modernization/workflows/harden-scan.js:175`、`plugins/code-modernization/workflows/harden-scan.js:195`、`plugins/code-modernization/workflows/harden-scan.js:197` |
| extract | extractor falsy 被 filter；referee falsy明文「drop this rule rather than crash」；P0 null vote 跳過；DTO 可為 null | 整批／後續繼續；未驗 rule 不冒充 confirmed；DTO fallback `[]` | `plugins/code-modernization/workflows/extract-rules.js:224`、`plugins/code-modernization/workflows/extract-rules.js:270`、`plugins/code-modernization/workflows/extract-rules.js:272`、`plugins/code-modernization/workflows/extract-rules.js:321`、`plugins/code-modernization/workflows/extract-rules.js:322`、`plugins/code-modernization/workflows/extract-rules.js:363` |
| uplift-deltas | finder falsy 被 filter；referee falsy `continue` | 整批繼續；無 referee 結果的 delta 不進 confirmed，也不進 dropped | `plugins/code-modernization/workflows/uplift-deltas.js:138`、`plugins/code-modernization/workflows/uplift-deltas.js:179`、`plugins/code-modernization/workflows/uplift-deltas.js:181`、`plugins/code-modernization/workflows/uplift-deltas.js:206` |
| uplift-migrate | agent null | 立即合成 `buildRan:false, built:false` 的 per-unit failure，單位不遺失；可能令「整批 0 個可量測 build」斷路，但已完成結果仍回傳 | `plugins/code-modernization/workflows/uplift-migrate.js:314`、`plugins/code-modernization/workflows/uplift-migrate.js:318`、`plugins/code-modernization/workflows/uplift-migrate.js:330`、`plugins/code-modernization/workflows/uplift-migrate.js:350`、`plugins/code-modernization/workflows/uplift-migrate.js:400` |
| security scan | 每個 logical agent call 先執行一次，falsy 時最多 retry 4 次；research 缺回傳只記 coverage，首輪 panel 缺任何票則丟棄該 finding，max adversarial exception 則沿用首輪 | 局部繼續；不是一個分支直接拖垮全階 | retry 陣列、filter、缺票規則與 adversarial `catch` 都在單行原檔：`plugins/claude-security/workflows/scan.js:1` |

相反地，**輸入／安全驗證失敗是整支 workflow 的 `throw new Error`**，不是局部分支失敗；六支 modernization workflow 都在 fan-out 前 fail fast，security scan 缺 `scanRoot`／`runDir` 也 throw：`plugins/code-modernization/workflows/portfolio-assess.js:18`、`plugins/code-modernization/workflows/reimagine-scaffold.js:18`、`plugins/code-modernization/workflows/harden-scan.js:20`、`plugins/code-modernization/workflows/extract-rules.js:24`、`plugins/code-modernization/workflows/uplift-deltas.js:22`、`plugins/code-modernization/workflows/uplift-migrate.js:26`、`plugins/claude-security/workflows/scan.js:1`。

`parallel`／`pipeline` runtime 對一般 JavaScript Promise rejection 是否自動轉成 null，指定材料**查不到**；可確定的只有上述腳本明寫的 falsy/null 路徑，以及 security scan 只在 max adversarial per-candidate stage 額外寫了 `try/catch`：`plugins/code-modernization/workflows/extract-rules.js:270`、`plugins/code-modernization/workflows/uplift-migrate.js:314`、`plugins/claude-security/workflows/scan.js:1`。

## 上限：併發數、總 agent 數、單次項目數

### 併發數

**runtime 的實際 concurrency 數字查不到。** 唯一明文是 runtime 會把超過 concurrency cap 的 agents 排隊，但沒有給 cap 值：`plugins/code-modernization/workflows/reimagine-scaffold.js:4`、`plugins/code-modernization/workflows/reimagine-scaffold.js:59`。`MAX_BATCH = 16` 是 uplift-migrate 單批交給 `parallel` 的 task 數上限；原註解反而說 batch 再大也不會超過 runtime 自己的 concurrency cap，所以 **16 不能當成 runtime concurrency**：`plugins/code-modernization/workflows/uplift-migrate.js:137`、`plugins/code-modernization/workflows/uplift-migrate.js:139`、`plugins/code-modernization/workflows/uplift-migrate.js:286`、`plugins/code-modernization/workflows/uplift-migrate.js:301`。

### 總 agent 數

**跨 7 支 workflow 沒有一個共同的 total-agent cap，且多支腳本在輸入／模型陣列上無 `maxItems`，所以整體沒有有限上界。** portfolio 的 `systems` 與 scaffold 的 `services` 只驗非空、沒有長度 cap；harden findings、extract rules、uplift deltas 的 schema array 也沒有 `maxItems`：`plugins/code-modernization/workflows/portfolio-assess.js:16`、`plugins/code-modernization/workflows/portfolio-assess.js:18`、`plugins/code-modernization/workflows/reimagine-scaffold.js:16`、`plugins/code-modernization/workflows/reimagine-scaffold.js:18`、`plugins/code-modernization/workflows/harden-scan.js:50`、`plugins/code-modernization/workflows/extract-rules.js:70`、`plugins/code-modernization/workflows/uplift-deltas.js:50`。

唯一可從腳本算出完整 logical-agent 上界的是 security scan。最寬的 max-effort 路徑為：inventory 最多 2 次完整性提交 + threat model 24 + research `24×4×2=192` + sweeps 3 + 首輪 panel `45×3=135` + repanel `45×3=135` + red-team 45 = **536 個 logical agent calls**；component 24、四 lens、每格兩人、3 sweep、candidate 45、每項 3 票、一次 correction 都在 `plugins/claude-security/workflows/scan.js:1`。

security scan 的 retry wrapper 是每個 logical call 初次 1 次，再按四個 delay 最多 retry 4 次，所以若把 retry 嘗試也算一次 `agent()` 呼叫，理論上界是 `536×5 = 2,680` 次 attempt：`plugins/claude-security/workflows/scan.js:1`。這是該腳本的推導上界，不是 runtime 宣告的全域 quota：同一來源 `plugins/claude-security/workflows/scan.js:1`。

其他腳本即使有 round/batch cap，也沒有有限 total-agent 上界：extract 最多 8 rounds，但每輪 fresh rules、之後的 P0 rules 都未設項目 cap；uplift-migrate 每批 16，但輸入 units 未設總長度 cap：`plugins/code-modernization/workflows/extract-rules.js:33`、`plugins/code-modernization/workflows/extract-rules.js:247`、`plugins/code-modernization/workflows/extract-rules.js:288`、`plugins/code-modernization/workflows/uplift-migrate.js:25`、`plugins/code-modernization/workflows/uplift-migrate.js:26`、`plugins/code-modernization/workflows/uplift-migrate.js:139`。

### 單次項目數／queue 寬度

腳本內明確的數值上限只有：uplift migration 每批 **16 units**；security inventory **12 components（normal）／24（high|max）**、raw candidates **400**、panel candidates **45**；extract round **8** 是輪數而非單次 parallel 寬度。這些值分別在 `plugins/code-modernization/workflows/uplift-migrate.js:139`、`plugins/code-modernization/workflows/uplift-migrate.js:286`、`plugins/claude-security/workflows/scan.js:1`、`plugins/code-modernization/workflows/extract-rules.js:33`。

另有兩個「傳入單一 prompt 的歷史清單」截斷，不是 agent queue cap：extract 只把最近 **200** 條 already-catalogued summary 傳入下一輪，DTO prompt 只帶前 **250** 個 rule name：`plugins/code-modernization/workflows/extract-rules.js:202`、`plugins/code-modernization/workflows/extract-rules.js:345`。其餘各段固定／資料 N 已在第一題的「扇出 N 總表」逐段列出並附來源。

## 證據如何跨階段流動

結論是：**外層是 schema 化的 object／array；內層仍有自由文字欄位。** 六支 modernization workflow 定義 11 個 schema contract（1+1+2+4+2+1），security scan 再有 inventory、threat-model、finding、verdict 4 個，共 **15 個 schema contract**：`plugins/code-modernization/workflows/portfolio-assess.js:42`、`plugins/code-modernization/workflows/reimagine-scaffold.js:42`、`plugins/code-modernization/workflows/harden-scan.js:46`、`plugins/code-modernization/workflows/harden-scan.js:83`、`plugins/code-modernization/workflows/extract-rules.js:66`、`plugins/code-modernization/workflows/extract-rules.js:110`、`plugins/code-modernization/workflows/extract-rules.js:128`、`plugins/code-modernization/workflows/extract-rules.js:138`、`plugins/code-modernization/workflows/uplift-deltas.js:46`、`plugins/code-modernization/workflows/uplift-deltas.js:74`、`plugins/code-modernization/workflows/uplift-migrate.js:149`、`plugins/claude-security/workflows/scan.js:1`。

每個實際 `agent(...)` call site 都把相應 contract 放在 options 的 `schema:` 欄位；例如 portfolio、harden、extract、migrate 分別在 `plugins/code-modernization/workflows/portfolio-assess.js:79`、`plugins/code-modernization/workflows/harden-scan.js:116`、`plugins/code-modernization/workflows/harden-scan.js:156`、`plugins/code-modernization/workflows/extract-rules.js:218`、`plugins/code-modernization/workflows/extract-rules.js:264`、`plugins/code-modernization/workflows/extract-rules.js:313`、`plugins/code-modernization/workflows/extract-rules.js:351`、`plugins/code-modernization/workflows/uplift-migrate.js:307`；security scan 的所有 agent options 也帶 schema：`plugins/claude-security/workflows/scan.js:1`。

schema 強制的是欄位形狀、required、type、enum、pattern；內容證據仍常是 string，例如 `source: path:line`、`reason`、`evidence`、`playbookGaps`。代表性定義在 `plugins/code-modernization/workflows/harden-scan.js:54`、`plugins/code-modernization/workflows/harden-scan.js:58`、`plugins/code-modernization/workflows/harden-scan.js:87`、`plugins/code-modernization/workflows/uplift-migrate.js:168`、`plugins/code-modernization/workflows/uplift-migrate.js:174`。

跨階段不是把整段對話上下文傳下去，而是腳本挑欄位重組 prompt。由前一個模型產生的自由文字會先包進 `<<<UNTRUSTED ... UNTRUSTED>>>` fence，且移除內嵌 fence marker；extract 的 referee 與 P0 panel、harden 的 judge、uplift-deltas 的 referee 都如此：`plugins/code-modernization/workflows/extract-rules.js:53`、`plugins/code-modernization/workflows/extract-rules.js:58`、`plugins/code-modernization/workflows/extract-rules.js:253`、`plugins/code-modernization/workflows/extract-rules.js:301`、`plugins/code-modernization/workflows/harden-scan.js:28`、`plugins/code-modernization/workflows/harden-scan.js:32`、`plugins/code-modernization/workflows/harden-scan.js:147`、`plugins/code-modernization/workflows/uplift-deltas.js:33`、`plugins/code-modernization/workflows/uplift-deltas.js:163`。

schema 之外還有程式層強制：Map dedup、enum-derived branch、filter null、重算票數，以及 `built && buildRan` clamp；這些機制分別可見於 `plugins/code-modernization/workflows/harden-scan.js:129`、`plugins/code-modernization/workflows/harden-scan.js:173`、`plugins/code-modernization/workflows/extract-rules.js:320`、`plugins/code-modernization/workflows/uplift-migrate.js:308`、`plugins/code-modernization/workflows/uplift-migrate.js:310`。

`agent()` runtime 收到 `schema` 後如何驗證、schema mismatch 是 retry、null 還是 throw，指定材料**查不到**；材料只展示 schema 被傳入的 call boundary，沒有 runtime implementation：例如 `plugins/code-modernization/workflows/portfolio-assess.js:66`、`plugins/code-modernization/workflows/portfolio-assess.js:79`、`plugins/claude-security/workflows/scan.js:1`。

## 恢復：中途停掉怎麼接

### 7 支實際 workflow

**自動 durable checkpoint／從半個 JS invocation 原地續跑：查不到。** 7 支腳本中可見的 round、`done`、`remaining`、`knownGaps` 都是 invocation 內變數；例如 uplift-migrate 在記憶體建立這四類狀態並於最後 return：`plugins/code-modernization/workflows/uplift-migrate.js:263`、`plugins/code-modernization/workflows/uplift-migrate.js:267`、`plugins/code-modernization/workflows/uplift-migrate.js:400`。extract 也只在本次 invocation 內維持 `seen`、`confirmed`、`round`：`plugins/code-modernization/workflows/extract-rules.js:184`、`plugins/code-modernization/workflows/extract-rules.js:191`、`plugins/code-modernization/workflows/extract-rules.js:358`。

security scan 有的是**單一 logical agent 的即時 retry**，不是 workflow checkpoint：四次 retry delays 與最終仍可回 falsy 都在 `plugins/claude-security/workflows/scan.js:1`。

`claude-security` orchestrator 另要求多階 job 用 task list 保存並更新 plan；但該句沒有宣告 task list 的持久性，也沒有給 interruption 後的 resume entrypoint，因此只能算 in-session 進度追蹤，不能當成已證實的恢復機制：tool 權限與原句分別在 `plugins/claude-security/agents/claude-security.md:7`、`plugins/claude-security/agents/claude-security.md:13`。

實作中唯一明確的**跨 invocation 接續協定**是 uplift-migrate：回傳 `remainingUnits`、`failedUnits`、`blockedUnits` 三份 `{name,path,deps?}` 可重送清單；caller 先把 `playbookGaps` 寫回 PLAYBOOK、處理 `sharedFileNeeds`，再以清單重呼叫：`plugins/code-modernization/workflows/uplift-migrate.js:5`、`plugins/code-modernization/workflows/uplift-migrate.js:6`、`plugins/code-modernization/workflows/uplift-migrate.js:350`、`plugins/code-modernization/workflows/uplift-migrate.js:356`、`plugins/code-modernization/workflows/uplift-migrate.js:415`、`plugins/code-modernization/workflows/uplift-migrate.js:423`。這只能接「已正常 return／被 circuit breaker 正常中止」的結果；半途程序消失而沒有 return 時如何還原 `done`／`remaining`，材料查不到：同一批狀態建立與 return 邊界見 `plugins/code-modernization/workflows/uplift-migrate.js:263`、`plugins/code-modernization/workflows/uplift-migrate.js:400`。

extract 的 maxRounds 截尾訊息允許 caller 以 `modulePattern` 或較高 `maxRounds` 再跑，但它沒有輸出可還原 `seen` map 的 checkpoint，因此是重跑／縮 scope，不是原地 resume：`plugins/code-modernization/workflows/extract-rules.js:283`、`plugins/code-modernization/workflows/extract-rules.js:284`、`plugins/code-modernization/workflows/extract-rules.js:358`。

### 官方參考文件有、但 7 支腳本未實作的 pattern

`advanced-workflows.md` 明確示範把狀態持久化到 `.claude/*-state.local.md`，並把「Persistent state across commands」與「Resume capability」列為效益：`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:64`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:81`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:122`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:126`。

同一參考文件的 recovery pattern 是讀 state file 的 started／environment／last completed，讓使用者選 resume、restart 或 abort：`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:332`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:346`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:348`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:358`；另有每階成功後寫 checkpoint log、用 last-successful-checkpoint 接回的範例：`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:579`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:590`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:600`。這是文件中的設計 pattern，不是 7 支 JS workflow 內可見的自動 runtime 功能：7 支實作中的唯一跨 invocation 清單協定仍是 `plugins/code-modernization/workflows/uplift-migrate.js:415`。

# 四、對照 nova

## 證據界線

nova 的程式碼不在指定材料內，所以「nova 現在是否已實作 schema validator、retry adapter、checkpoint store」一律**查不到**。以下只採題目明定的前提：nova 是 claude／codex／agy 三家平級 CLI 子程序、一次呼叫一個程序；凡由這個程序邊界推導的可搬性與缺件排序，均標成**推測**。可逐行引用的官方側材料則是 workflow、agent 定義與 recovery 參考，例如 `plugins/claude-security/workflows/scan.js:1`、`plugins/claude-security/agents/claude-security.md:1`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:1`。

## 哪些用法可以直接搬

此處「直接搬」指**保留同一控制語意，以 nova 外層 coordinator 啟動 CLI process**；不是把官方的 `agent()`／`parallel()` call 原封不動執行。兩種官方 call boundary 的實例在 `plugins/code-modernization/workflows/portfolio-assess.js:66`、`plugins/code-modernization/workflows/reimagine-scaffold.js:61`。

| 官方形狀 | 可搬性 | 推測：搬到多 CLI 的等價形狀 | 官方出處 |
|---|---|---|---|
| 單階固定 N／資料 N fan-out + barrier | **可直接搬** | coordinator 同時啟動 N 個 CLI，等所有 PID／result 回來後聚合；這不需要 child 彼此共享 runtime。 | scaffold 以 `parallel(services.map(...))` 後 filter：`plugins/code-modernization/workflows/reimagine-scaffold.js:61`、`plugins/code-modernization/workflows/reimagine-scaffold.js:88`；uplift-deltas 的兩階 barrier：`plugins/code-modernization/workflows/uplift-deltas.js:115`、`plugins/code-modernization/workflows/uplift-deltas.js:156`。 |
| 確定性 barrier chain／map-dedup-reduce | **可直接搬** | 每階只需把上一階已收齊的 JSON 結果交給 coordinator 去重、排序、再展開下一批；模型不必知道全域排程。 | harden 在 finder barrier 後以 Map 去重，再排 verifier：`plugins/code-modernization/workflows/harden-scan.js:122`、`plugins/code-modernization/workflows/harden-scan.js:135`、`plugins/code-modernization/workflows/harden-scan.js:161`。 |
| 固定／資料／預算 N 與 hard cap | **可直接搬** | N 的算式放 coordinator；CLI 只是單項 worker。 | round clamp／budget stop：`plugins/code-modernization/workflows/extract-rules.js:33`、`plugins/code-modernization/workflows/extract-rules.js:193`；batch cap 16：`plugins/code-modernization/workflows/uplift-migrate.js:139`、`plugins/code-modernization/workflows/uplift-migrate.js:286`。 |
| 對抗 panel 與程式計票 | **可直接搬** | 同一 candidate 分別交給三個獨立 CLI process，coordinator 只接受完整 3 票並算 2-of-3；程序獨立不妨礙票決。 | security scan 的三 lens、完整三票與 2-of-3 規則：`plugins/claude-security/workflows/scan.js:1`；extract 的雙 lens panel 與 `.every()` 計算：`plugins/code-modernization/workflows/extract-rules.js:291`、`plugins/code-modernization/workflows/extract-rules.js:320`、`plugins/code-modernization/workflows/extract-rules.js:330`。 |
| dependency-aware batches + circuit breaker | **控制形狀可直接搬** | coordinator 依 `deps` 算 eligible，單批啟動最多 16 個 CLI，收齊標準化 build 結果後算 2/3；child 無須互相通訊。 | eligibility、batch、breaker：`plugins/code-modernization/workflows/uplift-migrate.js:275`、`plugins/code-modernization/workflows/uplift-migrate.js:280`、`plugins/code-modernization/workflows/uplift-migrate.js:287`、`plugins/code-modernization/workflows/uplift-migrate.js:345`、`plugins/code-modernization/workflows/uplift-migrate.js:354`。 |
| 檔案式 durable state／resume pattern | **可直接搬** | `.local.md`／checkpoint log 本來就跨程序，不依賴 in-process object。 | state file、讀 state 決定 next action、checkpoint resume：`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:281`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:315`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:327`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:579`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:600`。 |

## 哪些不能原樣搬

| 官方機制 | 為何跨程序不能原樣搬 | 要維持語意時缺的橋（推測） | 官方出處 |
|---|---|---|---|
| 多階 `pipeline` 的 in-memory handoff | 官方 stage 2 直接收到 stage 1 的 JS object；security scan 還要求某 component 的 model 一落地就立刻排該 component 的 researchers。CLI process 沒有共享 object／closure。 | coordinator 需有 per-item state machine，將 stage result 序列化成 JSON／檔案，再啟動下一 CLI；否則只能退化成全域 barrier。 | scan 的 per-component `{component, model}` handoff 與「as soon as its model lands」都在 `plugins/claude-security/workflows/scan.js:1`。 |
| `agent(prompt,{agentType,schema})` runtime call | 官方同一 runtime 直接解析 agent type、權限與 schema；三家 CLI 沒有共同的 in-process `agent()` ABI。 | provider-neutral invocation envelope：role/prompt、cwd、tool policy、schema、timeout，再由 adapter 翻成三家 CLI flags/stdin。 | portfolio 的 call boundary：`plugins/code-modernization/workflows/portfolio-assess.js:66`、`plugins/code-modernization/workflows/portfolio-assess.js:76`、`plugins/code-modernization/workflows/portfolio-assess.js:79`；不同 agent 的 tools 權限則在例如 `plugins/claude-security/agents/scan-inventory.md:7`、`plugins/claude-security/agents/patch-generator.md:7`。 |
| agent 內再用 `Agent(...)` 當工具 | 官方 child agent 的 tool surface 可直接出現另一 agent；nova 的一次呼叫既是一個獨立 CLI process，不能假定 child 內有同一 runtime 的 Agent tool。 | child 把 nested-call request 交回 coordinator，或由 coordinator 預先展開；還要顯式傳回父 prompt 所需的結果。 | `explore` 被五個上游透過 `tools: ... Agent(claude-security:explore)` 暴露：`plugins/claude-security/agents/claude-security.md:7`、`plugins/claude-security/agents/patch-generator.md:7`、`plugins/claude-security/agents/patch-verifier.md:7`、`plugins/claude-security/agents/scan-researcher.md:7`、`plugins/claude-security/agents/scan-verifier.md:7`。 |
| schema 作為 runtime output contract | 官方把 JSON-schema-like object直接傳給每次 agent call；CLI 的 stdout、exit code與文字格式不是同一種 runtime result。 | 每家 CLI adapter 要抽出 payload，做相同 required/type/enum/pattern 驗證；invalid output 要有統一 retry／failure 規則。 | schema 與 call：`plugins/code-modernization/workflows/harden-scan.js:46`、`plugins/code-modernization/workflows/harden-scan.js:83`、`plugins/code-modernization/workflows/harden-scan.js:116`、`plugins/code-modernization/workflows/harden-scan.js:156`。 |
| falsy/null branch failure 語意 | 官方腳本把 skipped／died agent 表成 falsy/null，再 filter、continue 或合成結果；OS process 則至少有 exit code、signal、timeout、stdout parse failure，不能直接等同一個 null。 | 統一 result envelope，先把各 CLI 的成功、可重試、永久失敗、timeout、partial output 正規化，再套官方 filter／circuit semantics。 | extract 明文把 null referee 當 skipped/dead 並 drop：`plugins/code-modernization/workflows/extract-rules.js:270`、`plugins/code-modernization/workflows/extract-rules.js:272`；migrate 對 null 合成失敗：`plugins/code-modernization/workflows/uplift-migrate.js:314`、`plugins/code-modernization/workflows/uplift-migrate.js:330`。 |
| 收斂迴圈的活狀態 | extract 的 `seen Map`、`dryRounds`、`confirmed` 都在同一 JS invocation；CLI 本身跑完即退場。 | coordinator 保存 dedup keys、round、dry counter、confirmed/rejected；若要抗 coordinator crash，再寫 durable checkpoint。 | `seen`／counters／while／fresh reset：`plugins/code-modernization/workflows/extract-rules.js:184`、`plugins/code-modernization/workflows/extract-rules.js:190`、`plugins/code-modernization/workflows/extract-rules.js:192`、`plugins/code-modernization/workflows/extract-rules.js:230`、`plugins/code-modernization/workflows/extract-rules.js:244`。 |
| 批間自由文字回饋 | uplift-migrate 直接把記憶體中的 `knownGaps` fence 後插入下一批 prompt；跨 CLI 不能傳 object reference，而且程序中斷會失去未落盤的 gaps。 | coordinator 持有／持久化 gaps，做 fence、去重、6,000-char 截斷後重組下一個 CLI prompt。 | gaps state、fence/truncate、回收：`plugins/code-modernization/workflows/uplift-migrate.js:266`、`plugins/code-modernization/workflows/uplift-migrate.js:291`、`plugins/code-modernization/workflows/uplift-migrate.js:297`、`plugins/code-modernization/workflows/uplift-migrate.js:333`。 |
| runtime token budget | extract 直接讀全域 `budget.total`／`budget.remaining()`；三家獨立程序沒有天然共享同一個 budget object。 | coordinator 統計 provider usage／預算，於排下一 round 前做同一 gate。 | `plugins/code-modernization/workflows/extract-rules.js:193`、`plugins/code-modernization/workflows/extract-rules.js:195` |

所以「管線」不是不能在 nova **實作**，而是不能把官方的 in-process `pipeline(items, stage1, stage2)` **原樣搬**；若退化成「全體 stage 1 都結束才啟動 stage 2」，語意就由管線變成屏障，失去 security scan 明寫的 as-soon-as-model-lands 行為：`plugins/claude-security/workflows/scan.js:1`。

同理，收斂 loop、dependency wave、adversarial panel 的**演算法**都可留，但狀態與失敗必須由 nova coordinator 顯式擁有；官方原碼分別把狀態放在 `seen`／`remaining`／vote objects：`plugins/code-modernization/workflows/extract-rules.js:184`、`plugins/code-modernization/workflows/uplift-migrate.js:263`、`plugins/code-modernization/workflows/uplift-migrate.js:340`、`plugins/claude-security/workflows/scan.js:1`。

## 官方有而 nova 沒有：前五名

**查不到（嚴格盤點結論）：**沒有 nova 原始碼，所以不能由指定的官方材料證明 nova 目前「沒有」以下任一項；可證明的只會是官方側確有相應機制，例如 schema call 與 recovery pattern：`plugins/code-modernization/workflows/portfolio-assess.js:79`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:332`。

**推測排序（依題目給定的多 CLI 程序模型；排序標準是補上後可立即承接最多官方 workflow 語意）：**

1. **跨 provider 的 result envelope + schema validator。** 先統一 `ok/status/payload/error/usage`，再驗 required/type/enum/pattern；7 支 workflow 的所有 agent call 都依賴 schema 化結果，且下游直接讀欄位分支，所以這是其他調度語意的地基：`plugins/code-modernization/workflows/portfolio-assess.js:42`、`plugins/code-modernization/workflows/portfolio-assess.js:79`、`plugins/code-modernization/workflows/extract-rules.js:66`、`plugins/code-modernization/workflows/extract-rules.js:218`、`plugins/claude-security/workflows/scan.js:1`。
2. **coordinator-owned failure normalization + retry/backoff。** 把 exit code、signal、timeout、schema-invalid、空輸出轉成一致的 retryable／terminal 狀態，才能重現 security scan 的「初次 + 4 retries」與其他腳本的局部 null isolation：`plugins/claude-security/workflows/scan.js:1`、`plugins/code-modernization/workflows/extract-rules.js:270`、`plugins/code-modernization/workflows/extract-rules.js:272`、`plugins/code-modernization/workflows/uplift-migrate.js:314`。
3. **durable per-item checkpoint／resume manifest（官方參考 pattern；7 支 JS 尚未實作）。** CLI 程序邊界讓已完成 unit、未完成 unit、票與 gaps 都應落盤；官方參考已給 `.local.md` state、last-completed 與 checkpoint resume pattern，實際 migrate 也已給三種 re-passable unit lists：`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:281`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:332`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:348`、`plugins/plugin-dev/skills/command-development/references/advanced-workflows.md:600`、`plugins/code-modernization/workflows/uplift-migrate.js:415`、`plugins/code-modernization/workflows/uplift-migrate.js:423`。
4. **有界 scheduler：per-provider concurrency、全域 agent／token budget、queue cap。** 官方把 runtime queue、effort-dependent width、remaining-token gate與 per-batch 16 分散在不同層；nova 若集中管理即可避免三家 CLI 同時爆量，並保留原本的比例控制：`plugins/code-modernization/workflows/reimagine-scaffold.js:4`、`plugins/code-modernization/workflows/extract-rules.js:193`、`plugins/code-modernization/workflows/uplift-migrate.js:137`、`plugins/code-modernization/workflows/uplift-migrate.js:141`、`plugins/claude-security/workflows/scan.js:1`。
5. **可稽核的 adversarial vote ledger + incomplete-panel 規則。** 對同一 claim 保存 provider／lens／verdict／reason，計票由 coordinator 做而不是讓最後一個模型自由總結；security scan 已把每 finding 的 panel／adversarial rounds 與總票數放入 return，且對缺票、repanel、red-team 各有不同 fail-open／fail-closed 規則：`plugins/claude-security/workflows/scan.js:1`。extract 的雙 judge 還顯示「排程票數」與「實收票數」必須分開記：`plugins/code-modernization/workflows/extract-rules.js:295`、`plugins/code-modernization/workflows/extract-rules.js:320`、`plugins/code-modernization/workflows/extract-rules.js:330`。

`Agent(...)` nested dispatch／role registry 沒排進前五，不是因為官方沒有，而是它只出現在 claude-security 這一組 agent 定義；前五項會橫跨更多支 workflow。它的存在與 5 個 `explore` 上游仍可直接由 `plugins/claude-security/agents/claude-security.md:7`、`plugins/claude-security/agents/patch-generator.md:7`、`plugins/claude-security/agents/patch-verifier.md:7`、`plugins/claude-security/agents/scan-researcher.md:7`、`plugins/claude-security/agents/scan-verifier.md:7` 核對。
