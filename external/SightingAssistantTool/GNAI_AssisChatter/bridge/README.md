# SightingAssistant_Chatter Bridge (Python)

這個 bridge 讓 Chrome extension 可以透過 localhost 呼叫 `dt gnai ask --assistant ...`。

## 1. 功能

1. 提供 OpenAI-compatible 端點:
- `POST /v1/chat/completions`
- `POST /chat/completions`

2. 從 request 取出最後一筆 user message，轉成:
- `dt gnai ask "<prompt>" --assistant <assistant>`

3. 回傳 OpenAI-compatible `choices[0].message.content` 給 extension。

4. 提供健康檢查:
- `GET /health`
- `GET /v1/health`

## 2. 啟動

在此資料夾執行:

```powershell
.\run_bridge.ps1
```

或直接:

```powershell
python .\bridge_server.py
```

預設監聽:
- `http://127.0.0.1:8775`

## 3. 環境變數

- `GNAI_BRIDGE_HOST` (預設 `127.0.0.1`)
- `GNAI_BRIDGE_PORT` (預設 `8775`)
- `GNAI_BRIDGE_TIMEOUT` (預設 `240` 秒)
- `GNAI_BRIDGE_DEFAULT_ASSISTANT` (預設 `sighting_assistant`)
- `GNAI_BRIDGE_API_KEY` (可選，設定後需 Bearer token)
- `GNAI_BRIDGE_DT_PATH` (可選，若 PATH 找不到 dt，填入 dt.exe 絕對路徑)

## 4. Extension 端模式（SightingAssistant_Chatter）

Extension 已是純 bridge 模式，固定呼叫:

- Base URL: `http://127.0.0.1:8775/v1`
- Assistant: `sighting_assistant`

不需要 options 設定頁；若 bridge 設定 `GNAI_BRIDGE_API_KEY`，才需在 extension 端另外加上對應 Bearer token（目前預設不啟用）。

## 5. 啟用 extension 自動啟 bridge（Native Messaging）

1. 在瀏覽器 `chrome://extensions` 找到 extension ID。
2. 進入此資料夾，執行:

```powershell
.\install_native_host.ps1 -ExtensionId <你的extension_id> -Browser chrome
```

3. 重新啟動瀏覽器後，extension 會在開啟時先做 health check。
4. 若 bridge 未啟動，extension 會透過 native host 執行 `run_bridge.ps1`，再輪詢確認連線。

## 6. 測試

健康檢查:

```powershell
curl http://127.0.0.1:8775/health
```

最小 chat 測試:

```powershell
curl -X POST http://127.0.0.1:8775/v1/chat/completions -H "Content-Type: application/json" -d "{\"model\":\"gpt-4o\",\"assistant\":\"sighting_assistant\",\"messages\":[{\"role\":\"user\",\"content\":\"Please assist with the HSD id 14025723680\"}]}"
```

## 7. 注意事項

1. 需要本機可執行 `dt` 指令。
2. bridge 只作 CLI 轉接，完整權限與資料治理仍需遵守公司規範。
3. 生產環境建議啟用 `GNAI_BRIDGE_API_KEY`，避免本機未授權呼叫。

若看到錯誤 `dt command not found`，請擇一處理：

1. 安裝/修復 dt CLI 並確認 `dt --version` 可執行。
2. 在 `run_bridge.ps1` 解除註解並設定 `GNAI_BRIDGE_DT_PATH` 指向 `dt.exe`。
3. 重新啟動 bridge，再用 sidepanel 的 `Debug 連線` 驗證。
