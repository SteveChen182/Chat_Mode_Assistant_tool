# SightingAssistant_Chatter

> A Chrome Extension that brings Intel GNAI-powered GPU sighting analysis directly into your browser's side panel.

SightingAssistant_Chatter is a front-end Chrome Extension designed for CEs and debug engineers to easily access Intel's GNAI-powered sighting analysis — without needing to run CLI commands manually. It connects the browser to the GNAI backend through a local Python bridge, so engineers can get AI-generated analysis directly while browsing HSD pages.

---

## Features

- **HSD-focused analysis** — Import any HSD ID to trigger a full sighting analysis pipeline: article reading, attachment inspection, issue classification, and a 7-section structured report.
- **Real-time streaming** — Responses are streamed token by token with a live progress indicator.
- **Multi-turn conversation** — Continue asking follow-up questions directly from the analysis output, drilling deeper into any part of the result.
- **Quick Action buttons** — 4 built-in buttons after the first response: Last Status & Action, Test Environment, Next Step, Potential Duplicated Issue.
- **Ask / Chat mode** — Toggle between Ask mode (single-turn) and Chat mode (multi-turn conversation).
- **Auto bridge management** — The extension detects whether the local bridge is running and can launch it via Native Messaging if configured.
- **Debug connection tool** — Built-in "Debug Connection" button shows bridge health, ping result, and endpoint status.

---

## Architecture

```
Chrome Side Panel (UI)
       ↕  chrome.runtime port
  background.js  (Service Worker)
       ↕  HTTP fetch  (OpenAI-compatible)
  bridge_server.py  (localhost:8775)
       ↕  subprocess
  dt gnai ask/chat ...  (SightingAssistantTool CLI)
       ↕
  Intel GNAI Platform (sighting_assistant)
```

| Layer | File | Role |
|-------|------|------|
| UI | `sidepanel.html / sidepanel.js` | Chat interface, HSD import, streaming render |
| Background | `background.js` | Bridge health check, API calls, stream relay |
| Bridge | `bridge/bridge_server.py` | Local HTTP server, translates requests to `dt gnai ask` |
| Launcher | `bridge/native_host_launcher.py` | Native Messaging host, auto-starts bridge process |
| Install | `bridge/install_native_host.ps1` | Registers Native Messaging host in Chrome & Registry |

---

## Prerequisites

- **Windows** (Native Messaging launcher is PowerShell-based)
- **Google Chrome**
- **Intel `dt` CLI** with GNAI access (`dt gnai ask "hello"` should work)
- **Python 3.x** (for running the bridge server)
- Intel corporate network or VPN

---

## Quick Start (Colleague Setup)

> If you are installing this for the first time, follow these 3 steps. No need to read the full Installation section below.

**Before you begin:** Verify that `dt gnai ask "hello"` works in your terminal. If it does, you're ready.

**Step 1 — Clone the repo**

```powershell
git clone https://github.com/SteveChen182/GNAI_GCD_AssistChatter.git C:\Intel\SightingChatter
```

> The target path (`C:\Intel\SightingChatter`) must **not contain spaces**.

**Step 2 — Start the bridge**

```powershell
C:\Intel\SightingChatter\GNAI_AssisChatter\bridge\run_bridge.ps1
```

The first run will automatically:
- Copy the sighting toolkit to `C:\dt_sighting`
- Update `~/.gnai/config.yaml` to point to `C:\dt_sighting`
- Start the local bridge server on port 8775

Keep this PowerShell window open while using the extension.

**Step 3 — Load the extension in Chrome**

1. Open `chrome://extensions`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked** → select `C:\Intel\SightingChatter\GNAI_AssisChatter`
4. Open the side panel and click **Debug Connection** to verify the bridge is `🟢 Ready`

---

## Installation (Full)

### Step 1 — Load the extension in Chrome

