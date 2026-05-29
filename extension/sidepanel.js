/**
 * sidepanel.js — Chat Mode Assistant UI
 *
 * Handles:
 * - Chat message display (streaming markdown)
 * - Tool execution progress indicators
 * - Quick-action button generation (table-driven)
 * - Two-phase HSD analysis flow
 */

// ══════════════════════════════════════════════════════════════════════════════
// QUICK ACTION TABLE — Edit this table to customize quick action buttons
// ══════════════════════════════════════════════════════════════════════════════
// Each entry:
//   label    → 按鈕上顯示的文字
//   prompt   → 按下去實際送給 GNAI 的 prompt
//   display  → 按下去後 output 視窗 (chat area) 顯示的文字（使用者看到的）
//   group    → 按鈕分組（同一組同時出現）: "start", "menu", "yesno", "custom"
//   show     → 何時顯示: "always" = session ready 時常駐, "menu" = AI 回覆有選單時, "import" = HSD 匯入後
// ──────────────────────────────────────────────────────────────────────────────
const QUICK_ACTIONS_TABLE = [
  // ── 常駐按鈕 (session ready 後顯示) ──
  { label: "Analyze",     prompt: "Please analyze this sighting.",                          display: "Analyze",            group: "start", show: "always" },
  { label: "Summary",     prompt: "Provide a brief summary of the current analysis.",       display: "Summary",            group: "start", show: "always" },
  { label: "Root Cause",  prompt: "What is the most likely root cause?",                    display: "Root Cause",         group: "start", show: "always" },
  { label: "Next Steps",  prompt: "What are the recommended next steps?",                   display: "Next Steps",         group: "start", show: "always" },

  // ── 選單回覆按鈕 (AI 輸出 numbered list 時顯示) ──
  { label: "All",         prompt: "all",                                                    display: "All",                group: "menu",  show: "menu" },
  { label: "Skip",        prompt: "skip",                                                   display: "Skip",               group: "menu",  show: "menu" },

  // ── Yes/No 回覆 ──
  { label: "Yes",         prompt: "yes",                                                    display: "Yes",                group: "yesno", show: "yesno" },
  { label: "No",          prompt: "no",                                                     display: "No",                 group: "yesno", show: "yesno" },

  // ── 第一次分析完成後顯示 ──
  { label: "📋 Summary",        prompt: "Provide a brief summary of this sighting analysis.",              display: "Summary",         group: "post", show: "post-analysis" },
  { label: "🔍 Root Cause",     prompt: "What is the most likely root cause?",                            display: "Root Cause",      group: "post", show: "post-analysis" },
  { label: "📝 Action Items",   prompt: "List comment's action items and who is action owner.",                             display: "Action Items",    group: "post", show: "post-analysis" },
  { label: "🔄 More Similiar issues",      prompt: "List 10 similar issues' ID, title and score by table style.",        display: "List 10 similiar issues",       group: "post", show: "post-analysis" },
 
];

// ── DOM refs ───────────────────────────────────────────────────────────────
const chatArea = document.getElementById("chat-area");
const quickActions = document.getElementById("quick-actions");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send-btn");
const btnNew = document.getElementById("btn-new");
const btnStop = document.getElementById("btn-stop");
const btnImport = document.getElementById("btn-import");
const btnSave = document.getElementById("btn-save");
const btnBottom = document.getElementById("btn-bottom");
const btnFontUp = document.getElementById("btn-font-up");
const btnFontDown = document.getElementById("btn-font-down");
const headerTitle = document.getElementById("header-title");
const headerSubtitle = document.getElementById("header-subtitle");
const statusBadge = document.getElementById("status-badge");
const btnHistory = document.getElementById("btn-history");
const onboardingEl = document.getElementById("onboarding");
const heroCta = document.getElementById("hero-cta");
const heroCtaBtn = document.getElementById("hero-cta-btn");
const postAnalysisPanel = document.getElementById("post-analysis-panel");
const postAnalysisGrid = document.getElementById("post-analysis-grid");
const toastContainer = document.getElementById("toast-container");
const modalOverlay = document.getElementById("modal-overlay");
const modalTitle = document.getElementById("modal-title");
const modalMessage = document.getElementById("modal-message");
const modalConfirmBtn = document.getElementById("modal-confirm");
const modalCancelBtn = document.getElementById("modal-cancel");

// ── Custom Modal ─────────────────────────────────────────────────────────────────────────
let _modalResolve = null;

function showModal(title, message, confirmText = "Confirm", cancelText = "Cancel") {
  return new Promise((resolve) => {
    _modalResolve = resolve;
    modalTitle.textContent = title;
    modalMessage.textContent = message;
    modalConfirmBtn.textContent = confirmText;
    modalCancelBtn.textContent = cancelText;
    modalOverlay.classList.add("show");
  });
}

modalConfirmBtn.addEventListener("click", () => {
  modalOverlay.classList.remove("show");
  if (_modalResolve) { _modalResolve(true); _modalResolve = null; }
});
modalCancelBtn.addEventListener("click", () => {
  modalOverlay.classList.remove("show");
  if (_modalResolve) { _modalResolve(false); _modalResolve = null; }
});

