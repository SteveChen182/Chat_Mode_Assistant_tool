# Suggestions for SightingAssistantTool Team

> These changes on the **Tool/Assistant side** will significantly improve the Chrome Extension integration reliability and user experience.

---

## Priority 1 — Critical

### 1.1 

| Item                             | Detail                                                                                                                                                                                                                                                                                                                                          |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Problem**                | In `--json` mode (`dt gnai chat --json`), when user replies to a selection menu (e.g. types "1"), the LLM loses context and restarts Phase 1 analysis from scratch. **This does NOT happen in CLI mode (without `--json`)** — typing "1" in CLI mode correctly selects the item and proceeds.                                      |
| **Verified**               | 2026-05-05: Tested both modes with HSD 14027453772. CLI mode (no --json) → "1" works correctly. JSON mode → "1" triggers full re-analysis.                                                                                                                                                                                                    |
| **Root Cause**             | The `dt` binary's `--json` mode likely constructs the conversation history differently, causing the LLM to lose the previous turn's context (menu output) when processing the next user message.                                                                                                                                            |
| **Who should fix**         | **GNAI Platform Team** — this is a `dt` binary behavior difference between `--json` and non-`--json` mode. The conversation history should be identical regardless of output format.                                                                                                                                               |
| **Workaround (Tool Team)** | Use suggestion 2.1 below (consolidated menu) to reduce interactive turns to 1, minimizing exposure to this bug. Additionally, add a prompt instruction:*"If the user's message is a short number (1-2 digits), comma-separated numbers, 'all', or 'skip', it is ALWAYS a response to your previous selection menu. Do NOT restart analysis."* |
| **Effort**                 | Bug report: 15 min. Prompt workaround: 20 min.                                                                                                                                                                                                                                                                                                  |

```yaml
# Prompt workaround — add to sighting_assistant.yaml:
IMPORTANT: If the user's next message after a selection menu is a short input
matching the pattern: numbers (e.g. "1", "2,3", "1-3"), "all", or "skip",
this is ALWAYS their response to YOUR previous menu.
You MUST proceed with analyzing the selected items.
Do NOT restart Phase 1. Do NOT re-read the article. Do NOT re-display the menu.
```

---

### 1.2 Remove `pause` from subprocess batch files

| Item              | Detail                                                                                                                                                                                                 |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Problem** | `sherlog_subprocess.py` and `displaydebugger_subprocess.py` add `pause` at the end of batch files. Child windows stay open indefinitely, blocking the process and requiring manual intervention. |
| **Fix**     | Remove the `pause` line from batch file generation.                                                                                                                                                  |
| **Effort**  | 5 min                                                                                                                                                                                                  |
| **Risk**    | Very low                                                                                                                                                                                               |

```python
# Before:
batch_content += "pause\n"

# After:
# (delete the line)
```

---

## Priority 2 — High

### 2.1 Consolidate all interactive gates into ONE menu

| Item              | Detail                                                                                                                                                                                                                          |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Problem** | Current flow asks user questions one by one: attachment menu → wiki search? → similar HSDs? Each requires a full round-trip (3-4 turns total). Combined with the P1 issue above, each turn boundary risks LLM losing context. |
| **Fix**     | After Phase 1, present ONE consolidated menu combining attachments + all optional analyses. User selects everything in a single response.                                                                                       |
| **Effort**  | ~30 min (prompt restructure)                                                                                                                                                                                                    |
| **Risk**    | Low                                                                                                                                                                                                                             |

```yaml
# Desired output format:
## Analysis Options — HSD {id}

**Attachments:**
1. ETL: SystemScopeTool_2026_03_19.zip
2. GDHM ID: 3254128063

**Additional analysis:**
3. Wiki search (suggested: "Xe3UpdateATS divide by zero")
4. Similar HSD search

Enter numbers (e.g. 1,2,4 or all), or skip:
```

**Result:** User interaction reduced from 3-4 turns → **1 turn**.

---

### 2.2 Split Phase 1 into fast + slow steps

