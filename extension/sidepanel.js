/**
 * sidepanel.js — Chat Mode Assistant UI
 *
 * Handles:
 * - Chat message display (streaming markdown)
 * - Tool execution progress indicatorj
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
  { label: "📋 Suggestion",        prompt: "Provide a brief summary version of next step suggestion with table style.Skip all attachment check, include latest action item if issue still open",              display: "Suggestion of next step",         group: "post", show: "post-analysis" },
  { label: "🔍 Potential Root Cause",     prompt: "What is the most likely root cause? (skip all attachment check)",                            display: "Potential Root Cause",      group: "post", show: "post-analysis" },
  { label: "📝 Lastest Action Items",   prompt: "List latest three comment's action items and who is action owner.",                             display: "Latest Action Items",    group: "post", show: "post-analysis" },
  { label: "🔄 More Similiar issues",      prompt: "List 10 similar issues' ID, title and score by table style.",        display: "List 10 similiar issues",       group: "post", show: "post-analysis" },
 
];

// ── DOM refs ───────────────────────────────────────────────────────────────
const chatArea = document.getElementById("chat-area");
const quickActions = document.getElementById("quick-actions");
const quickActionsRegression = document.getElementById("quick-actions-regression");
const inputEl = document.getElementById("input");
const sendBtn = document.getElementById("send-btn");
const btnNew = document.getElementById("btn-new");
const btnStop = document.getElementById("btn-stop");
const btnImport = document.getElementById("btn-import");
const btnSave = document.getElementById("btn-save");
const btnBottom = document.getElementById("btn-scroll-down");
const btnFontUp = document.getElementById("btn-font-up");
const btnFontDown = document.getElementById("btn-font-down");
const headerTitle = document.getElementById("header-title");
const headerSubtitle = document.getElementById("header-subtitle");
const statusBadge = document.getElementById("status-badge");
const btnHistory = null; // removed — replaced by tab bar
const btnSettings = document.getElementById("btn-settings");
const btnPopout = document.getElementById("btn-popout");
const btnResetConnection = document.getElementById("btn-reset-connection");
const connectionResetResult = document.getElementById("connection-reset-result");
const onboardingEl = document.getElementById("onboarding");
const onboardingImportBtn = document.getElementById("onboarding-import-btn");
const onboardingHsdInput = document.getElementById("onboarding-hsd-input");
const onboardingGoBtn = document.getElementById("onboarding-go-btn");
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

// ── Scroll Button Position ────────────────────────────────────────────────────────────────
const _inputArea = document.querySelector(".input-area");

function updateScrollBtnBottom() {
  const inputH = _inputArea ? _inputArea.offsetHeight : 60;
  const panelH = postAnalysisPanel.classList.contains("show")
    ? postAnalysisPanel.offsetHeight
    : 0;
  btnBottom.style.bottom = (inputH + panelH + 12) + "px";
}

// Watch post-analysis panel height changes (handles expand/collapse animation)
new ResizeObserver(() => updateScrollBtnBottom()).observe(postAnalysisPanel);

// ── Custom Modal ─────────────────────────────────────────────────────────────────────────
let _modalResolve = null;

function showModal(title, message, confirmText = "Confirm", cancelText = "Cancel") {
  return new Promise((resolve) => {
    _modalResolve = resolve;
    modalTitle.textContent = title;
    modalMessage.textContent = message;
    modalConfirmBtn.textContent = confirmText;
    if (cancelText) {
      modalCancelBtn.textContent = cancelText;
      modalCancelBtn.style.display = "";
    } else {
      modalCancelBtn.style.display = "none";
    }
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
  enableBottomInput();
}

function showOnboarding() {
  if (onboardingEl) onboardingEl.style.display = "flex";
  disableBottomInput();
}

function disableBottomInput() {
  inputEl.disabled = true;
  sendBtn.disabled = true;
  btnFontUp.disabled = true;
  btnFontDown.disabled = true;
}

function enableBottomInput() {
  inputEl.disabled = false;
  sendBtn.disabled = false;
  btnFontUp.disabled = false;
  btnFontDown.disabled = false;
}

// Initially disable bottom input (onboarding is visible)
disableBottomInput();

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
      postAnalysisPanel.classList.add("collapsed");
      const titleEl = postAnalysisPanel.querySelector(".post-analysis-title");
      if (titleEl) titleEl.textContent = _POST_TITLE_SHORT;
      sendUserMessage(btn.prompt, btn.display);
    });
    postAnalysisGrid.appendChild(el);
  }
  postAnalysisPanel.classList.remove("collapsed");
  postAnalysisPanel.classList.add("show");
  updateScrollBtnBottom();
  scrollToBottom();
}

function hidePostAnalysisPanel() {
  postAnalysisPanel.classList.remove("show");
  updateScrollBtnBottom();
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

// Analysis menu panel close button
document.getElementById("analysis-menu-close")?.addEventListener("click", () => {
  hideAnalysisMenuPanel();
  _showingMenuPanel = false;
  // Restore What's Next if we had an active HSD
  if (activeHsdId && _postAnalysisShown) {
    postAnalysisPanel.classList.remove("collapsed");
    postAnalysisPanel.classList.add("show");
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
let activeSessionIndex = 0;    // index into sessions[] for the currently active tab

// ── Port connection ────────────────────────────────────────────────────────

function connectPort() {
  port = chrome.runtime.connect({ name: "sidepanel" });

  port.onMessage.addListener((msg) => {
    switch (msg.type || msg.action) {
      // File dialog result from browse buttons
      case "file_dialog_result":
        onFileDialogResult(msg.field, msg.path || "");
        break;

      // Session lifecycle
      case "session_started":
        _pendingSessionRestart = false;
        _cancelConnectionTimeout();
        bridgeSessionCid = msg.conversation_id || "";
        if (msg.status !== "already_active") _sessionReadyNoticeShown = false;
        console.log(`[session_started] status=${msg.status} cid="${bridgeSessionCid}" activeCid="${activeConversationId}" match=${bridgeSessionCid === activeConversationId}`);
        // Restore default placeholder (may have been changed by stop reconnect state)
        inputEl.placeholder = "Type a message or HSD ID...";
        if (msg.status === "already_active") {
          // Session was already running (e.g. sidepanel reloaded) — just reconnect
          setStatus("connected", msg.session_waiting_input ? "Connected" : "Processing...");
          setInputEnabled(!!msg.session_waiting_input);
          hideConnectionSplash();
        } else {
          // New session starting — toolkit still loading (can take 30-90s)
          setStatus("connected", "Loading toolkits...");
          updateConnectionSplash("Loading AI toolkit...", "dt gnai chat starting — please wait (up to 90s)");
          // Input stays disabled until SSE 'ready' event
        }
        if (msg.conversation_id) {
          updateConversationId(msg.conversation_id);
        }
        break;
      case "session_stopped":
        if (_suppressNextSessionStopped) {
          // Tab switch interrupted streaming — suppress UI side effects, input already enabled
          _suppressNextSessionStopped = false;
          break;
        }
        if (_pendingSessionRestart) {
          // Lazy restart: bridge stopping to immediately restart — don't show "Session ended"
          setInputEnabled(false);
          break;
        }
        setStatus("disconnected", "Offline");
        removeToolIndicator();
        removeTypingIndicator();
        isStreaming = false;
        currentAiMsg = null;
        currentAiText = "";
        addSystemMsg("Session ended.");
        showToast("Session ended");
        // If there's a known CID, keep input enabled so user can reconnect by sending a message
        bridgeSessionCid = "";  // reset so next send triggers _restartBridgeForSession
        if (activeConversationId) {
          setInputEnabled(true);
          inputEl.placeholder = "Send a message to reconnect to this session...";
        } else {
          setInputEnabled(false);
        }
        break;
      case "session_interrupted":
        removeToolIndicator();
        removeTypingIndicator();
        isStreaming = false;
        currentAiMsg = null;
        currentAiText = "";
        addSystemMsg(uiLang === "zh" ? "已停止目前分析，正在重新連線..." : "Current analysis stopped. Reconnecting...");
        break;

      // Startup progress
      case "startup_status":
        setStatus("connected", msg.message || "Starting...");
        updateConnectionSplash(msg.message || "Starting...", "");
        break;
      case "bridge_unavailable":
        _cancelConnectionTimeout();
        setStatus("disconnected", "No Bridge");
        updateConnectionSplash("Bridge unavailable", "Run: cd bridge && python bridge_server.py");
        addSystemMsg("❌ Bridge server not available. Please run:\n  cd bridge && python bridge_server.py\n\nOr set up auto-launch: .\\install_native_host.ps1");
        setInputEnabled(false);
        break;
      case "session_start_error":
        _cancelConnectionTimeout();
        setStatus("disconnected", "Session Error");
        updateConnectionSplash("Session failed to start", msg.error || "Unknown error");
        addSystemMsg(`❌ Session error: ${msg.error}\n\nMake sure 'dt' is in your PATH.`);
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
      case "cid_mismatch":
        // Requested CID no longer exists on GNAI server — new conversation started
        console.warn(`[cid] mismatch: requested=${msg.requested} actual=${msg.actual}`);
        updateConversationId(msg.actual || "");
        // Also update sessions[activeSessionIndex] so it won't trigger lazy restart loop
        bridgeSessionCid = msg.actual || "";
        if (sessions.length > 0) {
          sessions[activeSessionIndex].conversationId = msg.actual || "";
          persistSessions();
        }
        // Flag: next user message should prepend HSD context to restore GNAI context
        if (activeHsdId) _pendingCidContextRestore = true;
        showToast("⚠️ 舊對話紀錄已過期，已開始新的對話（context 重置）");
        addSystemMsg(`⚠️ 此 session 的對話紀錄已過期（conversation_id 已失效），GNAI 已開始新的空白對話。之前的分析 context 已遺失。`);
        break;
      case "cid_expired":
        // GNAI showed Welcome despite having a CID → conversation expired
        // BUT: if session has no prior AI messages, this is a brand-new CID (first use), not expiry
        const hasPriorConversation = sessionMessages.some(m => m.role === "assistant");
        console.warn(`[cid] expired: requested=${msg.requested_cid} hasPriorConversation=${hasPriorConversation}`);
        if (!hasPriorConversation) {
          // New session, first-time CID — this is normal, not an expiry
          console.log("[cid] ignoring cid_expired for brand-new session (no prior messages)");
          break;
        }
        // Clear the old CID — it's useless now; cid_mismatch will set the new one later
        if (sessions.length > 0) {
          sessions[activeSessionIndex].conversationId = "";
          persistSessions();
        }
        updateConversationId("");
        // Flag so onReady auto-send will prepend HSD context
        if (activeHsdId) _pendingCidContextRestore = true;
        showToast(uiLang === "zh"
          ? "⚠️ 舊 Session 已過期，已自動重置為新 Session"
          : "⚠️ Previous session expired. A new session has been started.");
        addSystemMsg(uiLang === "zh"
          ? `⚠️ 舊的對話 Session 已過期（Conversation ID 已失效），GNAI 已自動開始新的 Session。\n之前的對話 context 已遺失，系統將自動補充 HSD context 重新提問。`
          : `⚠️ Previous session has expired. A new session has been started automatically.\nPrior conversation context is lost. The system will re-attach HSD context and resend your question.`
        );
        break;
      case "usage":
        onUsage(msg.usage);
        break;
      case "error":
        // gnai-level error (e.g. tool execution failure, connection abort)
        removeToolIndicator();
        isStreaming = false;
        finalizeAiMsg();
        {
          // msg.text = GNAI/bridge SSE error; msg.error = Service Worker exception
          const errText = msg.text || msg.error || "";
          const errSource = msg.text ? "GNAI" : msg.error ? "Bridge" : "Unknown";
          const ts = new Date().toLocaleTimeString();
          if (errText) {
            addSystemMsg(`⚠️ Error [${errSource}] (${ts}): ${errText}`);
          } else {
            // Empty error from GNAI — add diagnostic hint
            const raw = JSON.stringify(msg);
            addSystemMsg(`⚠️ Error [${errSource}] (${ts}): GNAI returned an empty error event.\nRaw: ${raw}\n\nThis may indicate a tool execution failure or network issue. Try re-sending your message.`);
          }
        }
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

      case "recovery_progress":
        setStatus("connected", "Resetting...");
        showConnectionSplash(msg.message || "Resetting connection...", "Bridge and CLI will be restarted.");
        if (connectionResetResult) {
          connectionResetResult.className = "connection-reset-result";
          connectionResetResult.style.display = "block";
          connectionResetResult.textContent = msg.message || "Resetting connection...";
        }
        break;

      case "recovery_result": {
        if (btnResetConnection) btnResetConnection.disabled = false;
        const diagnosis = msg.diagnosis || {};
        const layerNames = {
          bridge: uiLang === "zh" ? "Bridge" : "Bridge",
          cli: "CLI",
          interface: uiLang === "zh" ? "介面/串流" : "UI/stream",
          unknown: uiLang === "zh" ? "未知" : "unknown",
        };
        const layer = layerNames[diagnosis.layer] || diagnosis.layer || layerNames.unknown;
        if (msg.ok) {
          setStatus("connected", "Reconnected");
          const text = uiLang === "zh"
            ? `已完成完整重置並重新連線。重置前判斷：${layer}（${diagnosis.detail || diagnosis.code || "無詳細資訊"}）`
            : `Full reset completed. Previous issue was classified as ${layer}: ${diagnosis.detail || diagnosis.code || "no details"}`;
          if (connectionResetResult) {
            connectionResetResult.className = "connection-reset-result success";
            connectionResetResult.textContent = text;
          }
          addSystemMsg(`✅ ${text}`);
        } else {
          setStatus("disconnected", "Reset Failed");
          hideConnectionSplash();
          const text = uiLang === "zh"
            ? `完整重置失敗。重置前判斷：${layer}。失敗原因：${msg.error || diagnosis.detail || "未知錯誤"}`
            : `Full reset failed. Previous issue: ${layer}. Failure: ${msg.error || diagnosis.detail || "unknown error"}`;
          if (connectionResetResult) {
            connectionResetResult.className = "connection-reset-result error";
            connectionResetResult.textContent = text;
          }
          addSystemMsg(`❌ ${text}`);
        }
        break;
      }

      // GNAI config auto-repair events
      case "config_repaired":
        _configAutoFixed = true;
        showToast(uiLang === "zh" ? "⚙️ GNAI 設定檔已自動修復，重新連線中..." : "⚙️ GNAI config repaired, reconnecting...");
        updateConnectionSplash(
          uiLang === "zh" ? "⚙️ 自動修復 GNAI 設定檔" : "⚙️ Auto-repaired GNAI config",
          uiLang === "zh" ? "重新啟動 session..." : "Restarting session..."
        );
        break;
      case "config_repair_failed":
        addSystemMsg(`❌ ${msg.text || "GNAI config error. Please run: .\\bridge\\fix_gnai_config.ps1"}`);
        setStatus("disconnected", "Config Error");
        break;

      // Health check result (also used after port reconnect)
      case "health_result":
        if (msg.status === "stale_instance") {
          setStatus("disconnected", "Bridge Restarted");
          updateConnectionSplash("Bridge instance changed", "Reconnecting to the current bridge process...");
          setInputEnabled(false);
          break;
        }
        if (msg.session_active) {
          const cliState = msg.cli?.state || (msg.session_waiting_input ? "ready" : "processing");
          setStatus("connected", cliState === "ready" ? "Connected" : "Processing...");
          setInputEnabled(!!msg.session_waiting_input);
          if (msg.conversation_id) {
            bridgeSessionCid = msg.conversation_id;
            updateConversationId(msg.conversation_id);
          }
          if (msg.session_waiting_input) hideConnectionSplash();
        } else if (msg.cli?.state === "exited") {
          setStatus("disconnected", "CLI Exited");
          const detail = msg.cli.last_error?.detail || "The dt chat process stopped unexpectedly.";
          updateConnectionSplash("CLI process exited", detail);
          setInputEnabled(false);
        } else {
          setStatus("connected", "No Session");
        }
        break;

      // Errors (from Service Worker — SW-level exceptions)
      case "sw_error":
        addSystemMsg(`❌ Bridge Error: ${msg.error || "Unknown"}`);
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

  // Update status bar with current progress block / ASCII progress bar label
  if (progressFilterEnabled) {
    const { blockLabel, inBlock, progressLabel, progressDone } = getProgressFilteredText(currentAiText);
    if (inBlock && blockLabel) {
      // Inside ===...=== block: show the label
      setStatus("connected", blockLabel.substring(0, 50));
    } else if (!inBlock && blockLabel && !progressLabel) {
      // Block just closed, no progress bar yet: ✅ block label
      setStatus("connected", `✅ ${blockLabel.substring(0, 48)}`);
    } else if (progressLabel) {
      // ASCII progress bar: ⏳ for in-progress, ✅ for 100%
      setStatus("connected", progressDone
        ? `✅ ${progressLabel.substring(0, 48)}`
        : `⏳ ${progressLabel.substring(0, 48)}`);
    }
  }

  // Skip render entirely if tab is not visible
  if (document.hidden) return;

  // Debounced render for performance (dynamic interval based on text size)
  if (renderTimer) clearTimeout(renderTimer);
  renderTimer = setTimeout(() => {
    if (!currentAiMsg) return;

    // When progress filter is on, render only the filtered (non-block) text
    if (progressFilterEnabled) {
      const { display } = getProgressFilteredText(currentAiText);
      currentAiMsg.innerHTML = renderMarkdown(display);
      scrollToBottom();
      return;
    }

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

  // Capture AI text BEFORE finalizeAiMsg() clears it
  const aiContent = currentAiText;
  finalizeAiMsg();

  // Track AI response in session messages when we have accumulated text
  if (aiContent) {
    sessionMessages.push({ role: "assistant", content: aiContent });
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

  // Auto-send pending message (from lazy session switch)
  if (_pendingSendMessage) {
    let msg = _pendingSendMessage;
    _pendingSendMessage = null;
    // If CID expired during restart, prepend HSD context so GNAI knows what we're talking about
    if (_pendingCidContextRestore && activeHsdId) {
      _pendingCidContextRestore = false;
      if (!msg.includes(activeHsdId)) {
        msg = `[HSD ${activeHsdId}] ${msg}`;
      }
      console.log(`[onReady] CID expired → prepended HSD context: "${msg.slice(0, 80)}..."`);
    }
    console.log(`[onReady] auto-sending pending message: "${msg.slice(0, 50)}..."`);
    isStreaming = true;
    setTimeout(() => {
      port.postMessage({ action: "send", message: msg });
      showTypingIndicator();
    }, 100);
    return;  // Input stays disabled; will enable when AI responds
  }

  // If this is the first ready after session start, show welcome
  // But only if there are existing messages (not a brand-new empty session with onboarding)
  if (!accumulatedAnswer && !isLogAnalysisMode && sessionMessages.length > 0 && !_sessionReadyNoticeShown) {
    _sessionReadyNoticeShown = true;
    hideOnboarding();
    addSystemMsg("Session ready. Type an HSD ID to begin analysis.");
  }

  // Parse accumulated answer for quick-action buttons (disabled for manual testing)
  // if (accumulatedAnswer) {
  //   generateQuickActions(accumulatedAnswer);
  // }

  // Parse MENU block from AI response → show as buttons in What's Next panel
  // (Inline [Click] buttons are injected in finalizeAiMsg instead)

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
  hideConnectionSplash();

  // If config was auto-repaired, restart session automatically
  if (_configAutoFixed) {
    _configAutoFixed = false;
    setTimeout(() => {
      if (port) port.postMessage({ action: "start_session" });
    }, 500);
    return;
  }

  setInputEnabled(true);
}

function finalizeAiMsg() {
  if (currentAiMsg && currentAiText) {
    if (renderTimer) clearTimeout(renderTimer);
    // Always do a full re-render on finalize for correctness
    frozenNode = null;
    tailNode = null;
    const finalDisplay = progressFilterEnabled
      ? getProgressFilteredText(currentAiText).display
      : currentAiText;
    if (autoInteractEnabled) {
      const menuItems = extractMenuItems(currentAiText);
      if (menuItems.length > 0) {
        currentAiMsg.innerHTML = renderMenuItemsWithButtons(finalDisplay, menuItems);
        bindMenuClickEvents(currentAiMsg, menuItems);
      } else {
        currentAiMsg.innerHTML = renderMarkdown(finalDisplay);
      }
    } else {
      currentAiMsg.innerHTML = renderMarkdown(finalDisplay);
    }
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
 * Restart bridge for a different conversation ID (lazy session switch).
 * Called automatically when sendUserMessage detects CID mismatch.
 */
