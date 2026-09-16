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

- **Web chat window switching**: Use the header's pop-out button to move the main web chat into a separate window, and its return button to reopen the side panel. Switching preserves saved conversations, the current draft, scroll position, and unexpired tab-close undo entries. Switching is disabled during requests or page loading. Only one chat view can edit data at a time; other views remain paused. If a destination fails to take over, use the paused view's resume button after the timeout. SAT and legacy tool windows remain separate. Page capture in the chat popup uses its associated normal Chrome window.

- **Two-phase HSD analysis**: Quick summary first, then user-selected attachment analysis
- **Streaming responses**: Real-time AI output via SSE
- **Smart quick-action buttons**: Auto-detect interactive prompts and generate clickable options
- **Tool execution progress**: Visual indicators for running tools
- **Child window auto-close**: Handle subprocess pause windows automatically

## TODO

- [ ] **Web chat TXT/LOG attachments** (planned, not implemented): Allow attaching text logs separately from the question input. Show file size and loaded character count; explicitly reject or warn about oversized files instead of silently truncating them. Plan chunked analysis for large logs within model context limits, with clear coverage and token/cost expectations. Include a reminder to remove credentials and sensitive data before sending. Implementation is deferred at the user's request.
