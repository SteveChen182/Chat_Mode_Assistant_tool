/**
 * sidepanel.js — Chat Mode Assistant UI
 *
 * Handles:
 * - Chat message display (streaming markdown)
 * - Tool execution progress indicators
 * - Quick-action button generation (regex-based)
 * - Two-phase HSD analysis flow
 */

// ── DOM refs ───────────────────────────────────────────────────────────────
const chatArea = document.getElementById("chat-area");
const quickActions = document.getElementById("quick-actions");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send-btn");
const btnNew = document.getElementById("btn-new");
const btnStop = document.getElementById("btn-stop");
const statusBadge = document.getElementById("status-badge");

// ── State ──────────────────────────────────────────────────────────────────
let port = null;
let currentAiMsg = null;       // DOM element for streaming AI message
let currentAiText = "";        // accumulated text for current AI turn
let isStreaming = false;
let renderTimer = null;
const RENDER_DEBOUNCE_MS = 300;

// ── Port connection ────────────────────────────────────────────────────────

function connectPort() {
  port = chrome.runtime.connect({ name: "sidepanel" });

  port.onMessage.addListener((msg) => {
    switch (msg.type || msg.action) {
      // Session lifecycle
      case "session_started":
        // session/start now returns immediately ("starting"), toolkit still loading
        setStatus("connected", "Loading toolkits...");
        addSystemMsg("Session starting... waiting for toolkit to load.");
        // Input stays disabled until SSE 'ready' event
        break;
      case "session_stopped":
        setStatus("disconnected", "Offline");
        addSystemMsg("Session ended.");
        setInputEnabled(false);
        break;

      // Startup progress
      case "startup_status":
        setStatus("connected", msg.message || "Starting...");
        break;
      case "bridge_unavailable":
        setStatus("disconnected", "No Bridge");
        addSystemMsg("❌ Bridge server not available. Please run:\n  cd bridge && python bridge_server.py\n\nOr set up auto-launch: .\\install_native_host.ps1");
        setInputEnabled(false);
        break;

      // Streaming events from bridge SSE
      case "answer":
        onAnswerChunk(msg.text || "");
        break;
      case "tool_start":
        onToolStart(msg.name, msg.args || {});
        break;
      case "tool_request":
        onToolRequest(msg.name, msg.operation);
        break;
      case "usage":
        onUsage(msg.usage);
        break;
      case "ready":
        onReady(msg.accumulated_answer || "");
        break;
      case "info":
        onInfo(msg.text || "");
        break;
      case "end":
      case "goodbye":
        onEnd();
        break;
      case "stream_error":
        setStatus("connected", "Reconnecting...");
        // SSE will auto-reconnect in background.js; if it gives up, we'll get bridge_unavailable
        break;

      // Health check result (also used after port reconnect)
      case "health_result":
        if (msg.session_active) {
          setStatus("connected", msg.session_waiting_input ? "Connected" : "Processing...");
          setInputEnabled(!!msg.session_waiting_input);
        } else {
          setStatus("connected", "No Session");
        }
        break;

      // Errors
      case "error":
        addSystemMsg(`❌ Error: ${msg.error}`);
        break;
    }
  });

  port.onDisconnect.addListener(() => {
    port = null;
    // Service worker may have been suspended — auto-reconnect
    setTimeout(() => {
      if (!port) {
        connectPort();
        // Re-check health after reconnecting
        if (port) {
          port.postMessage({ action: "health" });
        }
      }
    }, 500);
  });

  // Check health on connect
  port.postMessage({ action: "health" });
}

// ── Event Handlers ─────────────────────────────────────────────────────────

function onAnswerChunk(text) {
  if (!currentAiMsg) {
    currentAiMsg = addAiMsg("");
    currentAiText = "";
  }
  currentAiText += text;
  isStreaming = true;

  // Debounced render for performance
  if (renderTimer) clearTimeout(renderTimer);
  renderTimer = setTimeout(() => {
    if (currentAiMsg) {
      currentAiMsg.innerHTML = renderMarkdown(currentAiText);
      scrollToBottom();
    }
  }, RENDER_DEBOUNCE_MS);
}