function _restartBridgeForSession() {
  if (!port) return;
  _pendingSessionRestart = true;
  const restartMsg = { action: "restart_session" };
  if (activeConversationId) restartMsg.conversation_id = activeConversationId;
  port.postMessage(restartMsg);
  showConnectionSplash("切換 Session...", "載入對話紀錄，請稍候（最多 90 秒）");
}

/**
 * Send a message to GNAI via the bridge.
 * @param {string} text - The actual prompt sent to GNAI
 * @param {string} [displayText] - What to show in chat area (defaults to text)
 *   When called from quick buttons, displayText differs from text.
 *   When called from input box, they are the same.
 */
function sendUserMessage(text, displayText) {
  if (!text.trim() || !port) return;
  // Guard: block input while AI is streaming to prevent accidental interruption
  if (isStreaming) {
    console.log("[sendUserMessage] blocked — AI is still streaming");
    return;
  }

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

  // Modification 1c: CID context restore — after cid_mismatch, prepend HSD ID so GNAI regains context
  if (_pendingCidContextRestore && activeHsdId) {
    _pendingCidContextRestore = false;
    if (!text.includes(activeHsdId)) {
      text = `[HSD ${activeHsdId}] ${text}`;
    }
  }

  // Modification 2: Menu selection prefix — wraps "1", "2", "all", "skip" with instruction
  // if (isMenuSelection && activeHsdId) {
  //   text = `I select: ${text}. Proceed with analyzing only the selected item(s) from the menu above. Do NOT repeat Phase 1 or re-read the article.`
  // }

  // Currently: send text (with HSD prefix if applicable)
  // Modification 3: Language instruction — append zh instruction when UI is set to zh
  // Skip for menu selections (1, 2, 3, all, skip, etc.) to avoid confusing GNAI's menu parser
  let messageToSend = text;
  const isMenuSelection = /^\s*(\d{1,2}|all|skip)\s*$/i.test(text.trim());
  if (uiLang === "zh" && !isMenuSelection) {
    messageToSend += " (請使用繁體中文回答)";
  }

  // Lazy bridge restart: if bridge is on a different session, queue message and restart
  if (bridgeSessionCid !== activeConversationId) {
    console.log(`[lazy-restart] CID mismatch: bridge="${bridgeSessionCid}" active="${activeConversationId}" → queueing message and restarting`);
    _pendingSendMessage = messageToSend;
    _restartBridgeForSession();
    hideOnboarding();
    return;
  }

  isStreaming = true;
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
  const el = document.getElementById("tool-progress");
  if (!el) return;
  el.innerHTML = `<div class="spinner"></div><span>Running: ${escapeHtml(text)}</span>`;
  el.style.display = "flex";
}

