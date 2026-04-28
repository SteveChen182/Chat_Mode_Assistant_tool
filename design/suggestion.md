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