| Item              | Detail                                                                                                                                                                     |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Problem** | All Phase 1 tools run simultaneously. User sees nothing until Sherlog/DisplayDebugger (1-5 min) completes.                                                                 |
| **Fix**     | Step 1A: run quick tools (read_article, attachments, RAG) → output preliminary summary immediately. Step 1B: run slow tools (sherlog, displaydebugger) → append results. |
| **Effort**  | ~20 min (prompt change)                                                                                                                                                    |
| **Risk**    | Low — LLM may occasionally ignore "output first" instruction; use strong directive                                                                                        |

---

### 2.3 Session management — independent sessions per HSD ID

| Item              | Detail                                                                                                                                                                                                                     |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Problem** | Currently `dt gnai chat` uses a single continuous conversation. When a CE switches to a different HSD, all previous context is carried along and can confuse the LLM. There is no way to "park" one session and start a fresh one. |
| **Ask**     | Investigate whether `gnai chat` can support named/independent sessions (similar to `gnai ask --session <name>`), so a CE can run multiple HSD analyses in parallel and switch between them without cross-contamination.       |
| **Benefit** | CEs typically work on 5-10 HSDs per day. With session support: switch HSD → resume where you left off; no context pollution between cases; Extension can map each tab/panel to a session ID.                                |
| **Effort**  | Investigation + implementation by GNAI Platform team (not a prompt change)                                                                                                                                                  |
| **Risk**    | Low — additive feature, does not break existing single-session usage                                                                                                                                                       |

Desired CLI interface (for reference):
```bash
# Start or resume a named session
dt gnai chat --json --assistant sighting_assistant --session hsd_14027453772

# List active sessions
dt gnai chat --list-sessions

# Delete a session
dt gnai chat --delete-session hsd_14027453772
```

---

## Priority 3 — Medium

### 3.1 Add `[PROGRESS]` output for long-running tools

| Item              | Detail                                                                                                                               |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| **Problem** | When Sherlog or DisplayDebugger runs for 1-5 min, the only signal is `tool_start`. No progress updates — user thinks it's frozen. |
| **Fix**     | Add `print("[PROGRESS] Sherlog: analyzing dump 3254128063...")` at key stages in subprocess scripts.                               |
| **Effort**  | ~20 min                                                                                                                              |
| **Risk**    | Very low                                                                                                                             |

---

### 3.2 Structured interaction markers

| Item              | Detail                                                                                                       |
| ----------------- | ------------------------------------------------------------------------------------------------------------ |
| **Problem** | Extension must use regex heuristics to detect when LLM is asking a question. Sometimes misdetects or misses. |
| **Fix**     | Instruct LLM to wrap interactive prompts in parseable tags.                                                  |
| **Effort**  | ~30 min                                                                                                      |
| **Risk**    | Low (LLM may occasionally forget)                                                                            |

```yaml
# When asking user for selection:
[USER_INPUT_REQUIRED:SELECT_MULTIPLE]
1. ETL: file.zip
2. GDHM: 3254128063
[/USER_INPUT_REQUIRED]

# When asking yes/no:
[USER_INPUT_REQUIRED:YES_NO]
Would you like to search for similar HSDs?
[/USER_INPUT_REQUIRED]
```

---

### 3.3 Fixed phase markers

| Item              | Detail                                                                                  |
| ----------------- | --------------------------------------------------------------------------------------- |
| **Problem** | Extension cannot reliably track which phase is running — only infers from answer text. |
| **Fix**     | Output a fixed-format marker at each phase start.                                       |
| **Effort**  | ~15 min                                                                                 |
| **Risk**    | Low                                                                                     |

```
[PHASE:1:DATA_GATHERING]
[PHASE:2:ATTACHMENT_ANALYSIS]
[PHASE:3:REPORT_GENERATION]
```

---

## Section 4 — Integration Protocol (Tool ↔ Extension Collaboration)

To maximize reliability of the consolidated menu (2.1) and work around the `--json` turn-break issue (1.1), we propose a **Menu Protocol** that both sides agree on:

### 4.1 Tool side: Fixed menu output format with markers

Wrap the selection menu in parseable tags so Extension can detect it with 100% accuracy:

```
[MENU:START]
1. ETL: SystemScopeTool_2026_03_19.zip
2. GDHM ID: 3254128063
3. Wiki search (suggested: "Xe3 divide by zero")
4. Similar HSD search
[MENU:END]
```

**Effort (Tool):** 15 min prompt change

### 4.2 Extension side: Multi-select toggle UI