function _updateProgressStatus(text) {
  // Show progress text (from answer chunks) in the tool-progress status bar
  const el = document.getElementById("tool-progress");
  if (!el) return;
  el.innerHTML = `<div class="spinner"></div><span>${escapeHtml(text)}</span>`;
  el.style.display = "flex";
}

function removeToolIndicator() {
  const el = document.getElementById("tool-progress");
  if (el) {
    el.style.display = "none";
    el.innerHTML = "";
  }
}

function setStatus(cls, text) {
  statusBadge.className = `header-status ${cls}`;
  statusBadge.textContent = text;
}

function setInputEnabled(enabled) {
  inputEl.disabled = !enabled;
  sendBtn.disabled = !enabled;
  btnImport.disabled = !enabled;
  // Protect against accidental interruption: disable actions that mutate the
  // session while AI is running. Settings remains available for recovery.
  if (btnNew) btnNew.disabled = !enabled;
  if (btnSave) btnSave.disabled = !enabled;
  // Tab bar clicks should also be gated
  const tabItems = document.querySelectorAll(".tab-item");
  tabItems.forEach(tab => { tab.style.pointerEvents = enabled ? "" : "none"; });
  if (enabled) inputEl.focus();

  // Log Analysis Mode: the header status dot collapses to a colorless circle
  // when "connected" (no visible text), so it can't tell the user whether
  // GNAI is still working. Mirror the same busy/ready signal in a dedicated
  // status pill inside the Log Analysis bar instead.
  if (isLogAnalysisMode) {
    setLogAnalysisStatus(enabled ? "ready" : "busy");
    if (btnLogAnalyze) btnLogAnalyze.disabled = !enabled || !logPathInput.value.trim();
  }
}

function setLogAnalysisStatus(state) {
  if (!logAnalysisStatus) return;
  logAnalysisStatus.className = `log-analysis-status ${state}`;
  logAnalysisStatus.textContent = state === "busy" ? "⏳ Analyzing..." : "✅ Ready";
}

// ── Auto-scroll state ────────────────────────────────────────────────────────
let userScrolledUp = false;

