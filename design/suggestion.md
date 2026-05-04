# Assistant Tool 修改建議 — 提升 Extension 開發可靠度

> 以下修改建議針對 SightingAssistantTool 端，目的是讓 Chrome Extension 互動開發更精確、更可靠。

---

## 高影響 / 低工作量

### 1. 移除子視窗的 `pause`（最高優先）

`sherlog_subprocess.py` 和 `displaydebugger_subprocess.py` 的 batch file 最後都有 `pause`，導致子視窗卡住等按鍵。

```python
# 改前：batch 結尾
batch_content += "pause\n"

# 改後：直接結束，不 pause
# (刪掉 pause 那行即可)
```

**效果：** 子視窗自動關閉，Extension 不需要 `_maybe_close_paused_child_windows()` 那套 hack。

---

### 2. Prompt 中加入結構化互動標記

在 `sighting_assistant.yaml` 的 prompt 裡，指示 LLM 在問使用者問題時加上可解析的標記：

```yaml
prompt: |
  ...
  When asking the user to select attachments, format your question EXACTLY like:
  
  [USER_INPUT_REQUIRED:SELECT_MULTIPLE]
  Please select attachments to analyze:
  1) SystemScopeTool_2026_03_19.zip
  2) crash_dump.dmp
  3) All of the above
  [/USER_INPUT_REQUIRED]
  
  When asking a yes/no question, format as:
  [USER_INPUT_REQUIRED:YES_NO]
  Would you like to run DisplayDebugger analysis?
  [/USER_INPUT_REQUIRED]
```

**效果：** Extension 用 regex 偵測 `[USER_INPUT_REQUIRED:SELECT_MULTIPLE]` 就能 100% 精確產生對應的按鈕 UI，不用猜。

---

### 3. 長時間工具加 progress 輸出

在 `sherlog_subprocess.py` / `displaydebugger_subprocess.py` 加入 progress print：

```python
print("[PROGRESS] Sherlog: Starting GDHM analysis for ID 3254128063...")
# ... subprocess runs ...
print("[PROGRESS] Sherlog: Analysis complete, processing results...")
```

**效果：** Extension 從 `answer` 或 stdout 看到 `[PROGRESS]` 就更新 loading 指示器，使用者不會以為死掉了。

---

## 中影響 / 中工作量

### 4. Report 輸出同時寫 JSON 結構化檔案

目前報告是純 markdown 在 `answer` chunks 裡。可以加一個步驟讓 LLM 同時寫一份結構化 JSON：

```yaml
# 在 prompt 最後加
After generating the report, also call system_write_file to save a JSON version:
{
  "hsd_id": "14027453772",
  "category": "BSOD", 
  "phase": "complete",
  "sections": { "1.1": {...}, "1.2": {...} },
  "tools_invoked": ["read_article", "attachments", ...],
  "similar_hsds": [...]
}
Save to: $GNAI_TEMP_WORKSPACE/report_structured.json
```

**效果：** Extension 可以用 JSON 做漂亮的 UI rendering（摺疊 section、工具狀態圖表等），而不是只能顯示 raw markdown。

---

### 5. 固定 Phase 宣告格式

```yaml
prompt: |
  At the start of each phase, output a phase marker:
  [PHASE:1:DATA_GATHERING]
  [PHASE:2:ATTACHMENT_ANALYSIS]  
  [PHASE:3:INTERACTIVE_GATE]
  [PHASE:4:REPORT_GENERATION]
```

**效果：** Extension 可以做進度條 UI（Phase 1/6 → 2/6 → ...）

---

## 修改影響矩陣

| 修改 | 工作量 | Extension 受益 | 風險 |
|------|--------|---------------|------|
| 移除 `pause` | 5 分鐘 | 消除子視窗問題 | 極低 |
| `[USER_INPUT_REQUIRED]` 標記 | 30 分鐘 | 精確互動 UI | 低（LLM 偶爾漏標記） |
| `[PROGRESS]` 輸出 | 20 分鐘 | 消除「假死」感 | 極低 |
| Phase 標記 | 15 分鐘 | 進度條 UI | 低 |
| JSON 報告 | 1-2 小時 | 高品質渲染 | 中（增加 token 消耗） |

---

## 結論

- **只改一件事：** 移除 `pause` — 直接消除最大的技術 hack。
- **改三件事：** `pause` + `[USER_INPUT_REQUIRED]` 標記 + `[PROGRESS]` 輸出 — 1 小時工作量，Extension 可靠度從 80% → **95%+**。

---

## 建議 6：Phase 1 拆成兩步 — 先輸出已知摘要再跑耗時 tools