When Extension detects `[MENU:START]...[MENU:END]`, it renders:
- Each item as a **toggle button** (click to select/deselect)
- An "All" shortcut and a "Skip" shortcut
- A "Submit" button that sends all selected items as comma-separated numbers

This replaces the current single-click-sends-immediately behavior.

**Effort (Extension):** ~1 hour

### 4.3 Agreed response format: `[MENU_RESPONSE]`

Extension sends the user's selection in a fixed format:

```
[MENU_RESPONSE] 1,3,4
```

Tool prompt includes:
```yaml
IMPORTANT: If user message starts with [MENU_RESPONSE], the rest is their
selection for your last menu. Proceed with analyzing ONLY the selected items.
Do NOT restart Phase 1. Do NOT re-read the article.
```

This is shorter and more reliable than a natural language prefix, and explicitly signals intent even when `--json` mode breaks turn context.

**Effort (Tool):** 10 min prompt addition

### 4.4 (Optional) State token for context recovery

Tool embeds a state token in the menu:
```
[MENU:START:state=phase2_hsd14027453772]
...
[MENU:END]
```

Extension echoes it back:
```
[MENU_RESPONSE:state=phase2_hsd14027453772] 1,3
```

LLM sees the state token and 100% knows which menu this responds to, even if turn context is lost.

**Effort (Both):** 30 min total

### Section 4 — Division of Work

| Task | Owner | Effort |
|------|-------|--------|
| `[MENU:START/END]` markers in prompt | Tool Team | 15 min |
| `[MENU_RESPONSE]` prompt instruction | Tool Team | 10 min |
| Detect `[MENU:START/END]`, render toggle buttons | Extension | 30 min |
| Multi-select UI + Submit button | Extension | 1 hr |
| State token (optional) | Both | 30 min |

---

## Summary Table

| #   | Suggestion                     | Priority              | Effort                 | Impact                                         |
| --- | ------------------------------ | --------------------- | ---------------------- | ---------------------------------------------- |
| 1.1 | `--json` menu context bug    | **P1-Critical** | Report + 20 min prompt | GNAI platform bug; prompt workaround available |
| 1.2 | Remove `pause`               | **P1-Critical** | 5 min                  | Eliminates child window hang                   |
| 2.1 | Consolidated menu              | **P2-High**     | 30 min                 | 3-4 turns → 1 turn                            |
| 2.2 | Phase 1 fast/slow split        | **P2-High**     | 20 min                 | Eliminates 1-5 min "blank screen"              |
| 2.3 | Session management per HSD     | **P2-High**     | GNAI Platform team     | CEs can switch HSD without context pollution   |
| 3.1 | Progress output                | **P3-Medium**   | 20 min                 | User knows tool is working                     |
| 3.2 | `[USER_INPUT_REQUIRED]` tags | **P3-Medium**   | 30 min                 | 100% accurate button generation                |
| 3.3 | Phase markers                  | **P3-Medium**   | 15 min                 | Enables progress bar UI                        |
| 4.x | Menu Protocol (Tool↔Extension) | **P2-High**     | Tool: 25 min, Ext: 1.5 hr | Reliable multi-select even with --json bug |

---

## Notes

- All P1 and P2 items are **prompt-only changes** (modify `sighting_assistant.yaml`) except 1.2 which is a one-line code deletion.
- P3 items are optional enhancements — Extension already has workarounds via regex detection.
- Section 4 (Menu Protocol) requires coordination between Tool and Extension teams but provides the strongest fix for the `--json` turn-break issue.
- No changes to tool function signatures or APIs are required.
- Total estimated effort for all items: **~4 hours** (Tool: ~1.5 hr, Extension: ~2.5 hr)
- Total for P1+P2 only: **~2 hours**

---

---

# SightingAssistantTool 修改建議（中文版）

> 以下修改針對 **Tool/Assistant 端**，能顯著提升 Chrome Extension 整合的可靠性與使用者體驗。

---

## Priority 1 — 嚴重（影響功能正確性）

### 1.1 `--json` 模式下選項選擇失去上下文（GNAI 平台 Bug）

