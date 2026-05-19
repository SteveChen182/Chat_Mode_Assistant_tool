# Chat Mode Assistant — Extension Overview

## What Is This?

**Chat Mode Assistant** is a Chrome Extension that provides a graphical side-panel interface for interacting with Intel's GNAI Sighting Assistant Tool — a CLI-based AI agent that analyzes HSD (Hardware Sighting Database) issues.

Without this extension, engineers must use a terminal to interact with the AI assistant. The extension bridges that gap by providing a modern chat UI directly inside Chrome, right next to the HSD-ES web pages they're already working with.

---

## Architecture (Three-Layer Design)

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Chrome Extension (User Interface)                 │
│  ┌────────────────────┐   ┌───────────────────────────┐    │
│  │  sidepanel.js       │   │  background.js             │    │
│  │  • Chat UI          │   │  • Bridge connection mgmt  │    │
│  │  • Markdown render  │   │  • SSE event consumer      │    │
│  │  • Quick-action btn │   │  • Auto-launch bridge      │    │
│  │  • HSD import       │   │  • Health monitoring       │    │
│  │  • Chat history     │   │  • Reconnect logic         │    │
│  └────────────────────┘   └───────────────────────────┘    │
└────────────────────────────────┬────────────────────────────┘
                                 │ HTTP + SSE (localhost:8776)
┌────────────────────────────────┴────────────────────────────┐
│  Layer 2: Bridge Server (Protocol Translator)               │
│  • Python HTTP server on port 8776                          │
│  • Manages dt CLI process via ConPTY (pywinpty)             │
│  • Parses JSON stdout → SSE events for extension           │
│  • Auto-closes subprocess "pause" windows                   │
└────────────────────────────────┬────────────────────────────┘
                                 │ ConPTY stdin/stdout