1. Open `chrome://extensions`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked** → select the `GNAI_AssisChatter` folder
4. Copy the **Extension ID** shown by Chrome (you'll need it in Step 3)

### Step 2 — Prepare the toolkit (first time only)

The bridge calls `dt gnai ask` using the `sighting_assistant`. The toolkit path **must not contain spaces**.

```powershell
New-Item -ItemType Directory -Path C:\dt_sighting -Force
# Copy toolkit.yaml / tools / assistants / src from your SightingAssistantTool clone
```

Then register it in `~/.gnai/config.yaml`:

```yaml
- name: sighting
  type: local
  path: "C:\\dt_sighting"
  url: ""
```

> **Note:** If `cryptography` package in `.workspace` is v42+, downgrade it:
> ```powershell
> C:\dt_sighting\.workspace\tools\python\python.exe -m pip install "cryptography<42" `
>   --target "C:\dt_sighting\.workspace\tools\python-site-packages" `
>   --upgrade --no-deps `
>   --index-url https://gfx-assets.fm.intel.com/artifactory/api/pypi/pypi-gsae/simple
> ```

### Step 3 — Register the Native Messaging host

```powershell
cd GNAI_AssisChatter\bridge
.\install_native_host.ps1 -ExtensionId <YOUR_EXTENSION_ID> -Browser chrome
```

### Step 4 — Reload the extension

In `chrome://extensions`, click **Reload** for SightingAssistant_Chatter.

### Step 5 — Validate

1. Open the extension side panel
2. Click the ⚙ gear icon → **Debug Connection** — it should show `🟢 Ready`

---

## Usage

1. Navigate to an HSD page (`hsdes.intel.com/...`) or any relevant webpage
2. Open the SightingAssistant_Chatter side panel
3. Click **Import HSD** to auto-detect the HSD ID from the URL, or type it manually
4. Press **Send** — the assistant will run the full sighting analysis pipeline
5. Use the Quick Action buttons or type follow-up questions to continue the conversation

> To skip attachment analysis and get a quick summary:
> _"Please give me a punchline summary of HSD XXXXXXXXXX and skip attachment check"_

---

## Bridge Configuration

All settings are controlled via environment variables in `bridge/run_bridge.ps1`:

| Variable | Default | Description |
|----------|---------|-------------|
| `GNAI_BRIDGE_HOST` | `127.0.0.1` | Bridge listen address |
| `GNAI_BRIDGE_PORT` | `8775` | Bridge listen port |
| `GNAI_BRIDGE_TIMEOUT` | `360` | `dt gnai ask` timeout in seconds |
| `GNAI_BRIDGE_DEFAULT_ASSISTANT` | `sighting_assistant` | Default GNAI assistant |
| `GNAI_BRIDGE_DT_PATH` | _(auto)_ | Full path to `dt.exe` if not in PATH |
| `GNAI_BRIDGE_API_KEY` | _(empty)_ | Optional Bearer token for bridge auth |
| `GNAI_BRIDGE_DEBUG` | `1` | Enable debug logging |
| `GNAI_BRIDGE_ECHO_RESPONSE` | `1` | Echo responses to stdout |

---

## File Structure

```
GNAI_AssisChatter/
├── manifest.json               # Chrome Extension MV3 config
├── background.js               # Service worker — bridge health, API calls, stream relay
├── sidepanel.html              # Side panel UI
├── sidepanel.js                # Chat logic, HSD session, streaming render
└── bridge/
    ├── bridge_server.py        # Local HTTP bridge (OpenAI-compatible endpoints)
    ├── run_bridge.ps1          # Bridge startup script (sets env vars + sync toolkit)
    ├── native_host_launcher.py # Native Messaging host — auto-starts bridge
    ├── install_native_host.ps1 # Registers native host in Chrome & Windows Registry
    └── native_host_launcher.cmd# CMD wrapper for the native host
```

---

## Known Limitations

- Windows only (Native Messaging launcher uses PowerShell)
- Requires Intel corporate network or VPN for GNAI and HSDES access
- The toolkit path must **not contain spaces** (OneDrive paths with spaces will break `dt gnai ask`)
- Only one HSD session active at a time per side panel instance

---

## Troubleshooting

### Kerberos Authentication Error

**Symptom:** The bridge starts successfully but `dt gnai ask` returns a Kerberos authentication error.

**Cause:** Windows maintains separate Kerberos credential caches for admin (elevated) and non-admin sessions. If `kinit` was run in an admin PowerShell window, the ticket is **not available** to non-admin processes — and vice versa.

**Fix:** Refresh your Kerberos ticket using one of the following methods, then re-run `run_bridge.ps1` in the same window:

- **Option 1 (easiest):** Lock your Windows screen (`Win+L`) and log back in. Windows will renew your ticket automatically.
- **Option 2:** If MIT Kerberos for Windows is installed, run `kinit` from its install folder:
  ```powershell
  & "C:\Program Files\MIT\Kerberos\bin\kinit.exe"
  .\run_bridge.ps1
  ```
- **Option 3:** Run `dt auth login` if your `dt` CLI supports it.

> **Note:** `kinit` is **not** a built-in Windows command. It requires MIT Kerberos for Windows to be installed.
>
> `run_bridge.ps1` will automatically check for a valid Kerberos ticket at startup and warn you if none is found.

---

## License

Intel Internal — Not for external distribution.

---
---

# SightingAssistant_Chatter（中文說明）

> 一個將 Intel GNAI GPU Sighting 分析功能直接帶入瀏覽器側邊欄的 Chrome Extension。

SightingAssistant_Chatter 是專為 CE 和 debug 工程師設計的前端 Chrome Extension，讓使用者不需要手動下 CLI 指令，就能直接透過瀏覽器使用 Intel GNAI 後端的 AI Sighting 分析功能。Extension 透過本機 Python bridge 連接 GNAI 後端，工程師在瀏覽 HSD 頁面時即可即時取得 AI 分析結果。

---

## 功能特色

- **HSD 分析** — 輸入 HSD ID 即可觸發完整的 sighting 分析流程：讀取文章、附件檢查、問題分類，並產生 7 段式結構化報告。
- **即時串流輸出** — 回應逐字 streaming 顯示，搭配進度指示器。
- **多輪對話** — 可以接續輸出結果持續追問，深入探討分析結果的任何部分。
- **Quick Action 按鈕** — 第一次回應後顯示 4 個快速按鈕：最新狀況與 Action、測試環境、下一步建議、潛在重複問題。
- **Ask / Chat 模式切換** — Ask 模式為單輪問答，Chat 模式支援多輪對話。
- **自動 bridge 管理** — Extension 會自動偵測 bridge 是否在執行，若已設定 Native Messaging 可自動啟動。
- **Debug 連線工具** — 內建「Debug Connection」按鈕，可查看 bridge 狀態、ping 結果與 endpoint 資訊。

---

## 架構

```
Chrome Side Panel（UI）
       ↕  chrome.runtime port
  background.js（Service Worker）
       ↕  HTTP fetch（OpenAI-compatible）
  bridge_server.py（localhost:8775）
       ↕  subprocess
  dt gnai ask/chat ...（SightingAssistantTool CLI）
       ↕
  Intel GNAI Platform（sighting_assistant）
```

| 層級 | 檔案 | 職責 |
|------|------|------|
| UI | `sidepanel.html / sidepanel.js` | 聊天介面、HSD 匯入、串流渲染 |
| Background | `background.js` | Bridge 健康檢查、API 呼叫、串流轉發 |
| Bridge | `bridge/bridge_server.py` | 本機 HTTP 伺服器，將請求轉換為 `dt gnai ask` |
| Launcher | `bridge/native_host_launcher.py` | Native Messaging host，自動啟動 bridge |
| 安裝 | `bridge/install_native_host.ps1` | 在 Chrome 與 Registry 註冊 Native Messaging host |

---

## 前置需求

- **Windows**（Native Messaging launcher 以 PowerShell 為基礎）
- **Google Chrome**
- **Intel `dt` CLI** 且有 GNAI 存取權限（`dt gnai ask "hello"` 可正常執行）
- **Python 3.x**（用於執行 bridge server）
- Intel 公司網路或 VPN

---

## 快速安裝（同事適用）

> 第一次安裝只需以下 3 步驟，不需閱讀下方完整安裝說明。

**開始前確認：** 在終端機執行 `dt gnai ask "hello"` 可以正常回應，即代表環境準備好了。

**步驟一 — Clone repo**

```powershell
git clone https://github.com/SteveChen182/GNAI_GCD_AssistChatter.git C:\Intel\SightingChatter
```

> 目標路徑（`C:\Intel\SightingChatter`）**不能有空格**。

**步驟二 — 啟動 bridge**

```powershell
C:\Intel\SightingChatter\GNAI_AssisChatter\bridge\run_bridge.ps1
```

第一次執行會自動：
- 將 sighting toolkit 複製到 `C:\dt_sighting`
- 更新 `~/.gnai/config.yaml` 指向 `C:\dt_sighting`
- 在 port 8775 啟動本機 bridge server

使用 extension 期間請保持此 PowerShell 視窗開啟。

**步驟三 — 在 Chrome 載入 Extension**

1. 開啟 `chrome://extensions`
2. 開啟右上角 **Developer mode**
3. 點選 **Load unpacked** → 選取 `C:\Intel\SightingChatter\GNAI_AssisChatter`
4. 開啟側邊欄，點選 **Debug Connection** 確認 bridge 顯示 `🟢 Ready`

---

## 完整安裝說明

### 步驟一 — 在 Chrome 載入 Extension

1. 開啟 `chrome://extensions`
2. 開啟 **Developer mode**
3. 點選 **Load unpacked** → 選取 `GNAI_AssisChatter` 資料夾
4. 複製 Chrome 顯示的 **Extension ID**（步驟三會用到）

### 步驟二 — 準備 toolkit（僅第一次）

Bridge 透過 `sighting_assistant` 呼叫 `dt gnai ask`，toolkit 路徑**不能有空格**。

```powershell
New-Item -ItemType Directory -Path C:\dt_sighting -Force
# 將 SightingAssistantTool clone 中的 toolkit.yaml / tools / assistants / src 複製過來
```

在 `~/.gnai/config.yaml` 加入 sighting toolkit 設定：

```yaml
- name: sighting
  type: local
  path: "C:\\dt_sighting"
  url: ""
```

### 步驟三 — 註冊 Native Messaging host

```powershell
cd GNAI_AssisChatter\bridge
.\install_native_host.ps1 -ExtensionId <你的Extension_ID> -Browser chrome
```

### 步驟四 — 重新載入 Extension

在 `chrome://extensions` 點選 SightingAssistant_Chatter 的 **Reload**。

### 步驟五 — 驗證

1. 開啟 extension 側邊欄
2. 點選 ⚙ 齒輪圖示 → **Debug Connection** — 應顯示 `🟢 Ready`

---

## 使用方式

1. 前往 HSD 頁面（`hsdes.intel.com/...`）或任何相關網頁
2. 開啟 SightingAssistant_Chatter 側邊欄
3. 點選 **Import HSD** 自動偵測 URL 中的 HSD ID，或手動輸入
4. 按 **Send** — AI 會執行完整的 sighting 分析流程
5. 使用 Quick Action 按鈕或直接輸入問題繼續對話

> 如要跳過附件分析並快速取得摘要：
> _"Please give me a punchline summary of HSD XXXXXXXXXX and skip attachment check"_

---

## Bridge 設定

所有設定透過 `bridge/run_bridge.ps1` 中的環境變數控制：

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `GNAI_BRIDGE_HOST` | `127.0.0.1` | Bridge 監聽位址 |
| `GNAI_BRIDGE_PORT` | `8775` | Bridge 監聽 port |
| `GNAI_BRIDGE_TIMEOUT` | `360` | `dt gnai ask` 逾時秒數 |
| `GNAI_BRIDGE_DEFAULT_ASSISTANT` | `sighting_assistant` | 預設 GNAI assistant |
| `GNAI_BRIDGE_DT_PATH` | _(自動偵測)_ | `dt.exe` 完整路徑（若不在 PATH 中） |
| `GNAI_BRIDGE_API_KEY` | _(空白)_ | 選用的 bridge 認證 token |
| `GNAI_BRIDGE_DEBUG` | `1` | 啟用 debug 日誌 |
| `GNAI_BRIDGE_ECHO_RESPONSE` | `1` | 將回應輸出至 stdout |

---

## 檔案結構

```
GNAI_AssisChatter/
├── manifest.json               # Chrome Extension MV3 設定
├── background.js               # Service worker — bridge 健康檢查、API 呼叫、串流轉發
├── sidepanel.html              # 側邊欄 UI
├── sidepanel.js                # 聊天邏輯、HSD session、串流渲染
└── bridge/
    ├── bridge_server.py        # 本機 HTTP bridge（OpenAI-compatible endpoints）
    ├── run_bridge.ps1          # Bridge 啟動腳本（設定環境變數 + 同步 toolkit）
    ├── native_host_launcher.py # Native Messaging host — 自動啟動 bridge
    ├── install_native_host.ps1 # 在 Chrome 與 Windows Registry 註冊 native host
    └── native_host_launcher.cmd# CMD wrapper
```

---

## 已知限制

- 僅支援 Windows（Native Messaging launcher 以 PowerShell 為基礎）
- 需要 Intel 公司網路或 VPN 才能存取 GNAI 與 HSDES
- Toolkit 路徑**不能有空格**（OneDrive 路徑含空格會導致 `dt gnai ask` 失敗）
- 每個側邊欄 instance 同時只能有一個 HSD session

---

## 問題排除

### Kerberos 認證錯誤

**症狀：** Bridge 啟動正常，但 `dt gnai ask` 回傳 Kerberos 認證錯誤。

**原因：** Windows 對 admin（elevated）和一般 session 分別維護獨立的 Kerberos credential cache。若 `kinit` 是在 admin PowerShell 執行，一般 session 的 process **無法存取**該 ticket，反之亦然。

**解法：** 用以下任一方式刷新 Kerberos ticket，然後在同一個視窗重新執行 `run_bridge.ps1`：

- **選項一（最簡單）：** 按 `Win+L` 鎖定螢幕再登入，Windows 會自動更新 ticket。
- **選項二：** 若有安裝 MIT Kerberos for Windows，從安裝目錄執行 `kinit`：
  ```powershell
  & "C:\Program Files\MIT\Kerberos\bin\kinit.exe"
  .\run_bridge.ps1
  ```
- **選項三：** 若 `dt` CLI 支援，執行 `dt auth login`。

> **注意：** `kinit` **不是** Windows 內建指令，需要安裝 MIT Kerberos for Windows 才能使用。
>
> `run_bridge.ps1` 啟動時會自動檢查 Kerberos ticket 是否有效，若無效會顯示警告。

---

## 授權

Intel 內部使用 — 禁止對外發布。