| 項目                                   | 說明                                                                                                                                                                                                    |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **問題**                         | `--json` 模式下（`dt gnai chat --json`），使用者回覆選項 menu（如打 "1"）後，LLM 失去上下文並重新跑 Phase 1 分析。**在 CLI 模式（不加 `--json`）下不會發生** — 打 "1" 可正確選擇並繼續。   |
| **已驗證**                       | 2026-05-05：用 HSD 14027453772 測試兩種模式。CLI 模式 → "1" 正確運作。JSON 模式 → "1" 觸發重新分析。                                                                                                  |
| **根本原因**                     | `dt` binary 的 `--json` 模式在建構 conversation history 時可能有差異，導致 LLM 在處理下一條使用者訊息時遺失了前一輪的 context（menu 輸出）。                                                        |
| **應修復方**                     | **GNAI Platform Team** — 這是 `dt` binary 在 `--json` vs 非 `--json` 模式間的行為差異。conversation history 不應因 output format 不同而不同。                                              |
| **Workaround（Tool Team 可做）** | 用建議 2.1（合併選項）將互動減少到 1 次，降低此 bug 的影響。另外在 prompt 中加入指令：*"如果使用者的訊息是 1-2 位數字、逗號分隔數字、'all' 或 'skip'，這一定是回應你前面的選項 menu。不可重新分析。"* |
| **工作量**                       | Bug report：15 分鐘。Prompt workaround：20 分鐘。                                                                                                                                                       |

```yaml
# Prompt workaround — 加入 sighting_assistant.yaml：
IMPORTANT: If the user's next message after a selection menu is a short input
matching the pattern: numbers (e.g. "1", "2,3", "1-3"), "all", or "skip",
this is ALWAYS their response to YOUR previous menu.
You MUST proceed with analyzing the selected items.
Do NOT restart Phase 1. Do NOT re-read the article. Do NOT re-display the menu.
```

---

### 1.2 移除子視窗的 `pause`

| 項目             | 說明                                                                                                                                    |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **問題**   | `sherlog_subprocess.py` 和 `displaydebugger_subprocess.py` 的 batch file 最後有 `pause`，子視窗卡住不關閉，阻塞流程且需手動介入。 |
| **修改**   | 刪除 batch 生成中的 `batch_content += "pause\n"`                                                                                      |
| **工作量** | 5 分鐘                                                                                                                                  |
| **風險**   | 極低                                                                                                                                    |

```python
# 改前：
batch_content += "pause\n"

# 改後：
# （刪除該行即可）
```

---

## Priority 2 — 高（大幅改善使用者體驗）

### 2.1 合併所有互動選項為單一 checklist

| 項目             | 說明                                                                                                                                               |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **問題**   | 目前流程是線性逐一問：attachment menu → wiki search? → similar HSDs?，需要 3-4 次來回。加上 P1 的問題，每次 turn 結束都有 LLM 失去上下文的風險。 |
| **修改**   | Phase 1 完成後，一次列出所有 attachments + 可選分析項目（wiki、similar HSDs），使用者一次選完。                                                    |
| **工作量** | 約 30 分鐘（prompt 重構）                                                                                                                          |
| **風險**   | 低                                                                                                                                                 |

```yaml
# 期望輸出格式：
## Analysis Options — HSD {id}

**Attachments:**
1. ETL: SystemScopeTool_2026_03_19.zip
2. GDHM ID: 3254128063

**Additional analysis:**
3. Wiki search (suggested: "Xe3UpdateATS divide by zero")
4. Similar HSD search

Enter numbers (e.g. 1,2,4 or all), or skip:
```

**效果：** 使用者互動從 3-4 次 → **1 次**。

---

### 2.2 Phase 1 拆兩步：先出摘要再跑耗時 tools

| 項目             | 說明                                                                                                                                       |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| **問題**   | 所有 Phase 1 tools 同時跑，使用者要等 Sherlog/DisplayDebugger 跑完（1-5 分鐘）才看到第一個字。                                             |
| **修改**   | Step 1A：跑快速 tools（read_article, attachments, RAG）→ 立即輸出初步摘要。Step 1B：跑慢速 tools（sherlog, displaydebugger）→ 追加結果。 |
| **工作量** | 約 20 分鐘（prompt 修改）                                                                                                                  |
| **風險**   | 低 — LLM 偶爾可能忽略「先輸出再繼續」的指令，需用強指令語氣                                                                               |