function onToolStart(name, args) {
  // Remove previous tool indicator if exists
  removeToolIndicator();

  const friendlyName = formatToolName(name);
  const detail = args.id ? ` (ID: ${args.id})` : "";
  addToolIndicator(`${friendlyName}${detail}`);
}

function onToolRequest(name, operation) {
  // Tool is actively executing — keep the indicator spinning
}

function onUsage(usage) {
  // Response complete for this turn
  isStreaming = false;
  removeToolIndicator();
}

function onReady(accumulatedAnswer) {
  // AI finished responding, waiting for user input
  isStreaming = false;
  removeToolIndicator();
  finalizeAiMsg();

  // Update status to Connected (handles initial toolkit-loaded ready too)
  setStatus("connected", "Connected");

  // If this is the first ready after session start, show welcome
  if (!accumulatedAnswer) {
    addSystemMsg("Session ready. Type an HSD ID to begin analysis.");
  }

  // Parse accumulated answer for quick-action buttons
  if (accumulatedAnswer) {
    generateQuickActions(accumulatedAnswer);
  }

  setInputEnabled(true);
}

function onInfo(text) {
  // Loading messages, toolkit progress, etc.
  if (text.includes("Loading toolkits") || text.includes("Loading")) {
    setStatus("connected", "Loading toolkits...");
  } else if (text) {
    setStatus("connected", text.substring(0, 40));
  }
}

function onEnd() {
  isStreaming = false;
  removeToolIndicator();
  finalizeAiMsg();
  setInputEnabled(true);
}

function finalizeAiMsg() {
  if (currentAiMsg && currentAiText) {
    if (renderTimer) clearTimeout(renderTimer);
    currentAiMsg.innerHTML = renderMarkdown(currentAiText);
    scrollToBottom();
  }
  currentAiMsg = null;
  currentAiText = "";
}

// ── Quick Action Buttons ───────────────────────────────────────────────────

function generateQuickActions(text) {
  quickActions.innerHTML = "";
  quickActions.classList.remove("show");

  const buttons = [];
  const lastLines = text.split("\n").slice(-30).join("\n");

  // Pattern 1: Numbered list items "1) text" or "1. text"
  const numberedItems = [...lastLines.matchAll(/^\s*(\d+)[).]\s+(.+)$/gm)];
  if (numberedItems.length >= 2) {
    for (const m of numberedItems) {
      buttons.push({ label: `${m[1]}`, value: m[1], detail: m[2].substring(0, 40) });
    }
    buttons.push({ label: "All", value: "all" });
    buttons.push({ label: "Skip", value: "skip" });
  }

  // Pattern 2: Yes/No question
  if (!buttons.length && /\b(would you like|do you want|shall I|proceed\?|yes\/no|y\/n)/i.test(lastLines)) {
    buttons.push({ label: "Yes", value: "yes" });
    buttons.push({ label: "No", value: "no" });
  }

  // Pattern 3: Comma-separated options "Select: A, B, C"
  if (!buttons.length) {
    const optMatch = lastLines.match(/(?:select|choose|pick|options?).*?:\s*(.+(?:,\s*.+){2,})/i);
    if (optMatch) {
      const options = optMatch[1].split(",").map(s => s.trim()).filter(Boolean);
      for (const opt of options) {
        buttons.push({ label: opt, value: opt });
      }
    }
  }

  if (buttons.length === 0) return;

  for (const btn of buttons) {
    const el = document.createElement("button");
    el.className = "quick-btn";
    el.textContent = btn.detail ? `${btn.label} — ${btn.detail}` : btn.label;
    el.title = btn.value;
    el.addEventListener("click", () => {
      quickActions.classList.remove("show");
      sendUserMessage(btn.value);
    });
    quickActions.appendChild(el);
  }

  quickActions.classList.add("show");
}

// ── Send Message ───────────────────────────────────────────────────────────

function sendUserMessage(text) {
  if (!text.trim() || !port) return;

  addUserMsg(text);
  quickActions.classList.remove("show");
  setInputEnabled(false);

  port.postMessage({ action: "send", message: text });
}

// ── UI Helpers ─────────────────────────────────────────────────────────────

