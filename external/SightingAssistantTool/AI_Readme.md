# Sighting Assistant Tool（SAT）— 完整專案分析

> **版本日期：** 2026-04-28 | **授權：** GNU GPLv3  
> **儲存庫：** `intel-sandbox/SightingAssistantTool`

---

## 目錄

1. [專案簡介](#1-專案簡介)
2. [目錄結構](#2-目錄結構)
3. [核心概念](#3-核心概念)
4. [六階段執行流程](#4-六階段執行流程)
5. [工具清單與功能說明](#5-工具清單與功能說明)
6. [Python 原始碼模組](#6-python-原始碼模組)
7. [外部 Toolkit 整合](#7-外部-toolkit-整合)
8. [檔案產出與資料流](#8-檔案產出與資料流)
9. [支援的 HSD 分類類別](#9-支援的-hsd-分類類別)
10. [安裝與使用方法](#10-安裝與使用方法)
11. [日常更新流程](#11-日常更新流程)
12. [除錯與疑難排解](#12-除錯與疑難排解)
13. [注意事項](#13-注意事項)

---

## 1. 專案簡介

**Sighting Assistant Tool (SAT)** 是基於 Intel 內部 **GNAI 平台**（GenAI 平台）的 **Local Toolkit**，專為 GPU 圖形除錯工程師設計。它透過 AI 驅動的分析流程，幫助工程師加速 **HSD sighting（缺陷追蹤）** 的問題分類、日誌分析和報告產生。

### 核心能力

| 能力 | 說明 |
|------|------|
| **HSD 文章讀取** | 自動從 HSD-ES API 抓取 sighting 的標題、描述、評論等完整資訊 |
| **附件自動下載分析** | 下載 HSD 附件（ZIP、7z、ETL、日誌等），自動解壓並分類 |
| **智慧分類** | 將 sighting 自動歸類到 20 種問題類型之一 |
| **多種日誌分析器** | GOP UEFI 日誌、PTAT 監控、GfxPnp 指標、ETL 追蹤、Burnin 測試日誌 |
| **外部 Toolkit 整合** | 自動呼叫 Sherlog（GDHM 分析）和 DisplayDebugger（顯示驅動分析） |
| **RAG 知識檢索** | 查詢 DFD Checklist 和最佳已知方法（BKM） |
| **相似 HSD 搜尋** | 找出歷史上相似的 sighting 作為參考 |
| **HTML 報告產生** | 自動生成結構化分析報告 |

---

## 2. 目錄結構

```
SightingAssistant_GitHub/
│
├── toolkit.yaml                        ← GNAI Toolkit 設定檔（名稱、環境變數、依賴）
├── CLAUDE.md                           ← 開發指南（供 AI 參考的完整文件）
├── SIGHTING_ARCHITECTURE.md            ← 技術架構詳細說明
├── README.md                           ← 原始英文安裝指南
├── LICENSE                             ← GNU GPLv3 授權
│
├── assistants/                         ← GNAI Assistant 定義
│   ├── sighting_assistant.yaml         ← 主 Assistant（核心排程器）
│   └── sighting_report_helper.yaml     ← 報告組裝 Assistant
│
├── tools/                              ← GNAI Tool YAML 定義（共 16 個工具）
│   ├── sighting_read_article.yaml
│   ├── sighting_attachments.yaml
│   ├── sighting_get_category.yaml
│   ├── sighting_extract_attachment.yaml
│   ├── sighting_gop_analyzer.yaml
│   ├── sighting_native_etl_analyzer.yaml
│   ├── sighting_displaydebugger.yaml
│   ├── sighting_ptat_analyzer.yaml
│   ├── sighting_gfxpnp_analyzer.yaml
│   ├── sighting_sherlog_sync.yaml
│   ├── sighting_burnin_log_analyzer.yaml
│   ├── sighting_checklist_analyzer.yaml
│   ├── sighting_similarity_search.yaml
│   ├── sighting_rag_search.yaml
│   ├── sighting_report_json_builder.yaml
│   └── sighting_render_sat_report.yaml
│
├── src/                                ← Python 實作原始碼
│   ├── read_article.py                 ← HSD 文章讀取
│   ├── check_attachments.py            ← 附件下載、解壓、分類
│   ├── extract_attachment.py           ← 隨選解壓附件
│   ├── hsdes.py                        ← HSD-ES REST API 封裝
│   ├── etl_classifier.py              ← ETL 分類與解析
│   ├── log_file_analyzer.py           ← GOP/PTAT/GfxPnp 日誌分析（核心）
│   ├── native_etl_analyzer.py         ← 原生 ETL 預分析
│   ├── checklist_analyzer.py          ← DFD Checklist 檢查
│   ├── sighting_rag_search.py         ← RAG 向量搜尋
│   ├── similarity_search.py           ← 相似 HSD 搜尋
│   ├── displaydebugger_subprocess.py  ← DisplayDebugger 子程序呼叫
│   ├── sherlog_subprocess.py          ← Sherlog 子程序呼叫
│   ├── render_sat_report.py           ← JSON → HTML 報告渲染
│   ├── artifacts/
│   │   └── utils.py                   ← 關鍵字搜尋工具
│   ├── utils/
│   │   ├── archive_utils.py           ← 壓縮檔處理工具
│   │   └── log_utils.py               ← 日誌處理基底類別與工具函式
│   ├── bin/
│   │   └── tracefmt.exe               ← Windows ETL 格式轉換工具
│   └── manifests/                     ← ETW manifest 檔案
│       ├── igdEtw_Krnl.man
│       ├── IntelGfxDisplay.man
│       └── ... （共 5 個）
│
├── accuracy_test/                     ← 測試框架
│   ├── README.md
│   └── feedback.ipynb                 ← Jupyter 測試回饋筆記本
│
└── assets/                            ← 架構圖
    ├── SAT_Diagram_v1.svg
    └── SAT_Diagram_v2.svg
```

---

## 3. 核心概念

### 3.1 GNAI 平台

GNAI 是 Intel 內部的 GenAI 平台，支援 OpenAI + Anthropic/Claude 模型，提供 RAG（檢索增強生成）功能。SAT 作為一個 **Local Toolkit** 在 GNAI 上運行。

### 3.2 Toolkit → Assistant → Tool 架構

```
Toolkit (toolkit.yaml)
  └── Assistant (assistants/*.yaml)    ← AI 代理人，決定呼叫哪些工具
        ├── Tool (tools/*.yaml)         ← Command Tool：執行 Python 腳本
        ├── Tool (tools/*.yaml)         ← Agent Tool：用 LLM 做分析
        └── Sub-Assistant               ← 子代理人（如報告生成器）
```

- **Command Tool**：執行 shell 指令（Python 腳本），回傳 stdout/stderr
- **Agent Tool**：將資料餵給 LLM，回傳 LLM 分析結果
- **Assistant**：AI 代理人，根據 prompt 決定何時呼叫哪些 tool

### 3.3 兩個 Assistant

| Assistant | 模型 | 職責 |
|-----------|------|------|
| `sighting_assistant` | claude-4-6-sonnet | **主排程器**：執行完整 6 階段分析流程 |
| `sighting_report_helper` | claude-4-5-sonnet | **報告產生器**：將分析結果組裝成結構化 JSON |

---

## 4. 六階段執行流程

這是整個 SAT 的核心運作流程，由 `sighting_assistant` 依序執行：

```
使用者輸入 HSD ID
        │
        ▼
┌─────────────────────────────────────────┐
│  PHASE 1：資料收集                        │
│  ┌─→ sighting_read_article（讀 HSD 文章）│
│  ├─→ sighting_attachments（下載附件）     │
│  └─→ sighting_get_category（AI 分類）     │
└─────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│  PHASE 2：建立附件選擇選單                │
│  列出所有附件及其包含的檔案                │
│  讓使用者選擇要分析哪些項目                │
└─────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│  PHASE 3：互動式逐項分析                  │
│  根據使用者選擇，依檔案類型呼叫：          │
│  ├─ GOP 日誌 → sighting_gop_analyzer    │
│  ├─ ETL 檔案 → sighting_native_etl_analyzer │
│  │              + sighting_displaydebugger   │
│  ├─ GDHM dumps → sighting_sherlog_sync  │
│  ├─ PTAT CSV → sighting_ptat_analyzer   │
│  ├─ GfxPnp CSV → sighting_gfxpnp_analyzer │
│  ├─ Burnin 日誌 → sighting_burnin_log_analyzer │
│  └─ 壓縮檔 → sighting_extract_attachment │
└─────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│  PHASE 3 GATE：阻斷式互動步驟            │
│  ├─ 3A: Wiki 搜尋查詢（等使用者回應）     │
│  └─ 3B: 相似 HSD 搜尋（等使用者回應）     │
│  ★ 必須等使用者回應才能繼續               │
└─────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│  PHASE 4：結構化報告 JSON 建構            │
│  ├─ sighting_rag_search（DFD Checklist） │
│  ├─ sighting_rag_search（BKM 查詢）      │
│  └─ sighting_report_json_builder         │
│     （或呼叫 sighting_report_helper）     │
└─────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│  PHASE 5：HTML 報告渲染                   │
│  sighting_render_sat_report               │
│  → SAT_<HSD_ID>_Output/SAT_analysis_report.html │
└─────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│  PHASE 6：純文字摘要                      │
│  在聊天視窗中輸出最終分析摘要              │
└─────────────────────────────────────────┘
```

---

## 5. 工具清單與功能說明

### 5.1 Command Tools（執行 Python 腳本）

| 工具 | 腳本 | 功能 |
|------|------|------|
| `sighting_read_article` | `read_article.py` | 從 HSD-ES API 讀取 sighting 的標題、描述、評論，輸出到 `hsd_info_file` |
| `sighting_attachments` | `check_attachments.py` | 下載所有 HSD 附件（8 並行），解壓 ZIP/7z，分類 ETL/LOG/CSV，建立索引檔 |
| `sighting_extract_attachment` | `extract_attachment.py` | 隨選解壓指定壓縮檔，更新索引 |
| `sighting_native_etl_analyzer` | `native_etl_analyzer.py` | 用 `tracefmt.exe` 解析 ETL，識別類型（BootTrace/WPT/Display/GPUView） |
| `sighting_displaydebugger` | `displaydebugger_subprocess.py` | 在子程序中呼叫 DisplayDebugger toolkit 分析顯示驅動日誌 |
| `sighting_ptat_analyzer` | `log_file_analyzer.py ptat` | 分析 PTAT Monitor CSV，提取 GFX 頻率/節流事件，生成圖表（PNG） |
| `sighting_gfxpnp_analyzer` | `log_file_analyzer.py gfxpnp` | 分析 GfxPnp (GTMetrics) CSV，生成多欄圖表（PNG） |
| `sighting_sherlog_sync` | `sherlog_subprocess.py` | 在子程序中呼叫 Sherlog toolkit 分析 GDHM dumps |
| `sighting_checklist_analyzer` | `checklist_analyzer.py` | 檢查 DFD 合規性 |
| `sighting_similarity_search` | `similarity_search.py` | 搜尋歷史上相似的 HSD sighting |
| `sighting_rag_search` | `sighting_rag_search.py` | 透過 RAG API 查詢 DFD Checklist 和 BKM 最佳實踐 |
| `sighting_render_sat_report` | `render_sat_report.py` | 將 JSON 報告渲染為 HTML |

### 5.2 Agent Tools（用 LLM 分析）

| 工具 | 功能 |
|------|------|
| `sighting_get_category` | 讓 LLM 將 HSD 分類到 20 種類別之一 |
| `sighting_gop_analyzer` | 讓 LLM 分析 GOP UEFI 日誌（基於 `log_file_analyzer.py` 的結構化輸出） |
| `sighting_burnin_log_analyzer` | 讓 LLM 分析 Burnin 測試日誌，識別 GPGPU 錯誤模式 |
| `sighting_report_json_builder` | 讓 LLM 將所有分析結果組裝成結構化 JSON |

---

## 6. Python 原始碼模組

### 6.1 資料擷取層

| 模組 | 說明 |
|------|------|
| **`hsdes.py`** | HSD-ES REST API 封裝類別，使用 Kerberos 認證。提供 `read_article`、`get_comments_list`、`get_attachments_list`、`download_attachment`、`similarity_search` 等方法 |
| **`read_article.py`** | 呼叫 `HSDESAPI` 讀取 HSD 文章欄位和評論，寫入 `hsd_info_file` |
| **`similarity_search.py`** | 呼叫 `HSDESAPI.similarity_search()` 找相似 HSD |

### 6.2 附件處理層

| 模組 | 說明 |
|------|------|
| **`check_attachments.py`** | 核心附件處理（600+ 行）：8 並行下載、ZIP/7z 解壓、檔案分類（ETL/LOG/TXT/CSV）、偵測 split archive（.7z.001）、建立多個索引 JSON、複製日誌到 `persistent_logs/` |
| **`extract_attachment.py`** | 隨選解壓：只在使用者要求時才解壓特定壓縮檔，必要時從 HSD 重新下載缺失的分割檔 |
| **`utils/archive_utils.py`** | 壓縮檔工具：peek 預覽、manifest 讀寫、解壓狀態追蹤、split archive 處理、7z CLI 回退 |

### 6.3 日誌分析層

| 模組 | 說明 |
|------|------|
| **`log_file_analyzer.py`** | 最大的模組（1500+ 行），包含三個分析器：|
| → `GOPLogProcessor` | 用 40+ regex 解析 GOP UEFI 日誌，分析 Link Training、Clock Recovery、Mode Setting、Panel Power 等事件，輸出 Markdown 表格 |
| → `PTATLogProcessor` | 分析 PTAT Monitor CSV，提取 GFX 頻率、clip reason、throttle 事件，生成深色主題 matplotlib 圖表 |
| → `GfxPnpLogProcessor` | 分析 GfxPnp GTMetrics CSV，生成多欄圖表（RenderFreq、Bias 等） |
| **`etl_classifier.py`** | ETL 分類器（500+ 行）：用 `tracefmt.exe` 轉換 ETL 為文字，偵測 ETL 類型、驅動版本、pipe underrun 模式 |
| **`native_etl_analyzer.py`** | 從 `all_etl_files.json` 載入目標 ETL，呼叫 `etl_classifier` 分析 |

### 6.4 外部整合層

| 模組 | 說明 |
|------|------|
| **`displaydebugger_subprocess.py`** | 子程序呼叫 DisplayDebugger toolkit，在獨立 CMD 視窗中執行 `gnai ask --assistant=displaydebugger`，輸出移到 `SAT_<HSD>/DisplayDebugger_Output/` |
| **`sherlog_subprocess.py`** | 子程序呼叫 Sherlog toolkit，驗證 10 位 GDHM ID，在獨立 CMD 視窗中執行，輸出移到 `SAT_<HSD>/Sherlog_Output/` |

### 6.5 報告與搜尋層

| 模組 | 說明 |
|------|------|
| **`sighting_rag_search.py`** | HTTP + Basic Auth 呼叫 GNAI RAG API，支援並行多查詢，profile 固定 `gpu-debug`，含重試機制（3 次指數退避） |
| **`render_sat_report.py`** | 將結構化 JSON 轉換為完整 HTML 報告（含樣式表格），處理各種 legacy 資料格式，輸出到 `SAT_<HSD>/SAT_analysis_report.html` |

### 6.6 工具函式

| 模組 | 說明 |
|------|------|
| **`utils/log_utils.py`** | `LogProcessor` 抽象基底類別、`get_sat_output_dir()` 路徑管理、日誌檔案載入、多種結果合併函式 |
| **`artifacts/utils.py`** | 關鍵字搜尋工具，用 regex 在 HSD 欄位中做 word boundary 搜尋 |

---

## 7. 外部 Toolkit 整合

SAT 與兩個外部 GNAI Toolkit 整合，使用 **子程序模式**（在獨立 CMD 視窗中呼叫 `gnai ask`）：

### 7.1 Sherlog — GDHM Dump 分析

```
觸發條件：HSD 附件或描述中包含 GDHM dump ID（嚴格 10 位數字）
呼叫方式：gnai ask "Analyze GDHM dump ID {gdhm_id}" --assistant=sherlog_complex_analyzer
輸出位置：SAT_<HSD_ID>_Output/Sherlog_Output/sherlog_{gdhm_id}.md
```

### 7.2 DisplayDebugger — 顯示驅動日誌分析

```
觸發條件：偵測到 GOP 日誌（含 IntelGOP/IntelPEIM 標記）或顯示相關 ETL
呼叫方式：gnai ask --assistant=displaydebugger "analyze the display {gop/etl} file '{path}' and check {focus}"
分析焦點：由 sighting_assistant 根據 HSD 內容智慧決定（如顯示偵測、連結訓練、HDCP、電源等）
輸出位置：SAT_<HSD_ID>_Output/DisplayDebugger_Output/
```

---

## 8. 檔案產出與資料流

### 8.1 暫存工作區（GNAI_TEMP_WORKSPACE）— 聊天結束後刪除

```
$GNAI_TEMP_WORKSPACE/
├── hsd_info_file                       ← HSD 文章資訊
├── attachment_info_file                ← 附件分析結果
├── all_log_txt_trace_csv_files.json    ← 所有日誌/文字/CSV 檔案索引
├── all_etl_files.json                  ← 所有 ETL 檔案索引
├── archive_manifest.json              ← 壓縮檔內容清單
├── extracted_<attachment_id>/          ← 解壓後的附件目錄
└── persistent_logs/                    ← 個別日誌檔案（加 attachment_id 前綴）
    ├── <attachment_id>_<log_1.txt>
    └── <attachment_id>_<log_n.txt>
```

### 8.2 持久輸出（SAT_\<HSD_ID\>_Output）— 永久保留

```
$GNAI_TOOLKIT_DIRECTORY/SAT_<HSD_ID>_Output/
├── raw_attachments/                    ← 原始 HSD 下載檔案
├── extracted_<attachment_id>/          ← 大型解壓內容
├── PTAT_logs_plots/                    ← PTAT 分析圖表 (PNG)
├── GfxPnp_logs_plots/                  ← GfxPnp 分析圖表 (PNG)
├── DisplayDebugger_Output/             ← DisplayDebugger 文字輸出
├── Sherlog_Output/                     ← Sherlog Markdown 輸出
└── SAT_analysis_report.html            ← ★ 最終 HTML 分析報告
```

### 8.3 資料流概述

```
HSD-ES API
    │
    ├──→ hsd_info_file（文章 + 評論）
    │
    ├──→ attachment_info_file（附件清單 + 分類）
    │       │
    │       ├──→ persistent_logs/（解壓後的個別日誌）
    │       ├──→ all_log_txt_trace_csv_files.json（日誌索引）
    │       └──→ all_etl_files.json（ETL 索引）
    │
    ├──→ 各分析工具讀取索引 → 執行分析
    │       ├── GOP 分析 → Markdown 表格
    │       ├── PTAT 分析 → JSON + PNG 圖表
    │       ├── ETL 分析 → JSON（類型 + 驅動資訊）
    │       ├── Sherlog → Markdown 報告
    │       └── DisplayDebugger → 文字報告
    │
    ├──→ RAG 搜尋 → DFD Checklist + BKM
    │
    ├──→ 相似 HSD 搜尋 → 相似案例列表
    │
    └──→ 所有結果 → report_json_builder → JSON
              │
              └──→ render_sat_report → HTML 報告
```

---

## 9. 支援的 HSD 分類類別

`sighting_get_category` Agent Tool 會將每個 HSD 分類到以下 20 種類別之一：

| # | 類別 | 說明 |
|---|------|------|
| 1 | Display | 顯示輸出、解析度、多螢幕 |
| 2 | Media Decode | 影片/音訊解碼 |
| 3 | Media Encode | 影片/音訊編碼 |
| 4 | 3D/Gaming | 3D 渲染、遊戲效能 |
| 5 | GPGPU/Compute | GPU 計算（OpenCL、Level Zero） |
| 6 | Power/Thermal | 電源管理、溫度 |
| 7 | BSOD/TDR/Hang | 藍屏、TDR 逾時、當機 |
| 8 | Driver Installation | 驅動安裝問題 |
| 9 | Yellow Bang | 裝置管理員驚嘆號 |
| 10 | Performance | 效能退化 |
| 11 | Memory | 記憶體洩漏/損壞 |
| 12 | Security | 安全漏洞 |
| 13 | Firmware/GOP | UEFI/GOP 韌體 |
| 14 | HDR | 高動態範圍 |
| 15 | HDCP/DRM | 內容保護 |
| 16 | Audio | 音訊問題 |
| 17 | Wireless Display | 無線顯示（Miracast） |
| 18 | Container/VM | 虛擬化 |
| 19 | ML/AI Workloads | 機器學習工作負載 |
| 20 | Other | 其他/無法分類 |

---

## 10. 安裝與使用方法

### 10.1 前置需求

- **GNAI CLI (`dt`)** 已安裝並啟用
- Intel 企業網路環境（Kerberos 認證）
- Windows 系統（`tracefmt.exe` 為 Windows 二進位檔）
- Python 3.11+（由 GNAI 自動管理虛擬環境）

### 10.2 安裝步驟

```bash
# 1. 啟用 GNAI 擴充
dt extensions enable gnai

# 2. Clone 專案
git clone https://github.com/intel-sandbox/SightingAssistantTool.git sighting
cd sighting

# 3. 註冊 Toolkit（會自動建立 Python venv 並安裝依賴）
dt gnai toolkits register .

# 4.（選用）驗證安裝
dt gnai toolkits validate .
```

### 10.3 基本使用

```bash
# 啟動互動式聊天
dt gnai chat --assistant sighting_assistant

# 啟動後輸入：
> Assist me with HSD ID 15018275324
```

### 10.4 進階使用

```bash
# 詳細模式（顯示工具呼叫細節）
dt gnai chat --assistant sighting_assistant -v
```

### 10.5 互動流程

1. 輸入 HSD ID
2. SAT 自動讀取文章、下載附件、分類問題
3. 系統顯示附件選單，選擇要分析的項目
4. SAT 依序分析選定項目（可能開啟子視窗執行 Sherlog/DisplayDebugger）
5. 系統詢問是否要進行 Wiki 搜尋和相似 HSD 搜尋
6. SAT 生成結構化報告
7. 最終 HTML 報告存放在 `SAT_<HSD_ID>_Output/SAT_analysis_report.html`

---

## 11. 日常更新流程

```bash
# 進入專案目錄
cd SightingAssistant_GitHub

# 拉取最新版本
git pull

# 如果 toolkit 已用此路徑註冊，需重新註冊
dt gnai toolkits register .

# 如果出現 "already registered" 錯誤，需先取消再重新註冊
# 或直接在已註冊的路徑下 git pull
```

```bash
# 升級 GNAI CLI 本身
dt gnai update
```

---

## 12. 除錯與疑難排解

### 12.1 pip 安裝失敗

在 `%AppData%\pip\pip.ini` 新增：

```ini
[global]
proxy = http://proxy-png.intel.com:912
extra-index-url = https://pypi.org/simple/
```

### 12.2 SSL 憑證錯誤

Intel 內部憑證可能導致 `certifi` 驗證失敗。程式碼中已使用 `verify=False` 繞過（僅限 Intel 內部網路）。

### 12.3 Linux Kerberos 認證失敗

```bash
kinit <username>    # 取得 Kerberos token
klist               # 驗證 token
```

### 12.4 Toolkit 已註冊衝突

```
Error: Toolkit with name "sighting" is already registered at C:\dt_sighting
```

代表 `sighting` 這個名稱已有另一個路徑註冊。可以在已註冊的路徑下更新，或先移除再重新註冊。

### 12.5 `default_*` 工具找不到

GNAI v1.153.8 後內建工具從 `default_*` 改名為 `system_*`。**不需要**在 assistant 的 `tools:` 列表中列出系統工具（它們會自動注入）。

---

## 13. 注意事項

### 13.1 環境限制

- **僅支援 Windows**：`tracefmt.exe` 和子程序呼叫（`cmd /c`）皆為 Windows 專用
- **需要 Intel 內網**：HSD-ES API 和 Kerberos 認證需要 Intel 企業網路
- **需要 GNAI 帳號**：`INTEL_USERNAME` 和 `INTEL_PASSWORD` 必須設定

### 13.2 GNAI Temp Workspace

- `$GNAI_TEMP_WORKSPACE` 在聊天結束後會被刪除
- 不要在裡面存放需要保留的資料
- 需要保留的產出都寫入 `SAT_<HSD_ID>_Output/`

### 13.3 外部 Toolkit 依賴

- **Sherlog** 和 **DisplayDebugger** 必須分別註冊才能使用
- 如果未安裝，對應的分析步驟會失敗但不影響其他分析

### 13.4 Context Window 管理

- 大型輸出（JSON、日誌內容）寫入檔案而非 stdout
- stdout 只輸出檔案路徑，避免消耗 LLM token
- 這是 GNAI 最佳實踐

### 13.5 Split Archive 處理

- 程式支援分割壓縮檔（.7z.001, .002, ...）
- 會自動偵測和下載所有分割部分
- 如果 Python `py7zr` 處理失敗，會回退使用系統 7z CLI

### 13.6 GOP 分析觸發條件

- 只有檔名包含 `gop`、`uefi`、`preos`、`bios`、`intelgop`、`intelugop`、`intelpeim`、`boot` 的日誌才會觸發 GOP 分析器
- STC 系統追蹤日誌（如 `*_STC.log`）**不是** GOP 日誌，不會觸發

### 13.7 Phase 3 Gate

- Phase 3 的 Wiki 查詢和相似 HSD 搜尋是**阻斷式**的
- LLM 必須等使用者回應後才能進入 Phase 4
- 這是為了確保互動品質而特別設計的

---

> 本文件由 AI 自動分析產生，基於 2026-04-28 的專案原始碼。如有更新請重新分析。