---

### 2.3 Session 管理 — 每個 HSD ID 獨立 session

| 項目             | 說明                                                                                                                                                                                                                          |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **問題**   | 目前 `dt gnai chat` 只有單一連續對話。當 CE 切換到不同 HSD 時，前面的 context 全部帶著走，容易混淆 LLM。無法「暫停」一個 session 再開新的。                                                                                    |
| **期望**   | 調查 `gnai chat` 是否能支援具名/獨立 session（類似 `gnai ask --session <name>`），讓 CE 可以同時處理多個 HSD 分析並自由切換，互不污染。                                                                                        |
| **效益**   | CE 每天通常處理 5-10 個 HSD。有 session 支援後：切換 HSD → 接續上次進度；不同 case 之間 context 不互相污染；Extension 端可將每個 tab/panel 對應一個 session ID。                                                                |
| **工作量** | GNAI 平台團隊調查 + 實作（非 prompt 修改）                                                                                                                                                                                     |
| **風險**   | 低 — 純新增功能，不影響現有單一 session 用法                                                                                                                                                                                   |

期望 CLI 介面（供參考）：
```bash
# 開啟或恢復具名 session
dt gnai chat --json --assistant sighting_assistant --session hsd_14027453772

# 列出目前有效的 sessions
dt gnai chat --list-sessions

# 刪除 session
dt gnai chat --delete-session hsd_14027453772
```

---

## Priority 3 — 中等（提升整合品質）

### 3.1 長時間工具加 progress 輸出

| 項目             | 說明                                                                                                |
| ---------------- | --------------------------------------------------------------------------------------------------- |
| **問題**   | Sherlog/DisplayDebugger 跑 1-5 分鐘時沒有任何中間輸出，使用者以為當掉。                             |
| **修改**   | 在 subprocess script 的關鍵步驟加入 `print("[PROGRESS] Sherlog: analyzing dump 3254128063...")`。 |
| **工作量** | 約 20 分鐘                                                                                          |
| **風險**   | 極低                                                                                                |

---

### 3.2 結構化互動標記

| 項目             | 說明                                                         |
| ---------------- | ------------------------------------------------------------ |
| **問題**   | Extension 要用 regex 猜測 LLM 是否在問問題，有時誤判或漏判。 |
| **修改**   | 在 prompt 中指示 LLM 用結構化標記包裹互動問題。              |
| **工作量** | 約 30 分鐘                                                   |
| **風險**   | 低（LLM 偶爾可能忘記加標記）                                 |

```yaml
# 選擇題：
[USER_INPUT_REQUIRED:SELECT_MULTIPLE]
1. ETL: file.zip
2. GDHM: 3254128063
[/USER_INPUT_REQUIRED]

# 是非題：
[USER_INPUT_REQUIRED:YES_NO]
Would you like to search for similar HSDs?
[/USER_INPUT_REQUIRED]
```

---

### 3.3 固定 Phase 宣告標記

| 項目             | 說明                                                              |
| ---------------- | ----------------------------------------------------------------- |
| **問題**   | Extension 無法可靠追蹤目前在哪個 Phase，只能從 answer text 推測。 |
| **修改**   | 每個 Phase 開始時輸出固定格式標記。                               |
| **工作量** | 約 15 分鐘                                                        |
| **風險**   | 低                                                                |

```
[PHASE:1:DATA_GATHERING]
[PHASE:2:ATTACHMENT_ANALYSIS]
[PHASE:3:REPORT_GENERATION]
```

---

## 第四節 — 整合協議（Tool ↔ Extension 協作）

為了最大化合併選項 menu（2.1）的可靠性，並繞過 `--json` turn 斷裂問題（1.1），我們提議一個雙方約定的 **Menu Protocol**：

### 4.1 Tool 端：固定 menu 輸出格式加標記

用可解析的標記包裹選項 menu，讓 Extension 能 100% 準確偵測：

```
[MENU:START]
1. ETL: SystemScopeTool_2026_03_19.zip
2. GDHM ID: 3254128063
3. Wiki search (suggested: "Xe3 divide by zero")
4. Similar HSD search
[MENU:END]
```

**工作量（Tool）：** 15 分鐘 prompt 修改

### 4.2 Extension 端：多選 toggle UI