chatArea.addEventListener("scroll", () => {
  // If user is within 80px of bottom, consider them "at bottom"
  const atBottom = chatArea.scrollHeight - chatArea.scrollTop - chatArea.clientHeight < 80;
  userScrolledUp = !atBottom;
  btnBottom.classList.toggle("show", userScrolledUp);
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
let bridgeSessionCid = "";      // CID the bridge process was actually started with
let _pendingSendMessage = null; // message queued to send after lazy bridge restart
let _pendingCidContextRestore = false; // true after cid_mismatch — next send should prepend HSD context
let _configAutoFixed = false;   // set when bridge auto-repaired config.yaml; triggers auto-restart on end
let _suppressNextSessionStopped = false; // suppress session_stopped side effects on tab switch
let _pendingSessionRestart = false;      // true while an atomic session switch is in progress
let _sessionReadyNoticeShown = false;    // suppress duplicate ready notices after SSE reconnects

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
  // In popup mode, currentWindow is the popup itself (no tabs).
  // Fall back to the last focused normal browser window.
  let [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab && _isPopup) {
    [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  }
  if (!tab && _isPopup) {
    // Still nothing — try any normal window
    const tabs = await chrome.tabs.query({ active: true, windowType: "normal" });
    tab = tabs[0];
  }
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
        uiLang === "zh" ? "切換 HSD" : "Switch HSD",
        uiLang === "zh"
          ? `從 HSD ${activeHsdId} 切換到 HSD ${hsdId}？新的 ID 將傳送到目前的 session。`
          : `Switch from HSD ${activeHsdId} to HSD ${hsdId}? This will send the new ID to the current session.`,
        uiLang === "zh" ? "切換" : "Switch",
        uiLang === "zh" ? "取消" : "Cancel"
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
    // Send full instruction to GNAI; display text stays clean in the UI
    sendUserMessage(`Analyze HSD ${hsdId}, use rich emoji style in the response`, `Analyze HSD ${hsdId}`);
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
  btnBottom.classList.remove("show");
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
  // Block if at max capacity
  if (sessions.length >= MAX_SESSIONS) {
    await showModal(
      uiLang === "zh" ? `已達 Tab 上限 (${MAX_SESSIONS})` : `Tab Limit Reached (${MAX_SESSIONS})`,
      uiLang === "zh"
        ? `目前已有 ${MAX_SESSIONS} 個 session，請先關閉不需要的 tab 再新增。`
        : `You have ${MAX_SESSIONS} sessions open. Please close an existing tab before adding a new one.`,
      uiLang === "zh" ? "確定" : "OK",
      null
    );
    return;
  }

  // Skip confirmation if session is empty
  if (sessionMessages.length === 0 && !activeHsdId) {
    startNewSession();
    return;
  }

  const confirmed = await showModal(
    uiLang === "zh" ? "開新 Session" : "Start New Session",
    uiLang === "zh"
      ? "離開目前 session 並開新的？目前的 session 將儲存到歷史記錄。"
      : "Leave current session and start a new one? Current session will be saved to history.",
    uiLang === "zh" ? "新增" : "New Session",
    uiLang === "zh" ? "取消" : "Cancel"
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
  _showingMenuPanel = false;
  hideAnalysisMenuPanel();

  // Push new empty session at front, shift others down
  sessions.unshift({
    hsdId: "",
    hsdTitle: "",
    conversationId: "",
    messages: [],
    timestamp: Date.now(),
  });
  sessions = sessions.slice(0, MAX_SESSIONS);
  activeSessionIndex = 0;
  persistSessions();

  if (port) {
    bridgeSessionCid = "";  // new session has no CID yet
    showConnectionSplash("Starting new session...", "");
    _startConnectionTimeout();
    port.postMessage({ action: "start_session" });
  }
}

btnStop.addEventListener("click", () => {
  if (port) {
    setInputEnabled(false);
    const interruptMsg = {
      action: "interrupt_session",
      assistant: isLogAnalysisMode ? "displaydebugger" : "sighting_assistant",
    };
    if (activeConversationId) interruptMsg.conversation_id = activeConversationId;
    port.postMessage(interruptMsg);
  }
});

// ── Initialize ─────────────────────────────────────────────────────────────

// ── Session Functions ─────────────────────────────────────────────────────

function saveCurrentSession() {
  if (!activeHsdId && sessionMessages.length === 0) return;
  if (sessions.length === 0) {
    sessions.push({});
    activeSessionIndex = 0;
  }
  sessions[activeSessionIndex] = {
    hsdId: activeHsdId || "",
    hsdTitle: activeHsdTitle || "",
    conversationId: activeConversationId || "",
    messages: [...sessionMessages],
    postAnalysisShown: _postAnalysisShown,
    timestamp: Date.now(),
  };
}

async function persistSessions() {
  try {
    await chrome.storage.local.set({ chatSessions: sessions.slice(0, MAX_SESSIONS) });
    renderTabBar();
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

// Restore post-analysis panel for a session: show collapsed if previously shown, else hide
function _restorePostAnalysisPanel(shown) {
  if (shown) {
    _postAnalysisShown = false; // reset guard so showPostAnalysisPanel() rebuilds it
    showPostAnalysisPanel();   // builds buttons + shows panel
    postAnalysisPanel.classList.add("collapsed"); // immediately collapse
    const titleEl = postAnalysisPanel.querySelector(".post-analysis-title");
    if (titleEl) titleEl.textContent = _POST_TITLE_SHORT;
  } else {
    hidePostAnalysisPanel();
    _postAnalysisShown = false;
  }
}

async function switchToSession(index) {
  if (index < 0 || index >= sessions.length || index === activeSessionIndex) return;

  // If analysis is running, confirm before interrupting
  if (isStreaming) {
    const confirmed = await showModal(
      uiLang === "zh" ? "切換 Session" : "Switch Session",
      uiLang === "zh"
        ? "目前正在進行分析，切換 session 將會中斷現有分析。確定要切換嗎？"
        : "Analysis is in progress. Switching session will interrupt it. Continue?",
      uiLang === "zh" ? "切換" : "Switch",
      uiLang === "zh" ? "取消" : "Cancel"
    );
    if (!confirmed) return;
    _suppressNextSessionStopped = true;
    if (port) port.postMessage({ action: "stop_session" });
    isStreaming = false;
    removeToolIndicator();
    removeTypingIndicator();
  }

  // Save current active session
  saveCurrentSession();

  // Switch to the target index (no reordering — tab stays in place)
  activeSessionIndex = index;
  const target = sessions[activeSessionIndex];

  // Load into active state
  activeHsdId = target.hsdId || null;
  activeHsdTitle = target.hsdTitle || "";
  activeConversationId = target.conversationId || "";
  sessionMessages = [...(target.messages || [])];

  // Reset pending state from previous tab to prevent cross-tab contamination
  _pendingSendMessage = null;
  _pendingCidContextRestore = false;
  _pendingSessionRestart = false;
  currentAiMsg = null;
  currentAiText = "";
  accumulatedAnswer = "";
  _showingMenuPanel = false;
  hideAnalysisMenuPanel();

  console.log(`[switchToSession] → tab ${index}, hsd=${activeHsdId}, cid=${activeConversationId}, bridgeCid=${bridgeSessionCid}`);

  // Update UI
  updateHeaderTitle();
  updateHeaderSubtitle(activeHsdTitle);
  updateConversationId(activeConversationId);
  rebuildChatArea();
  _restorePostAnalysisPanel(target.postAnalysisShown || false);
  quickActions.classList.remove("show");
  quickActions.innerHTML = "";
  heroCta.classList.remove("show");
  if (sessionMessages.length === 0 && !activeHsdId) showOnboarding();
  else hideOnboarding();

  // Lazy restart: bridge will switch to this session's CID on next send
  setInputEnabled(true);
  setStatus("connected", "Connected");

  persistSessions();
  renderTabBar();
}

// ── Tab Bar ─────────────────────────────────────────────────────────────────

// (tab bar drag-to-scroll disabled)

function renderTabBar() {
  const bar = document.getElementById("tab-bar");
  if (!bar) return;
  bar.innerHTML = "";

  sessions.forEach((session, i) => {
    const tab = document.createElement("div");
    tab.className = "tab-item" + (i === activeSessionIndex ? " active" : "");
    tab.title = session.hsdTitle || (session.hsdId ? `HSD ${session.hsdId}` : "New Session");

    const label = document.createElement("span");
    label.className = "tab-label";
    label.textContent = session.hsdId ? `HSD ${session.hsdId}` : "New Session";
    tab.appendChild(label);

    const closeBtn = document.createElement("span");
    closeBtn.className = "tab-close";
    closeBtn.innerHTML = "&times;";
    closeBtn.title = "Close tab";
    closeBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await closeTab(i);
    });
    tab.appendChild(closeBtn);

    tab.addEventListener("click", () => switchToSession(i));

    bar.appendChild(tab);
  });

  // + button
  const addBtn = document.createElement("button");
  addBtn.className = "tab-add";
  addBtn.textContent = "+";
  addBtn.title = "New session";
  addBtn.addEventListener("click", () => btnNew.click());
  bar.appendChild(addBtn);
}

async function closeTab(index) {
  const session = sessions[index];
  const label = session.hsdId ? `HSD ${session.hsdId}` : "this session";
  const isActive = (index === activeSessionIndex);

  // If closing the active tab while streaming, warn
  if (isActive && isStreaming) {
    const confirmed = await showModal(
      uiLang === "zh" ? "關閉 Tab" : "Close Tab",
      uiLang === "zh"
        ? `目前正在進行分析，關閉此 tab 將中斷分析。確定要關閉 ${label} 嗎？`
        : `Analysis is in progress. Closing this tab will interrupt it. Close ${label}?`,
      uiLang === "zh" ? "關閉" : "Close",
      uiLang === "zh" ? "取消" : "Cancel"
    );
    if (!confirmed) return;
    _suppressNextSessionStopped = true;
    if (port) port.postMessage({ action: "stop_session" });
    isStreaming = false;
    removeToolIndicator();
    removeTypingIndicator();
  } else {
    const confirmed = await showModal(
      uiLang === "zh" ? "關閉 Tab" : "Close Tab",
      uiLang === "zh"
        ? `關閉 ${label}？此 session 將從歷史記錄中移除。`
        : `Close ${label}? This session will be removed from history.`,
      uiLang === "zh" ? "關閉" : "Close",
      uiLang === "zh" ? "取消" : "Cancel"
    );
    if (!confirmed) return;
  }

  if (isActive) {
    // Closing active tab
    if (sessions.length === 1) {
      // Only one tab left — just reset
      startNewSession();
      return;
    }
    sessions.splice(index, 1);
    // Go to the tab to the left, or stay at index 0 if we were at the first tab
    activeSessionIndex = index > 0 ? index - 1 : 0;
    const next = sessions[activeSessionIndex];
    activeHsdId = next.hsdId || null;
    activeHsdTitle = next.hsdTitle || "";
    activeConversationId = next.conversationId || "";
    sessionMessages = [...(next.messages || [])];
    updateHeaderTitle();
    updateHeaderSubtitle(activeHsdTitle);
    updateConversationId(activeConversationId);
    rebuildChatArea();
    _restorePostAnalysisPanel(next.postAnalysisShown || false);
    quickActions.classList.remove("show");
    quickActions.innerHTML = "";
    heroCta.classList.remove("show");
    if (sessionMessages.length === 0 && !activeHsdId) showOnboarding();
    else hideOnboarding();
    // Lazy restart: bridge will switch to this session's CID on next send
    setInputEnabled(true);
    setStatus("connected", "Connected");
  } else {
    sessions.splice(index, 1);
    // If the removed tab was before the active one, shift activeSessionIndex down
    if (index < activeSessionIndex) activeSessionIndex--;
  }

  persistSessions();
  renderTabBar();
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

function closeHistoryMenu() { /* replaced by tab bar */ }

function openHistoryMenu() {
  const menu = null; // replaced by tab bar; kept for compat
  if (!menu) { return; }
  const _unused = document.getElementById("historyMenu");
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
          uiLang === "zh" ? "刪除 Session" : "Delete Session",
          uiLang === "zh"
            ? `刪除 HSD ${entry.hsdId || "此 session"} 的歷史記錄？`
            : `Delete history for HSD ${entry.hsdId || "this session"}?`,
          uiLang === "zh" ? "刪除" : "Delete",
          uiLang === "zh" ? "取消" : "Cancel"
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

btnImport.addEventListener("click", importHsdFromWebpage);

// ── Settings (Language) ───────────────────────────────────────────────────

let uiLang = localStorage.getItem("uiLang") || "en"; // "en" | "zh"

// ── Feature Flags ────────────────────────────────────────────────────────────
let featureLogEnabled        = localStorage.getItem("feature_log")        === "true";  // default: OFF (unchecked on first install)
let featureRegressionEnabled = localStorage.getItem("feature_regression") !== "false";

function applyFeatureFlags() {
  const btnLog        = document.getElementById("btn-log-analysis");
  const btnRegression = document.getElementById("btn-regression");
  const checkLog        = document.getElementById("feature-log-check");
  const checkRegression = document.getElementById("feature-regression-check");

  if (btnLog)        btnLog.style.display        = featureLogEnabled        ? "" : "none";
  if (btnRegression) btnRegression.style.display = featureRegressionEnabled ? "" : "none";
  if (checkLog)        checkLog.checked        = featureLogEnabled;
  if (checkRegression) checkRegression.checked = featureRegressionEnabled;
}

async function toggleFeature(featureKey, label, currentEnabled) {
  const action = currentEnabled ? "停用" : "啟用";
  const confirmed = await showModal(
    `${action} ${label}`,
    `確定要${action} "${label}" 功能嗎？${currentEnabled ? "按鈕將從主介面移除。" : "按鈕將重新出現在主介面。"}`,
    action,
    "取消"
  );
  if (!confirmed) {
    // Revert checkbox state
    applyFeatureFlags();
    return;
  }
  const newEnabled = !currentEnabled;
  localStorage.setItem(featureKey, newEnabled ? "true" : "false");
  return newEnabled;
}

// Init feature flags
applyFeatureFlags();

document.getElementById("feature-log-check")?.addEventListener("change", async () => {
  const result = await toggleFeature("feature_log", "Log Analysis (beta)", featureLogEnabled);
  if (result !== undefined) {
    featureLogEnabled = result;
    // If currently in Log mode and disabling, exit first
    if (!featureLogEnabled && isLogAnalysisMode) await exitLogAnalysisMode();
    applyFeatureFlags();
  }
});

document.getElementById("feature-regression-check")?.addEventListener("change", async () => {
  const result = await toggleFeature("feature_regression", "Regression Checker", featureRegressionEnabled);
  if (result !== undefined) {
    featureRegressionEnabled = result;
    // If currently in Regression mode and disabling, switch back to chat
    if (!featureRegressionEnabled && isRegressionMode) switchToChatMode();
    applyFeatureFlags();
  }
});

function applyLang(lang) {
  uiLang = lang;
  localStorage.setItem("uiLang", lang);
  // Update Send button label
  sendBtn.textContent = lang === "zh" ? "送出" : "Send";
  // Update active state on option buttons
  document.querySelectorAll(".lang-opt").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.lang === lang);
  });
}

// Init language on load
applyLang(uiLang);

// ── Debug Mode Setting ──────────────────────────────────────────────────────
const debugModeCheck = document.getElementById("debug-mode-check");
const debugModeApplyBtn = document.getElementById("debug-mode-apply");
let _debugModeSaved = false; // last saved state

// ── Auto-Interact Mode ────────────────────────────────────────────────────
const autoInteractCheck = document.getElementById("auto-interact-check");
let autoInteractEnabled = false;
let _showingMenuPanel = false; // true while What's Next shows MENU items

(async () => {
  try {
    const stored = await chrome.storage.local.get({ autoInteract: false });
    autoInteractEnabled = !!stored.autoInteract;
    if (autoInteractCheck) autoInteractCheck.checked = autoInteractEnabled;
  } catch { /* ignore */ }
})();

if (autoInteractCheck) {
  autoInteractCheck.addEventListener("change", async () => {
    autoInteractEnabled = autoInteractCheck.checked;
    await chrome.storage.local.set({ autoInteract: autoInteractEnabled });
    showToast(autoInteractEnabled
      ? (uiLang === "zh" ? "✅ 自動互動模式已開啟" : "✅ Auto-Interact Mode enabled")
      : (uiLang === "zh" ? "⭕ 自動互動模式已關閉" : "⭕ Auto-Interact Mode disabled")
    );
  });
}

// ── Progress Block Filter ───────────────────────────────────────────
const progressFilterCheck = document.getElementById("progress-filter-check");
let progressFilterEnabled = false;

(async () => {
  try {
    const stored = await chrome.storage.local.get({ progressFilter: false });
    progressFilterEnabled = !!stored.progressFilter;
    if (progressFilterCheck) progressFilterCheck.checked = progressFilterEnabled;
  } catch { /* ignore */ }
})();

if (progressFilterCheck) {
  progressFilterCheck.addEventListener("change", async () => {
    progressFilterEnabled = progressFilterCheck.checked;
    await chrome.storage.local.set({ progressFilter: progressFilterEnabled });
    showToast(progressFilterEnabled
      ? (uiLang === "zh" ? "✅ 進度區塊隱藏已開啟" : "✅ Progress block filter enabled")
      : (uiLang === "zh" ? "⭕ 進度區塊隱藏已關閉" : "⭕ Progress block filter disabled")
    );
  });
}

/**
 * Filter ===...=== progress blocks from AI text for chat display.
 * @returns {{ display: string, statusText: string, inBlock: boolean }}
 *   display    – text with all progress blocks removed
 *   statusText – last label seen inside a block (e.g. "DONE - CHECKING HSD ATTACHMENTS")
 *   inBlock    – true if the text ends inside an open (unclosed) block
 */
function getProgressFilteredText(text) {
  const isSep        = (line) => /^={10,}\s*$/.test(line);
  const isProgressBar = (line) => /^\[=+[ >]*\]\s*\d+%/.test(line.trim());

  const lines = text.split('\n');
  const displayLines = [];
  let inBlock      = false;
  let blockLabel   = "";   // last label inside ===...=== block
  let progressLabel = "";  // extracted label from last [===] XX% bar
  let progressDone  = false; // true if last progress bar was 100%

  for (const line of lines) {
    if (isSep(line)) {
      inBlock = !inBlock;
      // separator lines hidden from chat
    } else if (inBlock) {
      const t = line.trim();
      if (t) blockLabel = t;
      // block content hidden from chat
    } else if (isProgressBar(line)) {
      // [===...] XX% Description  → hidden from chat, track for status bar
      const m = line.trim().match(/^\[=+[ >]*\]\s*(\d+)%\s*(.*)/);
      if (m) {
        progressDone  = parseInt(m[1]) === 100;
        progressLabel = progressDone ? m[2].trim() : `${m[1]}% ${m[2].trim()}`;
      }
    } else {
      displayLines.push(line);
    }
  }

  // Collapse consecutive blank lines (artifacts from removed progress bars)
  const collapsed = [];
  let blankRun = 0;
  for (const line of displayLines) {
    if (line.trim() === "") {
      blankRun++;
      if (blankRun <= 1) collapsed.push(line);
    } else {
      blankRun = 0;
      collapsed.push(line);
    }
  }

  return { display: collapsed.join('\n'), blockLabel, inBlock, progressLabel, progressDone };
}

/**
 * Extract numbered menu items from raw AI text.
 * Handles both tagged [MENU:START]...[MENU:END] and untagged ── Analysis Menu ── blocks.
 */
function extractMenuItems(text) {
  const items = [];
  const seen = new Set();
  const add = (num, label) => {
    const key = `${num}:${label}`;
    if (!seen.has(key)) { seen.add(key); items.push({ num, label }); }
  };
  const scanBlock = (block) => {
    // Plain numbers: 1. label  or  1) label
    for (const m of block.matchAll(/^\s*(\d+)[.)]\s+(.+)$/gm)) add(m[1], m[2].trim());
    // Emoji numbers: 1️⃣  label
    for (const m of block.matchAll(/^\s*(\d)\uFE0F\u20E3\s+(.+)$/gm)) add(m[1], m[2].trim());
  };

  // Tagged menus [MENU:START...]...[MENU:END]
  for (const m of text.matchAll(/\[MENU:START[^\]]*\]([\s\S]*?)\[MENU:END\]/g)) scanBlock(m[1]);

  // Untagged: ── Analysis Menu ── header
  const headerIdx = text.search(/─{2,}[^─\n]*Analysis Menu[^─\n]*─{2,}/);
  if (headerIdx >= 0) scanBlock(text.substring(headerIdx));

  // ⚠️ No fallback scan — only inject [Click] when explicit menu context is present.
  // This prevents regular numbered lists in AI responses from getting buttons.

  return items;
}

