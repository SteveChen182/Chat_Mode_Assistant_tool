# History 功能說明

## 儲存結構

存放於 `chrome.storage.local`，key 為 `hsdHistory`，格式為陣列：

```json
[
  {
    "hsdId": "22022242269",
    "conversationId": "22022242269-1713180000000",
    "messages": [
      { "role": "user", "content": "..." },
      { "role": "assistant", "content": "..." }
    ],
    "timestamp": 1713180000000
  }
]
```

- 最多保留 **5 筆**（`MAX_HISTORY = 5`）
- 以 `hsdId` 去重：同一個 HSD 存入時會覆蓋舊的（移到最前面）
- 每次存入都會重新排序：最新的在最前

---

## 存入條件（`saveSessionToHistory`）

```
if (!activeHsdId || messages.length === 0) return;
```

- 必須有 `activeHsdId`（目前有鎖定一個 HSD）
- 必須至少有 1 則訊息
- 兩者缺一不補，不會存空白/無 HSD 的對話

---

## 存入觸發點

### 1. 每輪 AI 回覆完成後（主要路徑）
- **位置**：`sendMessage()` — assistant message push 完畢後
- **行為**：fire-and-forget（不 await），不阻塞 UI
- **說明**：只要 bridge 回傳完整回覆，就立即更新一次 history

### 2. 點擊 Clear 按鈕
- **位置**：`clearChat()` 開頭
- **行為**：`await`，存完才清除對話

### 3. Import 新 HSD 覆蓋當前對話
- **位置**：`importHsdIdFromWebpage()` — 使用者確認覆蓋後
- **行為**：`await`，存完才清除舊 session

### 4. 從 History 還原舊對話
- **位置**：`restoreSession()` 開頭
- **行為**：`await`，先存當前，再切換到指定舊 session

### 5. 切換到「載入網頁」模式
- **位置**：`loadPageContent()` — response 成功後，清除 messages 前
- **行為**：`await`，存完才重置狀態

### 6. 切換到「貼上剪貼簿」模式
- **位置**：`loadClipboard()` — 內容讀取成功後，清除 messages 前
- **行為**：`await`，存完才重置狀態

### 7. 側邊欄被隱藏或關閉（頁面進入背景）
- **位置**：`document.addEventListener("visibilitychange")`
- **條件**：`document.visibilityState === "hidden"`
- **行為**：fire-and-forget（不能 await，頁面即將卸載）

### 8. 關閉瀏覽器 / 切換 extension / 頁面卸載
- **位置**：`window.addEventListener("pagehide")`
- **行為**：fire-and-forget（不能 await，頁面即將卸載）
- **說明**：`pagehide` 在 Chrome Extension side panel 環境比 `beforeunload` 更可靠

---

## 讀取觸發點

### 打開 History 選單
- **位置**：`openHistoryMenu()` — 點擊 ↺ 按鈕時
- **行為**：從 `chrome.storage.local` 讀取 `hsdHistory`，動態建立 DOM 清單
- 每筆顯示：HSD ID（粗體）+ Conversation ID（灰色小字）

---

## 還原觸發點

### 點擊 History 項目
- **位置**：`restoreSession(entry)` — 點擊 history-item 時
- **流程**：
  1. `await saveSessionToHistory()`（先存當前 session）
  2. 取消進行中的串流
  3. 清除 `messages`, `pageContent`, `activeHsdId`, `activeConversationId`
  4. 從 `entry` 還原 `hsdId`, `conversationId`, `messages`
  5. 重新渲染所有訊息
  6. 顯示系統訊息：`Restored session: HSD {hsdId} ({n} messages)`

---

## 關閉選單觸發點

| 觸發 | 行為 |
|---|---|
| 點擊選單外部任意處 | `closeHistoryMenu()` |
| 按 `Escape` 鍵 | `closeHistoryMenu()` + `closeSettingsMenu()` |
| 再次點擊 ↺ 按鈕（已開啟時） | `closeHistoryMenu()` |