當 Extension 偵測到 `[MENU:START]...[MENU:END]`，渲染為：
- 每個選項是一個 **toggle 按鈕**（點擊選取/取消）
- 提供 "All" 和 "Skip" 快捷按鈕
- 一個 "Submit" 按鈕，送出所有已選項目為逗號分隔數字

取代目前「點一個就立刻送出」的行為。

**工作量（Extension）：** 約 1 小時

### 4.3 約定回覆格式：`[MENU_RESPONSE]`

Extension 用固定格式送出使用者的選擇：

```
[MENU_RESPONSE] 1,3,4
```

Tool prompt 中加入：
```yaml
IMPORTANT: If user message starts with [MENU_RESPONSE], the rest is their
selection for your last menu. Proceed with analyzing ONLY the selected items.
Do NOT restart Phase 1. Do NOT re-read the article.
```

這比自然語言 prefix 更短更可靠，且明確標示意圖，即使 `--json` 模式 turn context 遺失也能運作。

**工作量（Tool）：** 10 分鐘 prompt 新增

### 4.4（可選）State token 用於上下文恢復

Tool 在 menu 中嵌入 state token：
```
[MENU:START:state=phase2_hsd14027453772]
...
[MENU:END]
```

Extension 回覆時帶回：
```
[MENU_RESPONSE:state=phase2_hsd14027453772] 1,3
```

LLM 看到 state token 就能 100% 知道這是回應哪個 menu，即使 turn context 遺失。

**工作量（雙方）：** 共 30 分鐘

### 第四節 — 分工表

| 任務 | 負責方 | 工作量 |
|------|--------|--------|
| `[MENU:START/END]` 標記加入 prompt | Tool Team | 15 分鐘 |
| `[MENU_RESPONSE]` prompt 指令 | Tool Team | 10 分鐘 |
| 偵測 `[MENU:START/END]`，渲染 toggle 按鈕 | Extension | 30 分鐘 |
| Multi-select UI + Submit 按鈕 | Extension | 1 小時 |
| State token（可選） | 雙方 | 30 分鐘 |

---

## 總結表

| #   | 建議                           | 優先級            | 工作量                      | 影響                                |
| --- | ------------------------------ | ----------------- | --------------------------- | ----------------------------------- |
| 1.1 | `--json` 選項上下文 bug      | **P1-嚴重** | Report + 20 分鐘 prompt     | GNAI 平台 bug；有 prompt workaround |
| 1.2 | 移除 `pause`                 | **P1-嚴重** | 5 分鐘                      | 消除子視窗卡住問題                  |
| 2.1 | 合併互動選項為單一 menu        | **P2-高**   | 30 分鐘                     | 3-4 次互動 → 1 次                  |
| 2.2 | Phase 1 拆快/慢步              | **P2-高**   | 20 分鐘                     | 消除 1-5 分鐘空白畫面               |
| 2.3 | Session 管理（每 HSD 獨立）    | **P2-高**   | GNAI 平台團隊               | CE 切換 HSD 不會 context 污染       |
| 3.1 | Progress 輸出                  | **P3-中**   | 20 分鐘                     | 使用者知道工具在跑                  |
| 3.2 | `[USER_INPUT_REQUIRED]` 標記 | **P3-中**   | 30 分鐘                     | 100% 精確產生按鈕                   |
| 3.3 | Phase 標記                     | **P3-中**   | 15 分鐘                     | 可實作進度條 UI                     |
| 4.x | Menu Protocol（Tool↔Extension）| **P2-高**   | Tool: 25 分鐘, Ext: 1.5 小時 | 即使有 --json bug 也能可靠多選     |

---

## 備註

- P1 和 P2 項目全部都是 **prompt 修改**（改 `sighting_assistant.yaml`），除了 1.2 是刪一行 code。
- P3 項目為可選增強 — Extension 端已有 regex 偵測的 workaround。
- 第四節（Menu Protocol）需要 Tool 和 Extension 雙方協調，但提供對 `--json` turn 斷裂問題最強力的修復。
- 不需要修改 tool 的 function signatures 或 APIs。
- 全部項目預估工作量：**約 4 小時**（Tool: 約 1.5 小時, Extension: 約 2.5 小時）
- 僅做 P1+P2：**約 2 小時**