/**
 * Render AI message text with [Click] buttons injected after each menu item.
 * Uses placeholder markers that survive renderMarkdown’s escaping pipeline.
 */
function renderMenuItemsWithButtons(displayText, items) {
  if (items.length === 0) return renderMarkdown(displayText);

  // Helper: inject 【MENUBTN:N】 markers into a scoped section only
  const markSection = (section) => {
    let s = section;
    for (const item of items) {
      const n = item.num;
      s = s.replace(
        new RegExp(`(^[^\n]*${n}\\uFE0F\\u20E3[^\n]*)`, 'gm'),
        (m) => m.includes(`\u3010MENUBTN:${n}\u3011`) ? m : `${m}\u3010MENUBTN:${n}\u3011`
      );
      s = s.replace(
        new RegExp(`(^[ \\t]*${n}[.)]\\s+[^\n]+)`, 'gm'),
        (m) => m.includes(`\u3010MENUBTN:${n}\u3011`) ? m : `${m}\u3010MENUBTN:${n}\u3011`
      );
    }
    return s;
  };

  let text = displayText;

  // For tagged menus: mark INSIDE [MENU:START]...[MENU:END], then strip the tags
  text = text.replace(/\[MENU:START[^\]]*\]([\s\S]*?)\[MENU:END\]/g,
    (_, inner) => markSection(inner));

  // For untagged menus: mark only in the section AFTER ── Analysis Menu ── header
  const headerMatch = text.match(/─{2,}[^─\n]*Analysis Menu[^─\n]*─{2,}/);
  if (headerMatch) {
    const headerEnd = text.indexOf(headerMatch[0]) + headerMatch[0].length;
    text = text.substring(0, headerEnd) + markSection(text.substring(headerEnd));
  }

  // Render markdown
  let html = renderMarkdown(text);

  // Replace markers with button HTML
  html = html.replace(/\u3010MENUBTN:(\d+)\u3011/g,
    (_, num) => ` <button class="menu-click-btn" data-menunum="${num}">Click</button>`);

  return html;
}