// ── Toast Notifications ────────────────────────────────────────────────────────────────────────
function showToast(text, type = "") {
  const el = document.createElement("div");
  el.className = `toast${type ? ` toast-${type}` : ""}`;
  el.textContent = text;
  toastContainer.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

// ── Typing Indicator ─────────────────────────────────────────────────────────────────────────
function showTypingIndicator() {
  removeTypingIndicator();
  const el = document.createElement("div");
  el.className = "typing-indicator";
  el.id = "typing-indicator";
  el.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
  chatArea.appendChild(el);
  scrollToBottom();
}

function removeTypingIndicator() {
  const el = document.getElementById("typing-indicator");
  if (el) el.remove();
}

// ── Onboarding ───────────────────────────────────────────────────────────────────────────────
function hideOnboarding() {
  if (onboardingEl) onboardingEl.style.display = "none";
}

function showOnboarding() {
  if (onboardingEl) onboardingEl.style.display = "flex";
}

// ── Connection Splash ────────────────────────────────────────────────────────────────────────
const splashEl = document.getElementById("connection-splash");
const splashText = document.getElementById("splash-text");
const splashSub = document.getElementById("splash-sub");
const splashProgress = document.getElementById("splash-progress");

function showConnectionSplash(text, sub) {
  if (!splashEl) return;
  splashEl.classList.remove("fade-out");
  splashEl.style.display = "flex";
  if (text) splashText.textContent = text;
  if (sub) splashSub.textContent = sub;
  splashProgress.classList.remove("done");
}

function updateConnectionSplash(text, sub) {
  if (splashText && text) splashText.textContent = text;
  if (splashSub && sub) splashSub.textContent = sub;
}

function hideConnectionSplash() {
  if (!splashEl) return;
  splashProgress.classList.add("done");
  splashText.textContent = "Connected!";
  splashSub.textContent = "";
  setTimeout(() => {
    splashEl.classList.add("fade-out");
    setTimeout(() => { splashEl.style.display = "none"; }, 400);
  }, 600);
}

// ── Post-Analysis Panel ────────────────────────────────────────────────────────────────────
let _postAnalysisShown = false;
const _POST_TITLE_FULL = "✅ Analysis Complete — What's next?";
const _POST_TITLE_SHORT = "What's next?";

function showPostAnalysisPanel() {
  if (_postAnalysisShown) return;
  _postAnalysisShown = true;

  const buttons = QUICK_ACTIONS_TABLE.filter(btn => btn.show === "post-analysis");
  if (buttons.length === 0) return;

  // Set full title on first show
  const titleEl = postAnalysisPanel.querySelector(".post-analysis-title");
  if (titleEl) titleEl.textContent = _POST_TITLE_FULL;

  postAnalysisGrid.innerHTML = "";
  for (const btn of buttons) {
    const el = document.createElement("button");
    el.className = "post-analysis-btn";
    el.textContent = btn.label;
    el.title = btn.prompt;
    el.addEventListener("click", () => {
      hidePostAnalysisPanel();
      sendUserMessage(btn.prompt, btn.display);
    });
    postAnalysisGrid.appendChild(el);
  }
  postAnalysisPanel.classList.remove("collapsed");
  postAnalysisPanel.classList.add("show");
  scrollToBottom();
}

function hidePostAnalysisPanel() {
  postAnalysisPanel.classList.remove("show");
}

// Toggle collapse on header click
document.getElementById("post-analysis-header").addEventListener("click", () => {
  postAnalysisPanel.classList.toggle("collapsed");
  // After first collapse, shorten the title
  const titleEl = postAnalysisPanel.querySelector(".post-analysis-title");
  if (titleEl && postAnalysisPanel.classList.contains("collapsed")) {
    titleEl.textContent = _POST_TITLE_SHORT;
  }
});

// ── Save Chat as HTML ──────────────────────────────────────────────────────
btnSave.addEventListener("click", () => {
  const title = headerTitle.textContent || "Chat Mode Assistant";
  const subtitle = headerSubtitle?.textContent || "";
  const timestamp = new Date().toLocaleString();
  const chatContent = chatArea.innerHTML;

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>${title} - ${subtitle || "Export"}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f3f4f6; padding: 20px; max-width: 900px; margin: 0 auto; font-size: 14px; }
  h1 { color: #5F80AB; font-size: 18px; margin-bottom: 4px; }
  .meta { color: #6b7280; font-size: 12px; margin-bottom: 16px; }
  .chat-area { display: flex; flex-direction: column; gap: 8px; }
  .msg { max-width: 90%; padding: 10px 14px; border-radius: 12px; line-height: 1.5; word-wrap: break-word; }
  .msg-user { background: #dbeafe; align-self: flex-end; border-bottom-right-radius: 4px; }
  .msg-ai { background: #ffffff; align-self: flex-start; border-bottom-left-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  .msg-ai pre { background: #f9fafb; padding: 8px; border-radius: 6px; overflow-x: auto; font-size: 12px; margin: 6px 0; }
  .msg-ai code { font-size: 12px; }
  .msg-ai table { border-collapse: collapse; margin: 6px 0; font-size: 12px; }
  .msg-ai th, .msg-ai td { border: 1px solid #d1d5db; padding: 4px 8px; text-align: left; }
  .msg-ai th { background: #f3f4f6; }
  .tool-indicator { display: flex; align-items: center; gap: 8px; padding: 6px 12px; background: #fef3c7; border-radius: 8px; font-size: 12px; color: #92400e; }
</style>
</head>
<body>
<h1>${title}</h1>
<div class="meta">${subtitle ? subtitle + "<br>" : ""}Exported: ${timestamp}</div>
<div class="chat-area">${chatContent}</div>
</body>
</html>`;

  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const safeName = (subtitle || title).replace(/[^a-zA-Z0-9_\-]/g, "_").substring(0, 60);
  a.download = `${safeName}_${new Date().toISOString().slice(0,10)}.html`;
  a.click();
  URL.revokeObjectURL(url);
  showToast("Chat saved as HTML", "success");
});

// ── State ──────────────────────────────────────────────────────────────────
let port = null;
let currentAiMsg = null;       // DOM element for streaming AI message
let currentAiText = "";        // accumulated text for current AI turn
let isStreaming = false;
let renderTimer = null;
const RENDER_DEBOUNCE_MS = 300;
// Progressive render state
const PROGRESSIVE_THRESHOLD = 6000;  // switch to progressive mode above 6KB
let frozenHtml = "";                 // HTML rendered for frozen portion
let frozenTextLen = 0;               // how many chars of currentAiText are frozen
let frozenNode = null;               // frozen content DOM node (avoids full innerHTML rebuild)
let tailNode = null;                 // tail content DOM node

function getRenderDebounce() {
  const len = currentAiText.length;
  if (len > 50000) return 1200;
  if (len > 30000) return 800;
  if (len > 10000) return 500;
  return RENDER_DEBOUNCE_MS;
}

// ── Session State ─────────────────────────────────────────────────────────
const MAX_SESSIONS = 6;        // 1 active + 5 saved
let activeHsdId = null;        // detected from user's first message
let hsdImported = false;       // true after Import HSD, before first analysis sent
let sessionMessages = [];      // [{role, content}] for current session
let sessions = [];             // [{hsdId, hsdTitle, conversationId, messages[], timestamp}]

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
          if (msg.session_waiting_input) hideConnectionSplash();
        } else {
          // New session starting — toolkit still loading
          setStatus("connected", "Loading toolkits...");
          addSystemMsg("Session starting... waiting for toolkit to load.");
          // Input stays disabled until SSE 'ready' event
        }
        if (msg.conversation_id) {
          updateConversationId(msg.conversation_id);
        }
        break;
      case "session_stopped":
        setStatus("disconnected", "Offline");
        removeToolIndicator();
        removeTypingIndicator();
        isStreaming = false;
        currentAiMsg = null;
        currentAiText = "";
        addSystemMsg("Session ended.");
        showToast("Session ended");
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
        if (msg.conversation_id && !activeConversationId) {
          updateConversationId(msg.conversation_id);
        }
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
      case "send_rejected":
        // Bridge rejected send (session busy)
        addSystemMsg(`⏳ ${msg.message || "AI is still processing. Please wait."}`);
        setInputEnabled(true);
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
          if (msg.conversation_id) updateConversationId(msg.conversation_id);
          if (msg.session_waiting_input) hideConnectionSplash();
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
  removeTypingIndicator();
  if (!currentAiMsg) {
    currentAiMsg = addAiMsg("");
    currentAiText = "";
    frozenHtml = "";
    frozenTextLen = 0;
    frozenNode = null;
    tailNode = null;
  }
  currentAiText += text;
  isStreaming = true;

  // Skip render entirely if tab is not visible
  if (document.hidden) return;

  // Debounced render for performance (dynamic interval based on text size)
  if (renderTimer) clearTimeout(renderTimer);
  renderTimer = setTimeout(() => {
    if (!currentAiMsg) return;

    if (currentAiText.length < PROGRESSIVE_THRESHOLD) {
      // Small text: full render (accurate)
      currentAiMsg.innerHTML = renderMarkdown(currentAiText);
    } else {
      // Large text: progressive render using split DOM nodes
      if (frozenTextLen === 0 || currentAiText.length - frozenTextLen > PROGRESSIVE_THRESHOLD) {
        const searchEnd = currentAiText.length - 500;
        const lastSafeSplit = currentAiText.lastIndexOf("\n\n", searchEnd);
        if (lastSafeSplit > frozenTextLen) {
          frozenHtml = renderMarkdown(currentAiText.substring(0, lastSafeSplit));
          frozenTextLen = lastSafeSplit;

          // Rebuild DOM with frozen + tail nodes
          if (!frozenNode) {
            frozenNode = document.createElement("div");
            tailNode = document.createElement("div");
            currentAiMsg.innerHTML = "";
            currentAiMsg.appendChild(frozenNode);
            currentAiMsg.appendChild(tailNode);
          }
          frozenNode.innerHTML = frozenHtml;
        }
      }
      // Only update the tail node (much cheaper DOM operation)
      const tailText = currentAiText.substring(frozenTextLen);
      if (tailNode) {
        tailNode.innerHTML = renderMarkdown(tailText);
      } else {
        currentAiMsg.innerHTML = frozenHtml + renderMarkdown(tailText);
      }
    }
    scrollToBottom();
  }, getRenderDebounce());
}

function onToolStart(name, args) {
  // Remove previous tool indicator if exists
  removeToolIndicator();
  removeTypingIndicator();

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
}

function onReady(accumulatedAnswer) {
  // AI finished responding, waiting for user input
  isStreaming = false;
  removeToolIndicator();
  finalizeAiMsg();

  // Update status to Connected (handles initial toolkit-loaded ready too)
  setStatus("connected", "Connected");
  hideConnectionSplash();

  // If this is the first ready after session start, show welcome
  if (!accumulatedAnswer) {
    hideOnboarding();
    addSystemMsg("Session ready. Type an HSD ID to begin analysis.");
  }

  // Parse accumulated answer for quick-action buttons (disabled for manual testing)
  // if (accumulatedAnswer) {
  //   generateQuickActions(accumulatedAnswer);
  // }

  // Show post-analysis fancy panel after first HSD analysis completes
  if (accumulatedAnswer && activeHsdId && !_postAnalysisShown) {
    showPostAnalysisPanel();
  }

  // Save session when analysis completes
  if (sessionMessages.length > 0) {
    saveCurrentSession();
    persistSessions();
  }

  setInputEnabled(true);
}

function onInfo(text) {
  // Loading messages, toolkit progress, etc.
  if (text.includes("Loading toolkits") || text.includes("Loading")) {
    setStatus("connected", "Loading toolkits...");
    updateConnectionSplash("Loading toolkits...", "Preparing AI environment");
  } else if (text) {
    setStatus("connected", text.substring(0, 40));
    updateConnectionSplash(text.substring(0, 40), "");
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
    // Always do a full re-render on finalize for correctness
    frozenNode = null;
    tailNode = null;
    currentAiMsg.innerHTML = renderMarkdown(currentAiText);
    scrollToBottom();
  }
  currentAiMsg = null;
  currentAiText = "";
  frozenHtml = "";
  frozenTextLen = 0;
  frozenNode = null;
  tailNode = null;
}

// ── Quick Action Buttons (table-driven) ────────────────────────────────────

function renderQuickButtons(filter) {
  /**
   * Render quick action buttons from QUICK_ACTIONS_TABLE.
   * @param {string} filter - "always", "menu", "yesno", or "all"
   * @param {Array} extras - additional dynamic buttons [{label, prompt, display}]
   */
  quickActions.innerHTML = "";
  quickActions.classList.remove("show");

  const buttons = QUICK_ACTIONS_TABLE.filter(btn => btn.show === filter);
  if (buttons.length === 0) return;

  for (const btn of buttons) {
    const el = document.createElement("button");
    el.className = "quick-btn";
    el.textContent = btn.label;
    el.title = btn.prompt;
    el.addEventListener("click", () => {
      quickActions.classList.remove("show");
      sendUserMessage(btn.prompt, btn.display);
    });
    quickActions.appendChild(el);
  }
  quickActions.classList.add("show");
}

function renderDynamicNumberButtons(numberedItems) {
  /**
   * For numbered menu items detected in AI output,
   * render number buttons + the "All"/"Skip" from table.
   */
  quickActions.innerHTML = "";
  quickActions.classList.remove("show");

  // Number buttons (dynamic)
  for (const m of numberedItems) {
    const el = document.createElement("button");
    el.className = "quick-btn";
    const detail = m[2] ? m[2].substring(0, 40) : "";
    el.textContent = detail ? `${m[1]} — ${detail}` : m[1];
    el.title = m[1];
    el.addEventListener("click", () => {
      quickActions.classList.remove("show");
      sendUserMessage(m[1], m[1]);
    });
    quickActions.appendChild(el);
  }

  // Add "All" and "Skip" from table
  const menuButtons = QUICK_ACTIONS_TABLE.filter(btn => btn.show === "menu");
  for (const btn of menuButtons) {
    const el = document.createElement("button");
    el.className = "quick-btn";
    el.textContent = btn.label;
    el.title = btn.prompt;
    el.addEventListener("click", () => {
      quickActions.classList.remove("show");
      sendUserMessage(btn.prompt, btn.display);
    });
    quickActions.appendChild(el);
  }
  quickActions.classList.add("show");
}

function generateQuickActions(text) {
  quickActions.innerHTML = "";
  quickActions.classList.remove("show");

  const lastLines = text.split("\n").slice(-30).join("\n");

  // Pattern 1: Numbered list items "1) text" or "1. text"
  const numberedItems = [...lastLines.matchAll(/^\s*(\d+)[).]\s+(.+)$/gm)];
  if (numberedItems.length >= 2) {
    renderDynamicNumberButtons(numberedItems);
    return;
  }

  // Pattern 2: Yes/No question
  if (/\b(would you like|do you want|shall I|proceed\?|yes\/no|y\/n)/i.test(lastLines)) {
    renderQuickButtons("yesno");
    return;
  }

  // Pattern 3: Comma-separated options "Select: A, B, C"
  const optMatch = lastLines.match(/(?:select|choose|pick|options?).*?:\s*(.+(?:,\s*.+){2,})/i);
  if (optMatch) {
    const options = optMatch[1].split(",").map(s => s.trim()).filter(Boolean);
    quickActions.innerHTML = "";
    for (const opt of options) {
      const el = document.createElement("button");
      el.className = "quick-btn";
      el.textContent = opt;
      el.title = opt;
      el.addEventListener("click", () => {
        quickActions.classList.remove("show");
        sendUserMessage(opt, opt);
      });
      quickActions.appendChild(el);
    }
    quickActions.classList.add("show");
    return;
  }

  // No pattern matched — show persistent "always" buttons if session is ready
  renderQuickButtons("always");
}

// ── Send Message ───────────────────────────────────────────────────────────

/**
 * Send a message to GNAI via the bridge.
 * @param {string} text - The actual prompt sent to GNAI
 * @param {string} [displayText] - What to show in chat area (defaults to text)
 *   When called from quick buttons, displayText differs from text.
 *   When called from input box, they are the same.
 */
function sendUserMessage(text, displayText) {
  if (!text.trim() || !port) return;

  // Reset scroll lock — user sending a message means they want to follow output
  userScrolledUp = false;

  const shown = displayText || text;
  addUserMsg(shown);
  quickActions.classList.remove("show");
  setInputEnabled(false);

  // Auto-collapse post-analysis panel when user starts next action
  if (postAnalysisPanel.classList.contains("show")) {
    postAnalysisPanel.classList.add("collapsed");
    const titleEl = postAnalysisPanel.querySelector(".post-analysis-title");
    if (titleEl) titleEl.textContent = _POST_TITLE_SHORT;
  }

  // Track messages for session
  sessionMessages.push({ role: "user", content: shown });

  // Detect HSD ID from first user message (8-14 digit number)
  if (!activeHsdId) {
    const hsdMatch = text.match(/\b(\d{8,14})\b/);
    if (hsdMatch) {
      activeHsdId = hsdMatch[1];
      updateHeaderTitle();
      const cid = generateConversationId(activeHsdId);
      updateConversationId(cid);
    }
  }

  // ── Text modification logic ────────────────────────────────────────────────
  // Modification 1: HSD prefix — prepends [HSD xxxxx] when hsdImported is true
  if (hsdImported && activeHsdId) {
    hsdImported = false;
    quickActions.innerHTML = "";
    quickActions.classList.remove("show");
    if (!text.includes(activeHsdId)) {
      text = `[HSD ${activeHsdId}] ${text}`;
    }
    // Modification 1b: Output style instruction (disabled)
    // text += ` (Output format: Do NOT use inline code style. Use markdown table format for structured data.)`;
  }

  // Modification 2: Menu selection prefix — wraps "1", "2", "all", "skip" with instruction
  // if (isMenuSelection && activeHsdId) {
  //   text = `I select: ${text}. Proceed with analyzing only the selected item(s) from the menu above. Do NOT repeat Phase 1 or re-read the article.`
  // }

  // Currently: send text (with HSD prefix if applicable)
  const messageToSend = text;

  port.postMessage({ action: "send", message: messageToSend });
  showTypingIndicator();
  hideOnboarding();
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
  btnHistory.disabled = !enabled;
  if (enabled) inputEl.focus();
}

// ── Auto-scroll state ────────────────────────────────────────────────────────
let userScrolledUp = false;

chatArea.addEventListener("scroll", () => {
  // If user is within 80px of bottom, consider them "at bottom"
  const atBottom = chatArea.scrollHeight - chatArea.scrollTop - chatArea.clientHeight < 80;
  userScrolledUp = !atBottom;
});

function scrollToBottom() {
  if (userScrolledUp) return; // User is reading earlier content, don't jump
  requestAnimationFrame(() => {
    chatArea.scrollTop = chatArea.scrollHeight;
  });
}

function forceScrollToBottom() {
  userScrolledUp = false;
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
  updateRegressionBtnState();
}

let activeHsdTitle = "";
let activeConversationId = "";  // GNAI conversation ID

function updateHeaderSubtitle(title) {
  activeHsdTitle = title || "";
  _renderSubtitle();
  updateRegressionBtnState();
}

function updateConversationId(cid) {
  activeConversationId = cid || "";
  _renderSubtitle();
}

function generateConversationId(hsdId) {
  const ts = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14); // YYYYMMDDHHmmss
  return `${hsdId}_${ts}`;
}

function _renderSubtitle() {
  if (!headerSubtitle) return;
  const titleSpan = document.getElementById("subtitle-title");
  const cidSpan = document.getElementById("subtitle-cid");
  if (titleSpan) titleSpan.textContent = activeHsdTitle;
  if (cidSpan) cidSpan.textContent = activeConversationId ? `CID: ${activeConversationId}` : "";
  const hasContent = !!(activeHsdTitle || activeConversationId);
  headerSubtitle.classList.toggle("show", hasContent);
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
      const confirmed = await showModal(
        "Switch HSD",
        `Switch from HSD ${activeHsdId} to HSD ${hsdId}? This will send the new ID to the current session.`,
        "Switch",
        "Cancel"
      );
      if (!confirmed) return;
    }

    activeHsdId = hsdId;
    updateHeaderTitle();
    hideOnboarding();
    const cid = generateConversationId(hsdId);
    updateConversationId(cid);

    // Extract page title from tab
    const pageTitle = (tab.title || "").trim();
    // HSD-ES titles often look like "<ID> - <Title> - HSD-ES" or just the title
    let hsdTitle = pageTitle
      .replace(/^\d{8,14}\s*[-–—:]\s*/, "")   // strip leading HSD ID
      .replace(/\s*[-–—|]\s*HSD[-\s]?ES.*$/i, "")  // strip trailing "- HSD-ES"
      .trim();
    updateHeaderSubtitle(hsdTitle);

    addSystemMsg(`Imported HSD ID: ${hsdId}`);
    showToast(`HSD ${hsdId} imported`, "success");
    hsdImported = true;

    // Show quick-action button to start analysis (don't auto-send)
    showImportQuickActions(hsdId);
  } catch (e) {
    addSystemMsg("Failed to read current tab. Make sure the extension has tab access.");
  }
}

function showImportQuickActions(hsdId) {
  quickActions.innerHTML = "";
  quickActions.classList.remove("show");

  // Show large centered hero CTA button
  heroCtaBtn.textContent = `🚀 Analyze HSD ${hsdId}`;
  heroCta.classList.add("show");

  // One-time click handler
  const handler = () => {
    heroCta.classList.remove("show");
    hsdImported = false;
    sendUserMessage(`${hsdId} skip any attachment check`, `Analyze HSD ${hsdId}`);
    heroCtaBtn.removeEventListener("click", handler);
  };
  heroCtaBtn.addEventListener("click", handler);
}

// ── Simple Markdown Renderer ───────────────────────────────────────────────

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
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

btnBottom.addEventListener("click", () => {
  forceScrollToBottom();
});

// ── Font Size Control ──────────────────────────────────────────────────────
const FONT_SIZE_MIN = 10;
const FONT_SIZE_MAX = 22;
const FONT_SIZE_STEP = 1;
let chatFontSize = parseInt(localStorage.getItem("chatFontSize") || "14", 10);
chatArea.style.fontSize = chatFontSize + "px";

btnFontUp.addEventListener("click", () => {
  if (chatFontSize < FONT_SIZE_MAX) {
    chatFontSize += FONT_SIZE_STEP;
    chatArea.style.fontSize = chatFontSize + "px";
    localStorage.setItem("chatFontSize", chatFontSize);
  }
});

btnFontDown.addEventListener("click", () => {
  if (chatFontSize > FONT_SIZE_MIN) {
    chatFontSize -= FONT_SIZE_STEP;
    chatArea.style.fontSize = chatFontSize + "px";
    localStorage.setItem("chatFontSize", chatFontSize);
  }
});

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendUserMessage(inputEl.value);
    inputEl.value = "";
    inputEl.style.height = "auto";
  }
});

btnNew.addEventListener("click", async () => {
  // Skip confirmation if session is empty
  if (sessionMessages.length === 0 && !activeHsdId) {
    startNewSession();
    return;
  }

  const confirmed = await showModal(
    "Start New Session",
    "Leave current session and start a new one? Current session will be saved to history.",
    "New Session",
    "Cancel"
  );
  if (!confirmed) return;

  startNewSession();
});

function startNewSession() {
  // Save current session before creating new
  saveCurrentSession();

  // Reset chat area and state
  chatArea.innerHTML = "";
  quickActions.classList.remove("show");
  quickActions.innerHTML = "";
  activeHsdId = null;
  activeHsdTitle = "";
  activeConversationId = "";
  sessionMessages = [];
  updateHeaderTitle();
  updateHeaderSubtitle("");
  updateConversationId("");
  showOnboarding();
  heroCta.classList.remove("show");
  hidePostAnalysisPanel();
  _postAnalysisShown = false;

  // Push new empty session at front, shift others down
  sessions.unshift({
    hsdId: "",
    hsdTitle: "",
    conversationId: "",
    messages: [],
    timestamp: Date.now(),
  });
  sessions = sessions.slice(0, MAX_SESSIONS);
  persistSessions();

  if (port) {
    port.postMessage({ action: "start_session" });
  }
}

btnStop.addEventListener("click", () => {
  if (port) {
    port.postMessage({ action: "stop_session" });
  }
});

// ── Initialize ─────────────────────────────────────────────────────────────

// ── Session Functions ─────────────────────────────────────────────────────

function saveCurrentSession() {
  if (!activeHsdId && sessionMessages.length === 0) return;
  if (sessions.length === 0) {
    sessions.push({});
  }
  sessions[0] = {
    hsdId: activeHsdId || "",
    hsdTitle: activeHsdTitle || "",
    conversationId: activeConversationId || "",
    messages: [...sessionMessages],
    timestamp: Date.now(),
  };
}

async function persistSessions() {
  try {
    await chrome.storage.local.set({ chatSessions: sessions.slice(0, MAX_SESSIONS) });
  } catch (e) {
    console.error("[sessions] persist error:", e);
  }
}

async function loadSessions() {
  try {
    const stored = await chrome.storage.local.get({ chatSessions: [] });
    sessions = Array.isArray(stored.chatSessions) ? stored.chatSessions : [];
  } catch (e) {
    sessions = [];
  }
}

function switchToSession(index) {
  if (index < 1 || index >= sessions.length) return;

  // Save current active session
  saveCurrentSession();

  // Move target to front
  const target = sessions.splice(index, 1)[0];
  sessions.unshift(target);

  // Load into active state
  activeHsdId = target.hsdId || null;
  activeHsdTitle = target.hsdTitle || "";
  activeConversationId = target.conversationId || "";
  sessionMessages = [...(target.messages || [])];

  // Update UI
  updateHeaderTitle();
  updateHeaderSubtitle(activeHsdTitle);
  updateConversationId(activeConversationId);
  rebuildChatArea();

  persistSessions();
}

function rebuildChatArea() {
  chatArea.innerHTML = "";
  for (const msg of sessionMessages) {
    if (msg.role === "user") {
      addUserMsg(msg.content);
    } else if (msg.role === "assistant") {
      const el = addAiMsg("");
      el.innerHTML = renderMarkdown(msg.content);
    }
  }
  forceScrollToBottom();
}

function closeHistoryMenu() {
  const menu = document.getElementById("historyMenu");
  if (menu) menu.classList.remove("show");
}

function openHistoryMenu() {
  const menu = document.getElementById("historyMenu");
  if (!menu) return;

  // Toggle
  if (menu.classList.contains("show")) {
    menu.classList.remove("show");
    return;
  }

  // Save current session state before showing menu
  saveCurrentSession();

  menu.innerHTML = "";

  // Title
  const savedCount = sessions.length > 1 ? sessions.length - 1 : 0;
  const title = document.createElement("div");
  title.className = "history-menu-title";
  title.textContent = `Session History (${savedCount})`;
  menu.appendChild(title);

  // Show sessions 1+ (skip index 0 = current active)
  const savedSessions = sessions.slice(1);
  if (savedSessions.length === 0) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "No saved sessions yet";
    menu.appendChild(empty);
  } else {
    savedSessions.forEach((entry, i) => {
      const row = document.createElement("div");
      row.className = "history-item";

      // Info section (clickable to load)
      const info = document.createElement("div");
      info.className = "history-item-info";
      info.style.cursor = "pointer";

      const hsdLine = document.createElement("div");
      hsdLine.className = "history-item-hsd";
      hsdLine.textContent = entry.hsdId ? `HSD ${entry.hsdId}` : "Session";
      info.appendChild(hsdLine);

      if (entry.hsdTitle) {
        const titleLine = document.createElement("div");
        titleLine.className = "history-item-title";
        titleLine.textContent = entry.hsdTitle;
        info.appendChild(titleLine);
      }

      const timeLine = document.createElement("div");
      timeLine.className = "history-item-time";
      const cidText = entry.conversationId ? `CID: ${entry.conversationId}` : "";
      const timeText = formatTimestamp(entry.timestamp);
      timeLine.textContent = [cidText, timeText].filter(Boolean).join(" \u2022 ");
      info.appendChild(timeLine);

      info.addEventListener("click", () => {
        closeHistoryMenu();
        switchToSession(i + 1);
      });
      row.appendChild(info);

      // Delete button
      const delBtn = document.createElement("button");
      delBtn.className = "history-delete-btn";
      delBtn.innerHTML = "&#128465;"; // trash can
      delBtn.title = "Delete this session";
      delBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const confirmed = await showModal(
          "Delete Session",
          `Delete history for HSD ${entry.hsdId || "this session"}?`,
          "Delete",
          "Cancel"
        );
        if (!confirmed) return;
        sessions.splice(i + 1, 1);
        persistSessions();
        showToast("Session deleted", "success");
        openHistoryMenu(); // refresh menu
      });
      row.appendChild(delBtn);

      menu.appendChild(row);
    });
  }

  menu.classList.add("show");
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

// ── Session Event Listeners ───────────────────────────────────────────────

btnHistory.addEventListener("click", openHistoryMenu);

btnImport.addEventListener("click", importHsdFromWebpage);

// Close history menu on click outside
document.addEventListener("click", (e) => {
  const menu = document.getElementById("historyMenu");
  if (menu && menu.classList.contains("show") && !menu.contains(e.target) && e.target !== btnHistory) {
    closeHistoryMenu();
  }
});

// Close history menu on Escape
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeHistoryMenu();
  }
});

// Save session when page is being hidden
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") {
    saveCurrentSession();
    persistSessions();
  }
});

// ══════════════════════════════════════════════════════════════════════════════
// REGRESSION TOOL MODE
// ══════════════════════════════════════════════════════════════════════════════

const mainView = document.getElementById("main-view");
const regressionView = document.getElementById("regression-view");
const regressionArea = document.getElementById("regression-area");
const regressionInput = document.getElementById("regression-input");
const regressionSendBtn = document.getElementById("regression-send-btn");
const regressionHsdInfo = document.getElementById("regression-hsd-info");
const btnRegression = document.getElementById("btn-regression");
const btnBackToChat = document.getElementById("btn-back-to-chat");

let isRegressionMode = false;
const HEADER_COLOR_CHAT = "#5F80AB";
const HEADER_COLOR_REGRESSION = "#b8860b";  // dark goldenrod (土黃色)

function updateRegressionBtnState() {
  // R button requires both HSD ID and title to be available
  btnRegression.disabled = !(activeHsdId && activeHsdTitle);
}

function switchToRegressionMode() {
  isRegressionMode = true;

  // Pass HSD ID + title info
  const hsdInfo = activeHsdId ? `HSD: ${activeHsdId}` : "No HSD loaded";
  const titleInfo = activeHsdTitle ? ` — ${activeHsdTitle}` : "";
  regressionHsdInfo.textContent = ` | ${hsdInfo}${titleInfo}`;

  // Switch views
  mainView.style.display = "none";
  regressionView.style.display = "flex";

  // Change header appearance
  document.querySelector(".header").style.background = HEADER_COLOR_REGRESSION;
  headerTitle.textContent = "Regression Tool";
  statusBadge.textContent = "Regression Check";
  statusBadge.className = "header-status connected";

  // Focus input
  regressionInput.focus();
}

function switchToChatMode() {
  isRegressionMode = false;

  // Switch views
  regressionView.style.display = "none";
  mainView.style.display = "flex";

  // Restore header appearance
  document.querySelector(".header").style.background = HEADER_COLOR_CHAT;
  updateHeaderTitle();
  // Restore status based on connection
  if (port) {
    port.postMessage({ action: "health" });
  } else {
    setStatus("disconnected", "Offline");
  }

  inputEl.focus();
}

// Regression input/output (placeholder — to be developed further)
function addRegressionMsg(text, role) {
  const el = document.createElement("div");
  el.className = role === "user" ? "msg msg-user" : "msg msg-ai";
  el.textContent = text;
  regressionArea.appendChild(el);
  regressionArea.scrollTop = regressionArea.scrollHeight;
}

function sendRegressionMessage() {
  const text = regressionInput.value.trim();
  if (!text) return;

  addRegressionMsg(text, "user");
  regressionInput.value = "";
  regressionInput.style.height = "auto";

  // TODO: Hook up regression logic here
  // For now, echo back with placeholder response
  addRegressionMsg(`[Regression Tool] Received: "${text}"\n\nHSD: ${activeHsdId || "N/A"}\nTitle: ${activeHsdTitle || "N/A"}\n\n(Regression logic not yet implemented)`, "system");
}

// Event listeners
btnRegression.addEventListener("click", switchToRegressionMode);
btnBackToChat.addEventListener("click", switchToChatMode);

regressionSendBtn.addEventListener("click", sendRegressionMessage);
regressionInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendRegressionMessage();
  }
});
regressionInput.addEventListener("input", () => {
  regressionInput.style.height = "auto";
  regressionInput.style.height = Math.min(regressionInput.scrollHeight, 120) + "px";
});

// ── Init ───────────────────────────────────────────────────────────────────

connectPort();
setInputEnabled(false);

// Load saved sessions and restore active session UI
loadSessions().then(() => {
  if (sessions.length > 0 && sessions[0].messages && sessions[0].messages.length > 0) {
    const active = sessions[0];
    activeHsdId = active.hsdId || null;
    activeHsdTitle = active.hsdTitle || "";
    activeConversationId = active.conversationId || "";
    sessionMessages = [...active.messages];
    updateHeaderTitle();
    updateHeaderSubtitle(activeHsdTitle);
    updateConversationId(activeConversationId);
    rebuildChatArea();
    hideOnboarding();
  }
});

// Auto-start: connect to bridge
setTimeout(async () => {
  if (!port) return;
  setStatus("connected", "Connecting...");
  showConnectionSplash("Connecting to bridge server...", "Initializing session");
  port.postMessage({ action: "start_session" });
}, 300);
