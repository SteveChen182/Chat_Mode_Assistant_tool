# Chat Mode Assistant — Architecture Overview

## System Flow Diagram

```mermaid
flowchart TB
    subgraph Chrome["Chrome Browser"]
        HSD["HSD-ES Web Page<br>(hsdes.intel.com)"]
        subgraph Ext["Chrome Extension"]
            SP["sidepanel.js<br>UI / Markdown Renderer"]
            BG["background.js<br>Service Worker"]
            SP <-->|"chrome.runtime<br>port messages"| BG
            SP -->|"Import HSD<br>(content script)"| HSD
        end
    end

    subgraph Bridge["Bridge Server (Python, port 8776)"]
        HTTP["HTTP Endpoints<br>/session/start, /send, /stop"]
        SSE["SSE Stream<br>/session/stream"]
        PTY["ConPTY Manager<br>(pywinpty)"]
        PAUSE["Pause Window<br>Auto-Closer"]
        HTTP --> PTY
        PTY --> SSE
        PTY --> PAUSE
    end

    subgraph DT["dt CLI Process"]
        GNAI["dt gnai chat --json<br>--assistant sighting_assistant<br>--conversation-id CID"]
    end

    subgraph Cloud["GNAI Platform (gnai.intel.com)"]
        LLM["LLM<br>(Claude)"]
        subgraph Tools["SAT Custom Tools (15)"]
            T1["read_article"]
            T2["sherlog_analyze"]
            T3["displaydebugger"]
            T4["wiki_search"]
            T5["similar_hsd"]
            T6["... etc"]
        end
        LLM <--> Tools
    end

    BG <-->|"HTTP POST<br>(start/send/stop)"| HTTP
    BG <-->|"SSE GET<br>(answer/tool_start/<br>usage/ready/error)"| SSE
    PTY <-->|"stdin/stdout<br>via ConPTY"| GNAI
    GNAI <-->|"WebSocket<br>(HTTPS)"| LLM
```

## Data Flow — User Sends HSD ID

```mermaid
sequenceDiagram
    participant U as User
    participant SP as Sidepanel
    participant BG as Background.js
    participant BR as Bridge Server
    participant DT as dt gnai chat
    participant LLM as GNAI / Claude

    U->>SP: Type "14027453772"
    SP->>SP: Detect HSD ID → generate CID
    SP->>SP: Show "HSD 14027453772" + CID in header
    SP->>BG: port.postMessage({action:"send", message})
    BG->>BR: POST /session/send {message}
    BR->>DT: Write to PTY stdin
    DT->>LLM: Send message via WebSocket

    Note over LLM: Phase 1: Data Gathering

    LLM->>DT: tool_call: read_article(14027453772)
    DT->>BR: JSON stdout: {tool_start}
    BR->>BG: SSE event: tool_start
    BG->>SP: port.postMessage({type:"tool_start"})
    SP->>SP: Show "Running: Read Article" spinner

    LLM->>DT: tool_call: sherlog_analyze(...)
    Note over DT: Sherlog runs 1-5 min
    DT-->>BR: (pause window spawned)
    BR->>BR: Auto-close pause window

    LLM->>DT: answer chunk (streaming)
    DT->>BR: JSON stdout: {answer, text}
    BR->>BG: SSE event: answer
    BG->>SP: port.postMessage({type:"answer"})
    SP->>SP: Progressive render + dynamic debounce

    LLM->>DT: Menu: select attachments
    DT->>BR: JSON stdout: {answer, text: menu}
    BR->>BG: SSE event: answer
    BG->>SP: port.postMessage({type:"answer"})
    SP->>SP: Generate quick-action buttons

    U->>SP: Click "1" button
    SP->>SP: Prefix: "I select: 1. Proceed..."
    SP->>BG: port.postMessage({action:"send"})
    BG->>BR: POST /session/send
    BR->>DT: Write to stdin
    DT->>LLM: Send selection

    Note over LLM: Phase 2-3: Analysis + Report

    LLM->>DT: answer chunks (report)
    DT->>BR: JSON events
    BR->>BG: SSE stream
    BG->>SP: port messages
    SP->>SP: Render report (progressive)

    LLM->>DT: usage event
    DT->>BR: {usage}
    BR->>BG: SSE: usage
    BG->>SP: usage → finalize
    SP->>SP: Full re-render + enable input
```

## Component Responsibilities

```
┌─────────────────────────────────────────────────────────┐
│  Chrome Extension                                       │
│  ┌─────────────────────┐  ┌──────────────────────────┐  │
│  │  sidepanel.js        │  │  background.js           │  │
│  │                      │  │                          │  │
│  │  • UI rendering      │  │  • Bridge auto-launch    │  │
│  │  • Markdown parser   │  │  • SSE consumer          │  │
│  │  • Progressive render│  │  • HTTP relay             │  │
│  │  • Quick-action btns │  │  • Port ↔ bridge relay   │  │
│  │  • Import HSD        │  │  • Health check          │  │
│  │  • Save to HTML      │  │  • Native Messaging      │  │
│  │  • Session history   │  │  • Reconnect logic       │  │
│  │  • CID generation    │  │                          │  │
│  └─────────────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                         │ HTTP / SSE
┌─────────────────────────────────────────────────────────┐
│  Bridge Server (bridge_server.py)                       │
│                                                          │
│  • Manage dt process lifecycle (ConPTY)                  │
│  • Parse JSON events from dt stdout                      │
│  • Translate to SSE for Extension                        │
│  • Auto-close pause windows                              │
│  • Conversation ID passthrough                           │
│  • CORS + optional API key auth                          │
└─────────────────────────────────────────────────────────┘
                         │ ConPTY stdin/stdout
┌─────────────────────────────────────────────────────────┐
│  dt gnai chat --json --assistant sighting_assistant      │
│                                                          │
│  • GNAI CLI binary (Go)                                  │
│  • WebSocket connection to gnai.intel.com                │
│  • Streams JSON events: answer, tool_start, usage, etc.  │
│  • Loads registered toolkits (sherlog, displaydebugger)  │
└─────────────────────────────────────────────────────────┘
                         │ WebSocket (HTTPS)
┌─────────────────────────────────────────────────────────┐
│  GNAI Platform (gnai.intel.com)                         │
│                                                          │
│  • LLM orchestration (Claude)                            │
│  • 15 SAT custom tools                                   │
│  • Conversation history management                       │
│  • Token limit: 200K                                     │
└─────────────────────────────────────────────────────────┘
```

## Key Design Decisions

| Decision | Reason |
|----------|--------|
| ConPTY instead of pipe | `dt` (Go binary) block-buffers stdout on pipes; ConPTY forces line-buffered output for real-time streaming |
| Bridge as HTTP server | Chrome Extension cannot spawn processes; needs localhost HTTP relay |
| Progressive render | Large reports (30KB+) cause O(n²) DOM updates; frozen/tail node split reduces to O(n) |
| Dynamic debounce | 300ms→1200ms based on text size prevents CPU overload during streaming |
| CID = HSD_ID + timestamp | Each analysis session gets unique ID even for same HSD; enables future session switching |
| `--json` mode | Required for structured events (answer/tool_start/usage); but has known context bug on menu selection |