/** Bind click handlers to [Click] buttons injected by renderMenuItemsWithButtons. */
function bindMenuClickEvents(msgEl, items) {
  for (const btn of msgEl.querySelectorAll('.menu-click-btn[data-menunum]')) {
    const item = items.find(i => i.num === btn.getAttribute('data-menunum'));
    if (!item) continue;
    const isSkip = /skip/i.test(item.label);
    const prompt = isSkip ? 'skip' : `analysis ${item.num}. ${item.label}`;
    const dispText = `${item.num}. ${item.label}`;
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      msgEl.querySelectorAll('.menu-click-btn').forEach(b => { b.disabled = true; });
      sendUserMessage(prompt, dispText);
    });
  }
}

/**
 * Show parsed menu items as buttons in the What's Next panel.
 */
function hideAnalysisMenuPanel() {
  const panel = document.getElementById("analysis-menu-panel");
  if (panel) panel.classList.remove("show");
}

/** Restore What's Next panel immediately (collapsed) after menu is dismissed. */
function _restoreWhatsNextAfterMenu() {
  if (activeHsdId && _postAnalysisShown) {
    postAnalysisPanel.classList.remove("collapsed");
    postAnalysisPanel.classList.add("show");
    postAnalysisPanel.classList.add("collapsed"); // show collapsed
    const titleEl = postAnalysisPanel.querySelector(".post-analysis-title");
    if (titleEl) titleEl.textContent = _POST_TITLE_SHORT;
  }
}

function showMenuInPanel(menuItems) {
  _showingMenuPanel = true;

  // Hide What's Next panel while menu is shown
  hidePostAnalysisPanel();

  const panel = document.getElementById("analysis-menu-panel");
  const list  = document.getElementById("analysis-menu-list");
  if (!panel || !list) return;

  list.innerHTML = "";

  // Numbered items
  for (const item of menuItems) {
    const el = document.createElement("button");
    el.className = "analysis-menu-item";
    el.textContent = `${item.num}. ${item.label}`;
    el.addEventListener("click", () => {
      hideAnalysisMenuPanel();
      // If label contains "skip", just send "skip" without "analysis" prefix
      const isSkip = /skip/i.test(item.label);
      const fullLabel = `${item.num}. ${item.label}`;
      sendUserMessage(isSkip ? "skip" : `analysis ${fullLabel}`, fullLabel);
    });
    list.appendChild(el);
  }

  // All / Skip standalone buttons
  for (const spec of [{ label: "All", prompt: "all" }, { label: "Skip", prompt: "skip" }]) {
    const el = document.createElement("button");
    el.className = "analysis-menu-item";
    el.textContent = spec.label;
    el.addEventListener("click", () => {
      hideAnalysisMenuPanel();
      sendUserMessage(spec.prompt, spec.label);
    });
    list.appendChild(el);
  }

  panel.classList.add("show");
}

(async () => {
  try {
    const stored = await chrome.storage.local.get({ debugMode: false });
    _debugModeSaved = !!stored.debugMode;
    debugModeCheck.checked = _debugModeSaved;
  } catch { /* ignore */ }
})();

debugModeCheck.addEventListener("change", () => {
  // Show Apply button only when value differs from saved state
  debugModeApplyBtn.style.display = (debugModeCheck.checked !== _debugModeSaved) ? "block" : "none";
});

debugModeApplyBtn.addEventListener("click", async () => {
  const newVal = debugModeCheck.checked;
  const msg = newVal
    ? (uiLang === "zh" ? "啟用 Debug Mode 後，下次啟動 Bridge 時會顯示 CLI 視窗。\n需要重啟 Bridge 才會生效，是否立即重啟？" : "Enabling Debug Mode will show the Bridge console window.\nA Bridge restart is required. Restart now?")
    : (uiLang === "zh" ? "停用 Debug Mode 後，Bridge CLI 視窗將會隱藏。\n需要重啟 Bridge 才會生效，是否立即重啟？" : "Disabling Debug Mode will hide the Bridge console window.\nA Bridge restart is required. Restart now?");

  const confirmed = await showModal(
    uiLang === "zh" ? "套用 Debug Mode" : "Apply Debug Mode",
    msg,
    uiLang === "zh" ? "重啟 Bridge" : "Restart Bridge",
    uiLang === "zh" ? "稍後" : "Later"
  );

  // Save regardless of restart choice
  _debugModeSaved = newVal;
  await chrome.storage.local.set({ debugMode: newVal });
  debugModeApplyBtn.style.display = "none";
  showToast(uiLang === "zh" ? "✅ Debug Mode 設定已儲存" : "✅ Debug Mode setting saved");

  if (confirmed && port) {
    // Restart bridge: stop session → re-launch with new debug flag
    port.postMessage({ action: "stop_session" });
    setTimeout(() => {
      port.postMessage({ action: "restart_bridge" });
    }, 500);
  }
});

btnResetConnection?.addEventListener("click", async () => {
  const confirmed = await showModal(
    uiLang === "zh" ? "完整重置連線" : "Reset Connection",
    uiLang === "zh"
      ? "這會強制關閉目前的 Bridge 與 CLI，啟動全新程序並重新連到目前 Session。畫面中的聊天紀錄不會清除。"
      : "This force-closes the current Bridge and CLI, starts fresh processes, and reconnects the current session. Visible chat history will be preserved.",
    uiLang === "zh" ? "重置並重連" : "Reset & Reconnect",
    uiLang === "zh" ? "取消" : "Cancel"
  );
  if (!confirmed || !port) return;

  btnResetConnection.disabled = true;
  document.getElementById("settingsMenu")?.classList.remove("show");
  setInputEnabled(false);
  removeToolIndicator();
  removeTypingIndicator();
  isStreaming = false;
  currentAiMsg = null;
  currentAiText = "";
  showConnectionSplash(
    uiLang === "zh" ? "正在完整重置連線..." : "Resetting connection...",
    uiLang === "zh" ? "重新啟動 Bridge 與 CLI" : "Restarting Bridge and CLI"
  );

  const recoveryMsg = {
    action: "recover_connection",
    assistant: isLogAnalysisMode ? "displaydebugger" : "sighting_assistant",
  };
  if (activeConversationId) recoveryMsg.conversation_id = activeConversationId;
  port.postMessage(recoveryMsg);
});

// ── Toolkit Update Button ────────────────────────────────────────────────────
document.getElementById("btn-toolkit-update")?.addEventListener("click", async () => {
  const btn = document.getElementById("btn-toolkit-update");
  const resultEl = document.getElementById("toolkit-update-result");
  btn.disabled = true;
  btn.textContent = "⏳ Updating...";
  resultEl.style.display = "none";

  try {
    const bridgeUrl = `http://127.0.0.1:${await (async () => {
      const stored = await chrome.storage.local.get({ bridgePort: 8776 });
      return stored.bridgePort;
    })()}`;
    const resp = await fetch(`${bridgeUrl}/toolkit/update`, { method: "POST" });
    const data = await resp.json();

    if (data.status === "ok") {
      const alreadyLatest = data.stdout.includes("Already up to date");
      btn.textContent = "🔄 Update Toolkit (git pull)";
      resultEl.style.display = "block";
      resultEl.style.color = "#16a34a";
      resultEl.textContent = alreadyLatest
        ? `✅ Already up to date — ${data.commit}`
        : `✅ Updated! ${data.commit}`;
      if (!alreadyLatest) showToast("✅ Toolkit updated — restart session to apply", "success");
    } else {
      btn.textContent = "🔄 Update Toolkit (git pull)";
      resultEl.style.display = "block";
      resultEl.style.color = "#dc2626";
      resultEl.textContent = `❌ ${data.error || data.stderr || "Update failed"}`;
    }
  } catch (e) {
    btn.textContent = "🔄 Update Toolkit (git pull)";
    resultEl.style.display = "block";
    resultEl.style.color = "#dc2626";
    resultEl.textContent = "❌ Bridge not connected";
  } finally {
    btn.disabled = false;
  }
});