> 日期：2026-04-28 | 背景：Extension 測試 HSD 14027453772 時，所有 Phase 1 tools 同時呼叫，用戶等到 Sherlog 跑完才看到第一行 answer text

### 問題

目前 `sighting_assistant.yaml` 的 Phase 1 prompt 讓 LLM 一口氣呼叫所有 tools（`read_article`、`attachments`、`similarity_search`、`rag_search`、`sherlog_sync`、`gop_analyzer` 等），然後等**全部完成**後才開始生成 answer。

其中 `sherlog_sync` 和 `displaydebugger` 是 subprocess 呼叫外部 GNAI assistant，可能需要 1-5 分鐘。用戶在這段時間只看到 "Running: Sherlog Sync" 的 spinner，沒有任何內容。

### 建議修改

在 `sighting_assistant.yaml` 的 prompt 中，將 Phase 1 拆成 **Step A（快速）** 和 **Step B（耗時）**：

```yaml
prompt: |
  ## PHASE 1 — DATA GATHERING (TWO-STEP)

  ### Step 1A — Quick Data (output immediately after these tools return)
  1. Call sighting_read_article with the HSD ID
  2. Call sighting_attachments with the HSD ID
  3. Call sighting_similarity_search with the HSD ID
  4. Call sighting_rag_search for DFD checklist and BKM

  **AFTER Step 1A tools return, IMMEDIATELY output a preliminary summary:**
  - HSD title, category, component, status
  - Attachment list (names, sizes, types)
  - Similar HSD matches (if any)
  - DFD checklist status
  
  Format: "## Preliminary Summary (detailed analysis in progress...)"

  ### Step 1B — Deep Analysis (runs after preliminary summary is shown)
  5. If GDHM IDs found → call sighting_sherlog_sync
  6. If GOP logs found → call sighting_gop_analyzer
  7. If display logs found → call sighting_displaydebugger
  
  After Step 1B tools complete, append their results to the analysis.
```

### 預期效果

| 階段 | 時間 | 用戶看到 |
|------|------|----------|
| Step 1A | ~10-20s | HSD 摘要、附件列表、相似 HSD、checklist |
| Step 1B | ~1-5min | Sherlog/DisplayDebugger/GOP 分析結果追加 |

用戶在等 Sherlog 跑的時候已經能看到 HSD 的基本資訊，大幅改善體驗。

### 風險

- **低風險：** 只改 prompt 文字，不改 tool code
- **注意：** LLM 可能忽略「先輸出再繼續」的指令，需要用強指令語氣（如 `YOU MUST output the preliminary summary BEFORE calling Step 1B tools. DO NOT batch all tools together.`）
- **Token 影響：** 多一次 answer generation（preliminary summary），增加約 500-1000 tokens

---

## 建議 7：強制使用 `system_ask_user` 來維持 menu selection turn

> 日期：2026-05-04 | 背景：`--json` 模式下，LLM 把 attachment menu 輸出為 answer text 就結束 turn，導致使用者的 selection（如 "1", "all"）被當作全新一輪對話，LLM 重新跑 Phase 1

### 問題

在 `--json` 模式下：
1. LLM 輸出 attachment selection menu → `usage` event fires → turn 結束
2. 使用者回覆 "1" → 變成全新的 turn
3. LLM 不理解 "1" 是回應前面的 menu → 重新啟動 Phase 1 分析

在 CLI 模式（無 `--json`）下這個問題不存在，因為 LLM 使用 `system_ask_user` tool 來收集使用者回覆，turn 不會中斷。

### 建議修改

在 `sighting_assistant.yaml` 的 prompt 中加入明確指令：

```yaml
prompt: |
  ## CRITICAL: Interactive Menu — MUST use system_ask_user

  When you need to present an attachment/analysis selection menu to the user:
  1. Output the menu items as answer text (so user can see the options)
  2. IMMEDIATELY call `system_ask_user` tool to collect their selection
  3. DO NOT end your turn after displaying the menu
  4. DO NOT output the menu and wait for the next user message

  Example flow:
  - You output: "Available items:\n1. ETL: file.zip\n2. GDHM: 3254128063\nEnter selection..."
  - You MUST then call: system_ask_user(question="Enter numbers (1,2), 'all', or 'skip'")
  - The user's response comes back in the same turn
  - You proceed with analyzing the selected items

  This is MANDATORY because in --json mode, ending your turn loses the menu context.
```

### 預期效果

| 情境 | 改前 | 改後 |
|------|------|------|
| 使用者輸入 "1" | LLM 重新 Phase 1 | LLM 正確分析 item 1 |
| 使用者輸入 "all" | LLM 重新 Phase 1 | LLM 分析所有 items |
| 使用者輸入 "skip" | LLM 重新 Phase 1 | LLM 跳過，直接產出報告 |

### 風險

