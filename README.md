# Chat Mode Assistant Tool

Chrome Extension + Python Bridge for interactive GNAI `chat` mode integration with SightingAssistantTool.

## Architecture

```
Chrome Extension (sidepanel) 
    ↕ HTTP/SSE
Python Bridge Server (localhost:8775)
    ↕ stdin/stdout pipe
dt gnai chat --json --assistant sighting_assistant
```

## Project Structure

```
bridge/           → Python bridge server (chat mode)
extension/        → Chrome Extension (MV3 sidepanel)
design/           → Architecture & design docs
external/         → Reference code (not part of this project)
  Steve_Chatter/  → Existing ask-mode Extension (reference)
  SightingAssistantTool/ → GNAI Toolkit code (reference)
```

## Key Features

- **Two-phase HSD analysis**: Quick summary first, then user-selected attachment analysis
- **Streaming responses**: Real-time AI output via SSE
- **Smart quick-action buttons**: Auto-detect interactive prompts and generate clickable options
- **Tool execution progress**: Visual indicators for running tools
- **Child window auto-close**: Handle subprocess pause windows automatically