btnSettings.addEventListener("click", (e) => {
  e.stopPropagation();
  const menu = document.getElementById("settingsMenu");
  const isOpen = menu.classList.contains("show");
  // Close history menu if open
  closeHistoryMenu();
  menu.classList.toggle("show", !isOpen);
});

document.querySelectorAll(".lang-opt").forEach(btn => {
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    applyLang(btn.dataset.lang);
  });
});

// Close settings menu on click outside
document.addEventListener("click", (e) => {
  const menu = document.getElementById("settingsMenu");
  if (menu && menu.classList.contains("show") && !menu.contains(e.target) && e.target !== btnSettings) {
    menu.classList.remove("show");
  }
});

// ── Pop-out / Pop-in Toggle ──────────────────────────────────────────────────
const _isPopup = new URLSearchParams(window.location.search).has("popup");
const _hostWindowId = Number.parseInt(new URLSearchParams(window.location.search).get("hostWindowId"), 10);

// Update button icon based on mode
if (_isPopup) {
  btnPopout.textContent = "⧉"; // indicate "back to sidepanel"
  btnPopout.title = "Back to sidepanel";
  // In popup mode, hide Import button — only show HSD ID input
  if (onboardingImportBtn) onboardingImportBtn.style.display = "none";
  const divider = onboardingEl && onboardingEl.querySelector(".onboarding-divider");
  if (divider) divider.style.display = "none";
}

// ── Onboarding Import & Go handlers ─────────────────────────────────────────
if (onboardingImportBtn) {
  onboardingImportBtn.addEventListener("click", () => {
    importHsdFromWebpage();
  });
}

if (onboardingGoBtn && onboardingHsdInput) {
  onboardingGoBtn.addEventListener("click", () => {
    const val = onboardingHsdInput.value.trim();
    if (!val) return;
    hideOnboarding();
    sendUserMessage(val);
    onboardingHsdInput.value = "";
  });
  onboardingHsdInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      onboardingGoBtn.click();
    }
  });
}

function _saveStateForTransfer() {
  // Save current state into sessions[activeSessionIndex] before transferring
  saveCurrentSession();
  // Save full UI state so the new window can restore it exactly
  const transferData = {
    chatHtml: chatArea.innerHTML,
    sessionMessages: sessionMessages,
    activeHsdId: activeHsdId,
    activeHsdTitle: activeHsdTitle,
    activeConversationId: activeConversationId,
    postAnalysisShown: _postAnalysisShown,
    sessions: sessions,             // full tab list
    activeSessionIndex: activeSessionIndex,
    timestamp: Date.now(),
  };
  return chrome.storage.local.set({ _popoutTransfer: transferData });
}

btnPopout.addEventListener("click", () => {
  _saveStateForTransfer().catch((error) => {
    console.error("[popout] failed to save transfer state:", error);
  });
  if (_isPopup) {
    chrome.runtime.sendMessage({
      action: "popout_close",
      hostWindowId: Number.isInteger(_hostWindowId) ? _hostWindowId : undefined,
    });
  } else {
    chrome.runtime.sendMessage({ action: "popout_open" });
  }
});

// Close settings menu on Escape; C = clear active area
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const settingsMenu = document.getElementById("settingsMenu");
    if (settingsMenu) settingsMenu.classList.remove("show");
  }
  if ((e.key === "c" || e.key === "C") && !e.ctrlKey && !e.altKey && !e.metaKey) {
    const tag = document.activeElement?.tagName;
    if (tag !== "INPUT" && tag !== "TEXTAREA") {
      if (typeof isRegressionMode !== "undefined" && isRegressionMode) {
        const ra = document.getElementById("regression-area");
        if (ra) ra.innerHTML = "";
      } else {
        chatArea.innerHTML = "";
      }
    }
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
const btnLogAnalysis = document.getElementById("btn-log-analysis");
const btnLogReset    = document.getElementById("btn-log-reset");
const headerControls = document.getElementById("header-controls");
const logAnalysisBar = document.getElementById("log-analysis-bar");
const logAnalysisExit = document.getElementById("log-analysis-exit");
const logAnalysisStatus = document.getElementById("log-analysis-status");
const logPathInput = document.getElementById("log-path-input");
const manPathInput = document.getElementById("man-path-input");
const btnLogAnalyze = document.getElementById("btn-log-analyze");
const btnBrowseLog = document.getElementById("btn-browse-log");
const btnBrowseMan = document.getElementById("btn-browse-man");

let isRegressionMode = false;
let isLogAnalysisMode = false;
let _preLogSessionIndex = -1;  // session index before entering Log Analysis Mode
const HEADER_COLOR_CHAT = "#5F80AB";
const HEADER_COLOR_REGRESSION = "#b8860b";  // dark goldenrod (土黃色)
const HEADER_COLOR_LOG = "#1d4ed8";          // deep blue (Log Analysis)

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

// ── Log Analysis Mode ────────────────────────────────────────────────────────────────────────

async function switchToLogAnalysisMode() {
  const confirmed = await showModal(
    "Switch to Log Analysis Mode",
    "This will restart the bridge session with the 'displaydebugger' assistant. Current session will be saved. Continue?",
    "Switch",
    "Cancel"
  );
  if (!confirmed) return;

  isLogAnalysisMode = true;

  // Save and remember current session index before entering Log mode
  saveCurrentSession();
  _preLogSessionIndex = activeSessionIndex;

  chatArea.innerHTML = "";
  quickActions.classList.remove("show");
  quickActions.innerHTML = "";
  activeHsdId = null;
  activeHsdTitle = "";
  activeConversationId = "";
  sessionMessages = [];
  _postAnalysisShown = false;
  hidePostAnalysisPanel();
  heroCta.classList.remove("show");
  hideOnboarding();

  // Update header appearance
  document.querySelector(".header").style.background = HEADER_COLOR_LOG;
  headerTitle.textContent = "Log Analysis Mode";
  headerControls.classList.add("log-mode-active");
  document.body.classList.add("log-mode");
  logAnalysisBar.classList.add("show");

  // Show splash and restart bridge with displaydebugger
  showConnectionSplash("Switching to Log Analysis Mode...", "Restarting with displaydebugger assistant");
  setInputEnabled(false);

  if (port) {
    port.postMessage({ action: "restart_session", assistant: "displaydebugger" });
  }
}

async function exitLogAnalysisMode() {
  isLogAnalysisMode = false;

  // Restore header
  document.querySelector(".header").style.background = HEADER_COLOR_CHAT;
  headerControls.classList.remove("log-mode-active");
  document.body.classList.remove("log-mode");
  logAnalysisBar.classList.remove("show");

  // Save log session state, then restore the pre-log session
  saveCurrentSession();

  // Restore previous session if available
  const prevIndex = (_preLogSessionIndex >= 0 && _preLogSessionIndex < sessions.length)
    ? _preLogSessionIndex : -1;
  _preLogSessionIndex = -1;

  if (prevIndex >= 0 && sessions[prevIndex]) {
    activeSessionIndex = prevIndex;
    const prev = sessions[prevIndex];
    activeHsdId = prev.hsdId || null;
    activeHsdTitle = prev.hsdTitle || "";
    activeConversationId = prev.conversationId || "";
    sessionMessages = [...(prev.messages || [])];
    _postAnalysisShown = prev.postAnalysisShown || false;
    updateHeaderTitle();
    updateHeaderSubtitle(activeHsdTitle);
    updateConversationId(activeConversationId);
    rebuildChatArea();
    _restorePostAnalysisPanel(_postAnalysisShown);
    quickActions.classList.remove("show");
    quickActions.innerHTML = "";
    heroCta.classList.remove("show");
    if (sessionMessages.length === 0 && !activeHsdId) showOnboarding();
    else hideOnboarding();
  } else {
    // No previous session — reset to blank
    chatArea.innerHTML = "";
    quickActions.classList.remove("show");
    quickActions.innerHTML = "";
    activeHsdId = null;
    activeHsdTitle = "";
    activeConversationId = "";
    sessionMessages = [];
    _postAnalysisShown = false;
    hidePostAnalysisPanel();
    heroCta.classList.remove("show");
    showOnboarding();
    updateHeaderTitle();
  }

  // Show splash and restart bridge with sighting_assistant + previous CID if available
  showConnectionSplash("Returning to Chat Mode...", "Restarting with sighting_assistant");
  setInputEnabled(false);

  if (port) {
    const restartMsg = { action: "restart_session", assistant: "sighting_assistant" };
    if (activeConversationId) restartMsg.conversation_id = activeConversationId;
    port.postMessage(restartMsg);
  }
}

btnLogAnalysis.addEventListener("click", switchToLogAnalysisMode);
logAnalysisExit.addEventListener("click", exitLogAnalysisMode);

btnLogReset.addEventListener("click", async () => {
  const confirmed = await showModal(
    "Reset Log Analysis",
    "This will clear the log/man file paths and all chat messages. Continue?",
    "Reset",
    "Cancel"
  );
  if (!confirmed) return;

  // Clear path inputs
  logPathInput.value = "";
  manPathInput.value = "";
  btnLogAnalyze.disabled = true;

  // Clear chat area and session state
  chatArea.innerHTML = "";
  sessionMessages = [];
  activeConversationId = "";
  _postAnalysisShown = false;
  hidePostAnalysisPanel();
  quickActions.classList.remove("show");
  quickActions.innerHTML = "";
  heroCta.classList.remove("show");
});

// ── Log Analysis Toolbar ──────────────────────────────────────────────────

// Enable Analyze button only when a log path is provided
logPathInput.addEventListener("input", () => {
  btnLogAnalyze.disabled = !logPathInput.value.trim();
});

// ── Browse button helpers ─────────────────────────────────────────────────

const _dialogTimeouts = {};  // field -> timeout id

function openFileBrowseDialog(field, title) {
  if (!port) { showToast("Bridge not connected", "error"); return; }
  const btn = field === "log" ? btnBrowseLog : btnBrowseMan;

  // If already waiting, cancel the old timeout and reset (allow re-click)
  if (_dialogTimeouts[field]) {
    clearTimeout(_dialogTimeouts[field]);
    delete _dialogTimeouts[field];
  }

  btn.disabled = true;
  btn.textContent = "⏳";
  port.postMessage({ action: "file_dialog", field, title });

  // Safety timeout: if no result in 60s, re-enable the button
  _dialogTimeouts[field] = setTimeout(() => {
    delete _dialogTimeouts[field];
    btn.disabled = false;
    btn.innerHTML = "&#128193;";
    showToast("File dialog timed out — try again", "warn");
  }, 10_000);
}

function onFileDialogResult(field, path) {
  // Cancel the safety timeout
  if (_dialogTimeouts[field]) {
    clearTimeout(_dialogTimeouts[field]);
    delete _dialogTimeouts[field];
  }

  const btn = field === "log" ? btnBrowseLog : btnBrowseMan;
  btn.disabled = false;
  btn.innerHTML = "&#128193;";

  if (!path) return; // user cancelled

  if (field === "log") {
    logPathInput.value = path;
    btnLogAnalyze.disabled = false;
  } else {
    manPathInput.value = path;
  }
}

btnBrowseLog.addEventListener("click", () => openFileBrowseDialog("log", "Select Log File"));
btnBrowseMan.addEventListener("click", () => openFileBrowseDialog("man", "Select Man File"));

// ── Drag-and-drop for log/man path inputs ─────────────────────────────────
function setupDropTarget(inputEl, field) {
  inputEl.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    inputEl.classList.add("drag-over");
  });
  inputEl.addEventListener("dragleave", () => {
    inputEl.classList.remove("drag-over");
  });
  inputEl.addEventListener("drop", (e) => {
    e.preventDefault();
    inputEl.classList.remove("drag-over");
    // Chrome extension: DataTransferItem.getAsFile() gives a File object
    // but its .path is not exposed. We send the filename to bridge via
    // a special action so the bridge can resolve the full path from the
    // file name passed through the webkitRelativePath or use file.name.
    // Better approach: use the file entry to get the full path via
    // chrome.runtime messaging with the file handle.
    const file = e.dataTransfer.files[0];
    if (!file) return;
    // file.path is available in Electron; in Chrome extensions it's not directly
    // accessible. We post to the bridge asking it to resolve the path by name.
    // As a fallback, populate with the filename so the user sees something.
    const fullPath = file.path || file.name;
    if (field === "log") {
      logPathInput.value = fullPath;
      btnLogAnalyze.disabled = !fullPath.trim();
    } else {
      manPathInput.value = fullPath;
    }
  });
}