- **低風險：** `system_ask_user` 是 GNAI 平台內建 tool，不需額外安裝
- **注意：** 需確認 `system_ask_user` 在 `--json` 模式下的 event 格式（可能產出 `{"tool":"system_ask_user", ...}` event），Bridge 端需要對應處理
- **替代方案（如果 system_ask_user 不可用）：** 在 prompt 中強調 "If the user's message matches `/^\d{1,2}(,\d{1,2})*$|^all$|^skip$/i`, treat it as a response to your last attachment menu and proceed with analysis. Do NOT restart Phase 1."

### Bridge 端配合修改

如果 `system_ask_user` 產出特殊 JSON event，Bridge 需要：
1. 偵測 `system_ask_user` event
2. 發送 `waiting_input` event 給 Extension（啟用輸入框）
3. 使用者的回覆直接送入 PTY（不加 prefix）

這比目前的 "加 prefix 讓 LLM 理解" 方案更可靠，因為 turn 根本不會中斷。

---

## 建議 8：合併所有互動 gates 為單一 checklist（消除線性問答）

> 日期：2026-05-04 | 背景：目前 Phase 2 menu → Phase 3A wiki → Phase 3B similar HSDs 是線性問答，每問一次等一次回覆才問下一個。使用者要來回 3-4 次才能進入報告階段。

### 問題

目前流程：
```
[AI] Attachment menu: 1. ETL  2. GDHM → 等使用者選
[User] 1
[AI] Phase 3A: Wiki search? Type query or skip → 等使用者回答
[User] skip
[AI] Phase 3B: Similar HSDs? yes/no → 等使用者回答
[User] yes
[AI] (終於開始跑…)
```

每一步都是一個完整的 turn，使用者需要反覆等待 + 回答 3~4 次。

### 建議修改

將 Phase 2 + Phase 3 所有 gates 合併成**一張 checklist**，讓使用者一次選完：

```yaml
prompt: |
  ## Phase 2+3: Consolidated Selection Menu

  After Phase 1 (article read + category + RAG) completes, present a SINGLE
  consolidated selection menu. DO NOT ask questions one by one.

  Format EXACTLY as follows:

  ---
  ## Analysis Options — HSD {id}

  **Attachments to analyze:**
  1. ETL: SystemScopeTool_2026_03_19.zip
  2. GDHM ID: 3254128063

  **Additional analysis:**
  3. Wiki search (suggested query: "{auto_generated_query}")
  4. Similar HSD search

  Enter numbers (e.g. 1,2,4 or all), or skip:
  ---

  Rules:
  - Items 1-N are attachments (from Phase 2 scan)
  - Additional items are Phase 3 gates (wiki, similar HSDs, etc.)
  - User selects ALL desired items in ONE response (e.g. "1,3,4" or "all")
  - "skip" means skip ALL optional items, generate report from Phase 1 data only
  - After receiving selection, execute ALL selected items, then generate report
  - DO NOT ask follow-up questions for each item separately
```

### 預期新流程

```
[AI] Phase 1 complete. Here's your consolidated menu:
     1. ETL: SystemScope...zip
     2. GDHM: 3254128063
     3. Wiki search (suggested: "Xe3UpdateATS divide by zero")
     4. Similar HSD search
     Enter numbers or all/skip:

[User] 2,4        ← 一次選完！

[AI] Running GDHM analysis + Similar HSD search...
     (全部跑完後直接產出報告)
```

### Extension 端配合

Extension 的 `generateQuickActions()` **已經支援** numbered list 按鈕，所以：
- Attachment items → 顯示為 "1 — ETL: SystemScope..." 按鈕
- Additional items → 顯示為 "3 — Wiki search" 按鈕  
- "All" / "Skip" 按鈕照常顯示

使用者可以：
- 點個別按鈕（送出 "2"）
- 手動輸入組合（"2,4"）
- 點 "All" 全選

### 風險

- **低風險：** 純 prompt 修改
- **注意：** LLM 需正確理解多選組合（如 "2,4" = GDHM + Similar HSDs），prompt 要強調
- **Edge case：** Wiki search 需要 query 文字 — 如果使用者選了 wiki，用 auto-suggested query（LLM 根據 Phase 1 內容自動生成）。如果使用者想自定 query，可以輸入 "3:my custom query"

### 修改影響

| 項目 | 改前 | 改後 |
|------|------|------|
| 使用者互動次數 | 3-4 次 | **1 次** |
| 等待回合數 | 3-4 rounds | **1 round** |
| 使用者控制力 | 被動回答 | 主動勾選 |
| Extension 改動 | 不需要 | 不需要（已有 numbered buttons） |
| Token 消耗 | 較多（多 turn overhead） | 較少 |