┌────────────────────────────────┴────────────────────────────┐
│  Layer 3: dt gnai chat --json --assistant sighting_assistant │
│  • Intel DevTools CLI (Go binary)                           │
│  • Connects to GNAI Platform (LLM + 15 custom tools)       │
│  • Streams structured JSON events                           │
└─────────────────────────────────────────────────────────────┘
```

---

## User Workflow

### Step 1: Open Extension
Click the extension icon → Side panel opens → Bridge auto-starts → Session connects.

### Step 2: Provide HSD ID
Either:
- **Type** an HSD ID (e.g., `14027453772`) directly in the chat
- **Import** from current tab — click "Import" while viewing an HSD-ES article page

### Step 3: AI Analysis (Automated)
The assistant automatically:
1. **Phase 0**: Loads config (skipped if already configured)
2. **Phase 1A**: Reads HSD article, runs parallel tasks (RAG search, similarity search, classification)
3. **Phase 1B**: Presents attachment menu for user selection
4. **Phase 2**: Analyzes selected logs (Sherlog for crash dumps, DisplayDebugger for ETL traces)
5. **Phase 3**: Generates structured analysis report

### Step 4: Interact
- Use **quick-action buttons** (auto-generated from AI response) to select menu items
- Type follow-up questions for deeper analysis
- **Save** the conversation as an HTML report

---

## Role of the Extension

| Without Extension | With Extension |
|---|---|
| Open terminal, remember CLI commands | One-click from Chrome side panel |
| Copy-paste HSD IDs manually | Auto-import from HSD-ES page URL |
| Read raw terminal output | Formatted markdown with tables/code blocks |
| No visual progress feedback | Spinning indicators for each tool step |
| Must type menu numbers manually | Quick-action buttons for selections |
| No history between sessions | Saved chat history (last 10 sessions) |
| Must manually save output | One-click HTML export |
| CLI not shareable with non-technical users | Clean GUI accessible to all engineers |

---

## How It Enhances GNAI for Users

### 1. Zero-Friction Access
Engineers spend most of their time in Chrome looking at HSD-ES. The extension brings AI analysis **right next to their workflow** — no terminal switching needed.

### 2. Smart Context Passing
The extension automatically:
- Extracts HSD ID from the current browser tab URL
- Generates unique conversation IDs for session tracking
- Prefixes menu selections with context to prevent LLM misinterpretation in `--json` mode

### 3. Real-Time Streaming Visualization
Instead of watching raw JSON scroll by, users see:
- **Progressive markdown rendering** of AI responses
- **Tool execution indicators** showing which analysis step is running
- **Live streaming** text appearing as the AI generates it

### 4. Intelligent Interaction Assistance
The extension parses AI responses and auto-generates:
- **Numbered buttons** for menu selections (e.g., "Select attachments to analyze")
- **Yes/No buttons** for confirmation prompts
- **Option buttons** for multi-choice questions

### 5. Session Persistence
- Chat history stored locally (up to 10 sessions)
- HTML export for sharing analysis results with team members
- Conversation ID tracking for future session resume capability

---

## Technical Highlights

| Challenge | Solution |
|---|---|
| Chrome Extension cannot spawn processes | Bridge server as HTTP intermediary |
| Go binary (`dt`) block-buffers stdout on pipes | ConPTY (pywinpty) forces line-buffered output |
| Large AI responses (30KB+) cause UI lag | Progressive rendering with frozen/tail DOM nodes |
| `--json` mode loses menu context | Auto-prefix selections with explicit instructions |
| Subprocess tools open "Press any key" windows | Background thread auto-closes them |
| Service Worker may suspend | Auto-reconnect with SSE re-establishment |

---
---

# Chat Mode Assistant — Extension 總覽（中文版）

## 這是什麼？

**Chat Mode Assistant** 是一個 Chrome 擴充功能，提供圖形化側邊面板介面，用來與 Intel 的 GNAI Sighting Assistant Tool 互動——這是一個基於 CLI 的 AI 代理，專門分析 HSD（Hardware Sighting Database）問題。

沒有這個 extension 的話，工程師必須在終端機中與 AI 助手互動。Extension 填補了這個落差，在 Chrome 中提供現代化的聊天 UI，就在工程師正在使用的 HSD-ES 網頁旁邊。

---

## 架構（三層設計）

```
┌─────────────────────────────────────────────────────────────┐
│  第一層：Chrome Extension（使用者介面）                        │
│  ┌────────────────────┐   ┌───────────────────────────┐    │
│  │  sidepanel.js       │   │  background.js             │    │
│  │  • 聊天介面         │   │  • Bridge 連線管理          │    │
│  │  • Markdown 渲染    │   │  • SSE 事件消費者           │    │
│  │  • 快速動作按鈕     │   │  • 自動啟動 bridge          │    │
│  │  • HSD 匯入         │   │  • 健康狀態監控            │    │
│  │  • 聊天記錄         │   │  • 重連邏輯               │    │
│  └────────────────────┘   └───────────────────────────┘    │
└────────────────────────────────┬────────────────────────────┘
                                 │ HTTP + SSE (localhost:8776)
┌────────────────────────────────┴────────────────────────────┐
│  第二層：Bridge Server（協議轉換器）                          │
│  • Python HTTP 伺服器，port 8776                             │
│  • 透過 ConPTY (pywinpty) 管理 dt CLI 程序                   │
│  • 解析 JSON stdout → 轉成 SSE 事件給 extension             │
│  • 自動關閉子程序的「按任意鍵」視窗                            │
└────────────────────────────────┬────────────────────────────┘
                                 │ ConPTY stdin/stdout
┌────────────────────────────────┴────────────────────────────┐
│  第三層：dt gnai chat --json --assistant sighting_assistant   │
│  • Intel DevTools CLI（Go 二進位檔）                          │
│  • 連接 GNAI 平台（LLM + 15 個自定義工具）                    │
│  • 串流輸出結構化 JSON 事件                                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 使用流程