setupDropTarget(logPathInput, "log");
setupDropTarget(manPathInput, "man");

btnLogAnalyze.addEventListener("click", () => {
  const logPath = logPathInput.value.trim();
  if (!logPath) return;
  const manPath = manPathInput.value.trim();

  let command, display;
  if (manPath) {
    command = `analyze "${logPath}" with man file "${manPath}"`;
    display = `🔍 Analyze log: ${logPath}  |  Man file: ${manPath}`;
  } else {
    command = `analyze "${logPath}"`;
    display = `🔍 Analyze log: ${logPath}`;
  }

  sendUserMessage(command, display);
});

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

// Populate version badge in Settings menu
(function () {
  const el = document.getElementById('app-version-badge');
  if (el) el.textContent = 'v' + chrome.runtime.getManifest().version;
}());

// Regression button wiring
document.getElementById("reg-gfx-btn").addEventListener("click", () => {
  if (typeof checkGfxRegression === "function") checkGfxRegression();
});
document.getElementById("reg-gop-btn").addEventListener("click", () => {
  if (typeof checkGopRegression === "function") checkGopRegression();
});
document.getElementById("reg-clear-btn").addEventListener("click", () => {
  regressionArea.innerHTML = "";
});

// ── Driver History panel wiring ───────────────────────────────────────────────
document.getElementById("reg-history-btn").addEventListener("click", () => {
  if (typeof showDriverHistoryPanel === "function") showDriverHistoryPanel();
});

document.getElementById("dh-close-btn").addEventListener("click", () => {
  document.getElementById("driver-history-panel").style.display = "none";
});

document.querySelectorAll(".dh-tab").forEach(tab => {
  tab.addEventListener("click", async () => {
    document.querySelectorAll(".dh-tab").forEach(t => {
      t.style.borderBottomColor = "transparent";
      t.style.color = "#6b7280";
    });
    tab.style.borderBottomColor = "#3b82f6";
    tab.style.color = "#1d4ed8";
    if (typeof _renderHistoryList === "function")
      await _renderHistoryList(tab.dataset.type);
  });
});

setInputEnabled(false);

// Check for pop-out/pop-in transfer data first
async function _restoreTransferState() {
  try {
    const stored = await chrome.storage.local.get({ _popoutTransfer: null });
    const data = stored._popoutTransfer;
    if (!data || (Date.now() - data.timestamp > 30000)) {
      // No transfer data or stale (>30s) — ignore
      return false;
    }
    // Restore state
    activeHsdId = data.activeHsdId || null;
    activeHsdTitle = data.activeHsdTitle || "";
    activeConversationId = data.activeConversationId || "";
    sessionMessages = data.sessionMessages || [];
    _postAnalysisShown = data.postAnalysisShown || false;
    if (Array.isArray(data.sessions) && data.sessions.length > 0) {
      sessions = data.sessions;
      activeSessionIndex = (typeof data.activeSessionIndex === "number" && data.activeSessionIndex < data.sessions.length)
        ? data.activeSessionIndex : 0;
    }

    // Restore chat HTML directly (preserves rendered markdown, tool indicators, etc.)
    chatArea.innerHTML = data.chatHtml || "";
    updateHeaderTitle();
    updateHeaderSubtitle(activeHsdTitle);
    updateConversationId(activeConversationId);
    renderTabBar();
    hideOnboarding();

    // Re-show post-analysis panel if it was shown
    if (data.postAnalysisShown) {
      _postAnalysisShown = false; // reset so showPostAnalysisPanel() actually runs
      showPostAnalysisPanel();
      postAnalysisPanel.classList.add("collapsed");
      const titleEl = postAnalysisPanel.querySelector(".post-analysis-title");
      if (titleEl) titleEl.textContent = _POST_TITLE_SHORT;
    }

    forceScrollToBottom();

    // Clear transfer data
    await chrome.storage.local.remove("_popoutTransfer");
    return true;
  } catch (e) {
    console.error("[popout] restore error:", e);
    return false;
  }
}

_restoreTransferState().then((restored) => {
  if (restored) {
    // The destination view is restored; attach to the existing session if present.
    hideConnectionSplash();
    if (port) {
      port.postMessage({ action: "view_ready", view: _isPopup ? "popup" : "sidepanel" });
      port.postMessage({
        action: "initialize_view",
        assistant: isLogAnalysisMode ? "displaydebugger" : "sighting_assistant",
        conversation_id: activeConversationId || undefined,
      });
    }
    return;
  }

  // Load saved sessions and restore active session UI
  loadSessions().then(() => {
    activeSessionIndex = 0;
    renderTabBar();
    if (sessions.length > 0 && sessions[activeSessionIndex].messages && sessions[activeSessionIndex].messages.length > 0) {
      const active = sessions[activeSessionIndex];
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
    if (port) {
      port.postMessage({ action: "view_ready", view: _isPopup ? "popup" : "sidepanel" });
      port.postMessage({
        action: "initialize_view",
        assistant: isLogAnalysisMode ? "displaydebugger" : "sighting_assistant",
        conversation_id: activeConversationId || undefined,
      });
    }
  });
});

// ── Connection Timeout with Retry ──────────────────────────────────────────
let _connectionTimeout = null;

function _startConnectionTimeout() {
  _cancelConnectionTimeout();
  _connectionTimeout = setTimeout(() => {
    _connectionTimeout = null;
    // Show retry UI in splash
    if (splashEl && splashEl.style.display !== 'none') {
      splashText.textContent = uiLang === 'zh' ? '⚠️ 連線逾時' : '⚠️ Connection timeout';
      splashSub.innerHTML = `<button id="splash-retry-btn" style="margin-top:8px;padding:6px 18px;background:#5F80AB;color:#fff;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;">${uiLang === 'zh' ? '🔄 重試' : '🔄 Retry'}</button>`;
      splashProgress.classList.add('done');
      document.getElementById('splash-retry-btn')?.addEventListener('click', () => {
        splashSub.textContent = '';
        splashProgress.classList.remove('done');
        splashText.textContent = uiLang === 'zh' ? '重新連線中...' : 'Reconnecting...';
        _startConnectionTimeout();
        if (port) port.postMessage({ action: 'start_session' });
      });
    }
  }, 20000); // 20 seconds
}

function _cancelConnectionTimeout() {
  if (_connectionTimeout) {
    clearTimeout(_connectionTimeout);
    _connectionTimeout = null;
  }
}

// View initialization is handled by _restoreTransferState above.
