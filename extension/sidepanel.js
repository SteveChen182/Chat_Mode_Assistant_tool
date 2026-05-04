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
const btnImport = document.getElementById("btn-import");
const headerTitle = document.getElementById("header-title");
const headerSubtitle = document.getElementById("header-subtitle");
const statusBadge = document.getElementById("status-badge");

// ── State ──────────────────────────────────────────────────────────────────
let port = null;
let currentAiMsg = null;       // DOM element for streaming AI message
let currentAiText = "";        // accumulated text for current AI turn
let isStreaming = false;
let renderTimer = null;
const RENDER_DEBOUNCE_MS = 300;

// ── History State ──────────────────────────────────────────────────────────
const MAX_HISTORY = 10;
let activeHsdId = null;        // detected from user's first message
let sessionMessages = [];      // [{role, content}] for current session
let liveSessionHtml = "";      // saved chatArea HTML when viewing history
let isViewingHistory = false;
let historySaveTimer = null;
const HISTORY_SAVE_DEBOUNCE_MS = 3000;

// ── Port connection ────────────────────────────────────────────────────────

function connectPort() {
  port = chrome.runtime.connect({ name: "sidepanel" });

  port.onMessage.addListener((msg) => {
    switch (msg.type || msg.action) {
      // Session lifecycle
      case "session_started":
        if (msg.status === "already_active") {
          // Session was already running (e.g. sidepanel reloaded) — just reconnect
          setStatus("connected", msg.session_waiting_input ? "Connected" : "Processing...");
          setInputEnabled(!!msg.session_waiting_input);
        } else {
          // New session starting — toolkit still loading
          setStatus("connected", "Loading toolkits...");
          addSystemMsg("Session starting... waiting for toolkit to load.");
          // Input stays disabled until SSE 'ready' event
        }
        break;
      case "session_stopped":
        setStatus("disconnected", "Offline");
        removeToolIndicator();
        isStreaming = false;
        currentAiMsg = null;
        currentAiText = "";
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
      case "error":
        // gnai-level error (e.g. tool execution failure, connection abort)
        removeToolIndicator();
        isStreaming = false;
        finalizeAiMsg();
        addSystemMsg(`⚠️ Error: ${msg.text || "Unknown error"}`);
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
  finalizeAiMsg();

  // Track AI response in session messages when we have accumulated text
  if (currentAiText) {
    sessionMessages.push({ role: "assistant", content: currentAiText });
  }
  debouncedSaveHistory();
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

  // If viewing history, go back to live session first
  if (isViewingHistory) {
    backToLiveSession();
  }

  addUserMsg(text);
  quickActions.classList.remove("show");
  setInputEnabled(false);

  // Track messages for history
  sessionMessages.push({ role: "user", content: text });
  debouncedSaveHistory();

  // Detect HSD ID from first user message (8-14 digit number)
  if (!activeHsdId) {
    const hsdMatch = text.match(/\b(\d{8,14})\b/);
    if (hsdMatch) {
      activeHsdId = hsdMatch[1];
      updateHeaderTitle();
    }
  }

  // If this looks like a menu selection (numbers, "all", "skip"),
  // prefix with strong context so the LLM correctly interprets it as a selection response.
  // This is needed because in --json mode, the menu is output as answer text and
  // the user's reply is a new turn — the LLM may not realize it's a menu response.
  const trimmed = text.trim().toLowerCase();
  // Menu selections: 1-2 digit numbers (with commas/ranges), "all", or "skip"
  // Exclude long numbers (like HSD IDs which are 8+ digits)
  const isMenuSelection = /^(\d{1,2}([\s,\-]+\d{1,2})*|all|skip)$/i.test(trimmed);
  const messageToSend = (isMenuSelection && activeHsdId)
    ? `I select: ${text}. Proceed with analyzing only the selected item(s) from the menu above. Do NOT repeat Phase 1 or re-read the article.`
    : text;

  port.postMessage({ action: "send", message: messageToSend });
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
  btnImport.disabled = !enabled;
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

// ── Header Title ───────────────────────────────────────────────────────────

function updateHeaderTitle() {
  if (headerTitle) {
    headerTitle.textContent = activeHsdId ? `HSD ${activeHsdId}` : "Chat Mode Assistant";
  }
}

let activeHsdTitle = "";

function updateHeaderSubtitle(title) {
  activeHsdTitle = title || "";
  if (headerSubtitle) {
    headerSubtitle.textContent = activeHsdTitle;
    headerSubtitle.classList.toggle("show", !!activeHsdTitle);
  }
}

// ── Import HSD from Tab URL ────────────────────────────────────────────────

function extractHsdIdFromUrl(url) {
  const value = String(url || "").trim();
  // HSD-ES article URLs
  const patterns = [
    /^https:\/\/hsdes\.intel\.com\/appstore\/article-one\/#\/article\/(\d{8,14})(?:[/?#].*)?$/i,
    /^https:\/\/hsdes\.intel\.com\/appstore\/article-one\/#\/(\d{8,14})(?:[/?#].*)?$/i,
  ];
  for (const pattern of patterns) {
    const m = value.match(pattern);
    if (m) return m[1];
  }
  return "";
}

async function getCurrentTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function importHsdFromWebpage() {
  try {
    const tab = await getCurrentTab();
    const url = String(tab?.url || "");
    const hsdId = extractHsdIdFromUrl(url);

    if (!hsdId) {
      addSystemMsg("No HSD ID found in current tab URL. Open an HSD-ES article page first.");
      return;
    }

    // If already have an active HSD, confirm
    if (activeHsdId && activeHsdId !== hsdId) {
      const confirmed = confirm(`Switch from HSD ${activeHsdId} to HSD ${hsdId}? This will send the new ID to the current session.`);
      if (!confirmed) return;
    }

    activeHsdId = hsdId;
    updateHeaderTitle();

    // Extract page title from tab
    const pageTitle = (tab.title || "").trim();
    // HSD-ES titles often look like "<ID> - <Title> - HSD-ES" or just the title
    let hsdTitle = pageTitle
      .replace(/^\d{8,14}\s*[-–—:]\s*/, "")   // strip leading HSD ID
      .replace(/\s*[-–—|]\s*HSD[-\s]?ES.*$/i, "")  // strip trailing "- HSD-ES"
      .trim();
    updateHeaderSubtitle(hsdTitle);

    addSystemMsg(`Imported HSD ID: ${hsdId}`);

    // Auto-send the HSD ID to start analysis
    sendUserMessage(hsdId);
  } catch (e) {
    addSystemMsg("Failed to read current tab. Make sure the extension has tab access.");
  }
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
  // Reset history viewing state
  if (isViewingHistory) {
    isViewingHistory = false;
    document.getElementById("history-viewer-bar").classList.remove("show");
  }
  chatArea.innerHTML = "";
  quickActions.classList.remove("show");
  quickActions.innerHTML = "";
  // Reset session tracking
  activeHsdId = null;
  sessionMessages = [];
  updateHeaderTitle();
  updateHeaderSubtitle("");
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

// ── History Functions ──────────────────────────────────────────────────────

function debouncedSaveHistory() {
  if (historySaveTimer) clearTimeout(historySaveTimer);
  historySaveTimer = setTimeout(() => {
    historySaveTimer = null;
    saveToHistory();
  }, HISTORY_SAVE_DEBOUNCE_MS);
}

async function saveToHistory() {
  if (!activeHsdId || sessionMessages.length === 0) return;
  try {
    const stored = await chrome.storage.local.get({ chatHistory: [] });
    const history = Array.isArray(stored.chatHistory) ? stored.chatHistory : [];

    // Remove existing entry for same HSD (will re-add at front)
    const filtered = history.filter(e => e.hsdId !== activeHsdId);

    filtered.unshift({
      hsdId: activeHsdId,
      messages: [...sessionMessages],
      timestamp: Date.now(),
    });

    // Trim to max
    const trimmed = filtered.slice(0, MAX_HISTORY);
    await chrome.storage.local.set({ chatHistory: trimmed });
  } catch (e) {
    console.error("[history] save error:", e);
  }
}

function closeHistoryMenu() {
  const menu = document.getElementById("historyMenu");
  if (menu) menu.classList.remove("show");
}

async function openHistoryMenu() {
  const menu = document.getElementById("historyMenu");
  if (!menu) return;

  // Toggle
  if (menu.classList.contains("show")) {
    menu.classList.remove("show");
    return;
  }

  let stored = { chatHistory: [] };
  try {
    stored = await chrome.storage.local.get({ chatHistory: [] });
  } catch (_) {}

  const history = Array.isArray(stored.chatHistory) ? stored.chatHistory : [];
  menu.innerHTML = "";

  // Title
  const title = document.createElement("div");
  title.className = "history-menu-title";
  title.textContent = `Recent Sessions (${history.length})`;
  menu.appendChild(title);

  if (history.length === 0) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "No history yet";
    menu.appendChild(empty);
  } else {
    for (const entry of history) {
      const btn = document.createElement("button");
      btn.className = "history-item";

      const hsdLine = document.createElement("div");
      hsdLine.className = "history-item-hsd";
      hsdLine.textContent = `HSD ${entry.hsdId}`;
      btn.appendChild(hsdLine);

      const timeLine = document.createElement("div");
      timeLine.className = "history-item-time";
      timeLine.textContent = formatTimestamp(entry.timestamp);
      btn.appendChild(timeLine);

      btn.addEventListener("click", () => {
        closeHistoryMenu();
        viewHistoryEntry(entry);
      });
      menu.appendChild(btn);
    }
  }

  // Clear All button
  if (history.length > 0) {
    const clearBtn = document.createElement("button");
    clearBtn.className = "history-clear-btn";
    clearBtn.textContent = "Clear All History";
    clearBtn.addEventListener("click", async () => {
      await chrome.storage.local.set({ chatHistory: [] });
      closeHistoryMenu();
    });
    menu.appendChild(clearBtn);
  }

  menu.classList.add("show");
}

function viewHistoryEntry(entry) {
  // Save current live session HTML
  if (!isViewingHistory) {
    liveSessionHtml = chatArea.innerHTML;
  }
  isViewingHistory = true;

  // Update header title to show history HSD
  headerTitle.textContent = `HSD ${entry.hsdId} (history)`;
  updateHeaderSubtitle("");  // no subtitle for history view

  // Show viewer bar
  const bar = document.getElementById("history-viewer-bar");
  const label = document.getElementById("history-viewer-label");
  label.textContent = `📋 Viewing: HSD ${entry.hsdId} (${formatTimestamp(entry.timestamp)})`;
  bar.classList.add("show");

  // Hide quick actions and disable input
  quickActions.classList.remove("show");
  quickActions.innerHTML = "";
  setInputEnabled(false);

  // Render history messages
  chatArea.innerHTML = "";
  for (const msg of entry.messages) {
    if (msg.role === "user") {
      addUserMsg(msg.content);
    } else if (msg.role === "assistant") {
      const el = addAiMsg("");
      el.innerHTML = renderMarkdown(msg.content);
    }
  }
  scrollToBottom();
}

function backToLiveSession() {
  isViewingHistory = false;

  // Hide viewer bar
  document.getElementById("history-viewer-bar").classList.remove("show");

  // Restore header title + subtitle
  updateHeaderTitle();
  updateHeaderSubtitle(activeHsdTitle);

  // Restore live session
  chatArea.innerHTML = liveSessionHtml;
  liveSessionHtml = "";
  scrollToBottom();
  setInputEnabled(true);
}

function formatTimestamp(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const hours = String(d.getHours()).padStart(2, "0");
  const minutes = String(d.getMinutes()).padStart(2, "0");
  return `${month}/${day} ${hours}:${minutes}`;
}

// ── History Event Listeners ────────────────────────────────────────────────

document.getElementById("btn-history").addEventListener("click", openHistoryMenu);

document.getElementById("history-viewer-back").addEventListener("click", backToLiveSession);

btnImport.addEventListener("click", importHsdFromWebpage);

// Close history menu on click outside
document.addEventListener("click", (e) => {
  const menu = document.getElementById("historyMenu");
  const btn = document.getElementById("btn-history");
  if (menu && menu.classList.contains("show") && !menu.contains(e.target) && e.target !== btn) {
    closeHistoryMenu();
  }
});

// Close history menu on Escape
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeHistoryMenu();
  }
});

// Save to history when page is being hidden (fire-and-forget)
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") {
    saveToHistory();
  }
});

// ── Init ───────────────────────────────────────────────────────────────────

connectPort();

// Auto-start: check health first, only start new session if none active
setInputEnabled(false);
setTimeout(async () => {
  if (!port) return;
  setStatus("connected", "Connecting...");
  addSystemMsg("Connecting to bridge server...");
  // Ask background for health — it will start session only if needed
  port.postMessage({ action: "start_session" });
}, 300);