function addUserMsg(text) {
  const el = document.createElement("div");
  el.className = "msg msg-user";
  el.textContent = text;
  chatArea.appendChild(el);
  scrollToBottom();
  return el;
}

function addAiMsg(html) {
  const el = document.createElement("div");
  el.className = "msg msg-ai";
  el.innerHTML = html;
  chatArea.appendChild(el);
  scrollToBottom();
  return el;
}

function addSystemMsg(text) {
  const el = document.createElement("div");
  el.className = "msg msg-ai";
  el.style.fontStyle = "italic";
  el.style.color = "#6b7280";
  el.style.fontSize = "12px";
  el.textContent = text;
  chatArea.appendChild(el);
  scrollToBottom();
}

function addToolIndicator(text) {
  const el = document.createElement("div");
  el.className = "tool-indicator";
  el.id = "tool-progress";
  el.innerHTML = `<div class="spinner"></div><span>Running: ${escapeHtml(text)}</span>`;
  chatArea.appendChild(el);
  scrollToBottom();
}

function removeToolIndicator() {
  const el = document.getElementById("tool-progress");
  if (el) el.remove();
}

function setStatus(cls, text) {
  statusBadge.className = `header-status ${cls}`;
  statusBadge.textContent = text;
}

function setInputEnabled(enabled) {
  inputEl.disabled = !enabled;
  sendBtn.disabled = !enabled;
  if (enabled) inputEl.focus();
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    chatArea.scrollTop = chatArea.scrollHeight;
  });
}

function formatToolName(name) {
  return (name || "unknown")
    .replace(/^sighting_/, "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, c => c.toUpperCase());
}

// ── Simple Markdown Renderer ───────────────────────────────────────────────

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function renderMarkdown(text) {
  if (!text) return "";

  let html = escapeHtml(text);

  // Code blocks
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  // Italic
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

  // Headers
  html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');

  // Horizontal rules
  html = html.replace(/^---+$/gm, '<hr>');

  // Simple table rendering
  html = renderTables(html);

  // Line breaks
  html = html.replace(/\n/g, '<br>');

  return html;
}

function renderTables(html) {
  // Match markdown tables: | col | col | \n |---|---| \n | val | val |
  const tableRegex = /(\|.+\|)\n(\|[\s:|-]+\|)\n((?:\|.+\|\n?)+)/g;

  return html.replace(tableRegex, (match, headerRow, sepRow, bodyRows) => {
    const headers = headerRow.split("|").filter(c => c.trim()).map(c => c.trim());
    const rows = bodyRows.trim().split("\n").map(row =>
      row.split("|").filter(c => c.trim()).map(c => c.trim())
    );

    let table = "<table><thead><tr>";
    for (const h of headers) table += `<th>${h}</th>`;
    table += "</tr></thead><tbody>";
    for (const row of rows) {
      table += "<tr>";
      for (const cell of row) table += `<td>${cell}</td>`;
      table += "</tr>";
    }
    table += "</tbody></table>";
    return table;
  });
}

// ── Auto-resize textarea ───────────────────────────────────────────────────

inputEl.addEventListener("input", () => {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + "px";
});

// ── Event Listeners ────────────────────────────────────────────────────────

sendBtn.addEventListener("click", () => {
  sendUserMessage(inputEl.value);
  inputEl.value = "";
  inputEl.style.height = "auto";
});

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendUserMessage(inputEl.value);
    inputEl.value = "";
    inputEl.style.height = "auto";
  }
});

btnNew.addEventListener("click", () => {
  chatArea.innerHTML = "";
  quickActions.classList.remove("show");
  quickActions.innerHTML = "";
  if (port) {
    port.postMessage({ action: "start_session" });
  }
});

btnStop.addEventListener("click", () => {
  if (port) {
    port.postMessage({ action: "stop_session" });
  }
});

// ── Initialize ─────────────────────────────────────────────────────────────

connectPort();

// Auto-start: check bridge + start session
setInputEnabled(false);
setTimeout(() => {
  if (port) {
    setStatus("connected", "Connecting...");
    addSystemMsg("Connecting to bridge server...");
    port.postMessage({ action: "start_session" });
  }
}, 300);