### 步驟 1：開啟 Extension
點擊 extension 圖示 → 側邊面板開啟 → Bridge 自動啟動 → Session 連接完成。

### 步驟 2：提供 HSD ID
兩種方式：
- **直接輸入** HSD ID（例如 `14027453772`）到聊天框
- **從網頁匯入** — 在 HSD-ES 文章頁面點擊「Import」按鈕，自動擷取 URL 中的 ID

### 步驟 3：AI 自動分析
助手自動執行：
1. **Phase 0**：載入設定（已設定過則跳過）
2. **Phase 1A**：讀取 HSD 文章，平行執行 RAG 搜尋、相似度搜尋、分類
3. **Phase 1B**：呈現附件選單讓使用者選擇
4. **Phase 2**：分析選定的 log（Sherlog 分析 crash dump、DisplayDebugger 分析 ETL 追蹤）
5. **Phase 3**：產生結構化分析報告

### 步驟 4：互動
- 使用**快速動作按鈕**（從 AI 回應自動產生）來選擇選單項目
- 輸入追問問題進行更深入的分析
- **儲存**對話為 HTML 報告

---

## Extension 扮演的角色

| 沒有 Extension | 有 Extension |
|---|---|
| 開終端機、記住 CLI 指令 | Chrome 側邊面板一鍵開啟 |
| 手動複製貼上 HSD ID | 從 HSD-ES 頁面 URL 自動匯入 |
| 閱讀原始終端輸出 | 格式化的 Markdown（表格、程式碼區塊） |
| 沒有視覺進度回饋 | 每個工具步驟都有轉圈圈指示器 |
| 必須手動輸入選單數字 | 快速動作按鈕一鍵選擇 |
| Session 之間沒有記錄 | 儲存聊天記錄（最近 10 筆） |
| 必須手動儲存輸出 | 一鍵匯出 HTML |
| CLI 對非技術使用者不友善 | 清晰的 GUI，所有工程師都能使用 |

---

## 如何讓使用者更好地取得 GNAI 資料

### 1. 零摩擦存取
工程師大部分時間都在 Chrome 上看 HSD-ES。Extension 把 AI 分析帶到**工作流程旁邊**——不需要切換到終端機。

### 2. 智慧上下文傳遞
Extension 自動：
- 從瀏覽器分頁 URL 擷取 HSD ID
- 產生唯一的 conversation ID 用於 session 追蹤
- 在選單回覆前加上 context prefix，防止 LLM 在 `--json` 模式下誤解

### 3. 即時串流視覺化
使用者看到的不是原始 JSON，而是：
- AI 回應的**漸進式 Markdown 渲染**
- 顯示目前正在執行哪個分析步驟的**工具執行指示器**
- AI 生成文字時的**即時串流**顯示

### 4. 智慧互動輔助
Extension 解析 AI 回應，自動產生：
- **數字按鈕**用於選單選擇（例如「選擇要分析的附件」）
- **Yes/No 按鈕**用於確認提示
- **選項按鈕**用於多選問題

### 5. Session 持久化
- 聊天記錄本地儲存（最多 10 筆 session）
- HTML 匯出，方便與團隊成員分享分析結果
- Conversation ID 追蹤，為未來的 session 恢復功能做準備

---

## 技術亮點

| 挑戰 | 解決方案 |
|---|---|
| Chrome Extension 無法直接啟動程序 | Bridge server 作為 HTTP 中介 |
| Go binary（`dt`）在 pipe 時 block-buffer stdout | ConPTY (pywinpty) 強制 line-buffered 輸出 |
| 大型 AI 回應（30KB+）造成 UI 卡頓 | 漸進式渲染，使用 frozen/tail DOM 節點分離 |
| `--json` 模式丟失選單上下文 | 自動在選擇前加上明確指令 prefix |
| 子程序工具開啟「按任意鍵」視窗 | 背景執行緒自動關閉 |
| Service Worker 可能被暫停 | 自動重連 + SSE 重新建立 |
