/**
 * background.js — Service Worker
 * Manages bridge connection, auto-launch, and relays events between sidepanel and bridge server.
 */

// NOTE: Port is discovered dynamically from the bridge server at runtime.
// The bridge writes its actual port to bridge.port; native_host reads it and
// returns it in the NM response. We cache it in chrome.storage.session so it
// survives service worker restarts.
let bridgePort = null;   // set after first successful NM launch/check
const NM_HOST_NAME = "com.chat_mode_assistant.bridge";

function getBridgeUrl() {
  return bridgePort ? `http://127.0.0.1:${bridgePort}` : null;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ── Bridge API helpers ─────────────────────────────────────────────────────

async function bridgeFetch(path, options = {}) {
  // Recover port from session storage if lost (e.g. after Service Worker restart)
  if (!bridgePort) {
    try {
      const stored = await chrome.storage.session.get("bridgePort");
      if (stored.bridgePort) bridgePort = stored.bridgePort;
    } catch { /* ignore */ }
  }
  const base = getBridgeUrl();
  if (!base) throw new Error("Bridge port not yet known");
  const url = `${base}${path}`;
  const resp = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  return resp;
}

async function startSession(assistant, conversationId) {
  const body = { assistant: assistant || "sighting_assistant" };
  if (conversationId) body.conversation_id = conversationId;
  const resp = await bridgeFetch("/session/start", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return resp.json();
}

async function sendMessage(message) {
  const resp = await bridgeFetch("/session/send", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
  return resp.json();
}

async function stopSession() {
  const resp = await bridgeFetch("/session/stop", { method: "POST" });
  return resp.json();
}

async function healthCheck() {
  try {
    const resp = await bridgeFetch("/health");
    return await resp.json();
  } catch {
    return { status: "unreachable" };
  }
}

// ── Auto-Launch via Native Messaging ───────────────────────────────────────

function sendNativeMessage(msg) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage(NM_HOST_NAME, msg, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(response || {});
      }
    });
  });
}

/** Persist the discovered port so it survives service worker restarts. */
function saveBridgePort(port) {
  bridgePort = port;
  chrome.storage.session.set({ bridgePort: port }).catch(() => {});
}

/**
 * Ensure the bridge server is running.
 * 1. Try to recover port from session storage + health-check
 * 2. NM "launch" action → responds immediately ("already_running"|"launching"|"error")
 * 3. If "launching": poll NM "check" every second until bridge is ready
 * Returns true if bridge is ready.
 */
async function ensureBridgeRunning(sendStatus) {
  // Step 1: Try to recover persisted port from a previous launch
  sendStatus("Checking bridge...");
  if (!bridgePort) {
    try {
      const stored = await chrome.storage.session.get("bridgePort");
      if (stored.bridgePort) bridgePort = stored.bridgePort;
    } catch { /* session storage unavailable */ }
  }
  if (bridgePort) {
    const health = await healthCheck();
    if (health.status === "ok") {
      sendStatus("Bridge connected");
      return true;
    }
    // Stored port is stale — clear it
    bridgePort = null;
    chrome.storage.session.remove("bridgePort").catch(() => {});
  }

  // Step 2: NM "launch" — native_host responds immediately (no blocking wait)
  sendStatus("Starting bridge server...");
  let nmAvailable = false;
  try {
    const result = await sendNativeMessage({ action: "launch" });
    if (result.status === "error") {
      sendStatus(`Bridge launch error: ${result.message}`);
      return false;
    }
    if (result.status === "already_running" && result.port) {
      saveBridgePort(result.port);
      sendStatus("Bridge connected");
      return true;
    }
    // status === "launching" — bridge process was spawned, now poll for port
    nmAvailable = true;
    sendStatus("Bridge starting...");
  } catch (err) {
    // NM not set up (dev mode) or host crashed — show actual error
    sendStatus(`Native Messaging unavailable: ${err.message}`);
    return false;
  }

  // Step 3: Poll NM "check" every second until bridge is running (max 45s)
  for (let i = 0; i < 45; i++) {
    await sleep(1000);
    sendStatus(`Waiting for bridge... (${i + 1}s)`);
    try {
      const check = await sendNativeMessage({ action: "check" });
      if (check.status === "running" && check.port) {
        saveBridgePort(check.port);
        sendStatus("Bridge connected");
        return true;
      }
    } catch {
      // NM error during poll — keep waiting
    }
  }

  sendStatus("Bridge failed to start within 45s.");
  return false;
}

// ── Service Worker keep-alive ───────────────────────────────────────────────
// Chrome suspends Service Workers after ~30s of inactivity. During long tool
// execution (RAG search, Sherlog), no events flow back, causing suspension.
// This keep-alive prevents that by periodic self-ping while a session is active.
// It also monitors SSE health and reconnects if the stream dropped silently.

let keepAliveInterval = null;

function startKeepAlive() {
  if (keepAliveInterval) return;
  keepAliveInterval = setInterval(async () => {
    try {
      const health = await healthCheck();
      // If session is active but SSE is disconnected, force reconnect
      if (health.status === "ok" && health.session_active && !currentEventSource) {
        console.log("[bg] Keep-alive detected dead SSE — reconnecting");
        startStreaming();
      }
    } catch { /* ignore */ }
  }, 15000); // every 15s
}

function stopKeepAlive() {
  if (keepAliveInterval) {
    clearInterval(keepAliveInterval);
    keepAliveInterval = null;
  }
}

// ── SSE Stream consumer ────────────────────────────────────────────────────

let currentEventSource = null;
let sseReconnectTimer = null;
let sseReconnectAttempts = 0;
let activePort = null; // Global reference to current sidepanel/popup port
const SSE_RECONNECT_BASE_DELAY = 2000; // ms
const SSE_MAX_RECONNECT_ATTEMPTS = 15; // give up after ~2 min of retries

function _postToActivePort(msg) {
  try {
    if (activePort) activePort.postMessage(msg);
  } catch (e) {
    // Port disconnected — ignore, new port will be set on reconnect
    activePort = null;
  }
}

function startStreaming() {
  if (currentEventSource) {
    currentEventSource.close();
  }
  if (sseReconnectTimer) {
    clearTimeout(sseReconnectTimer);
    sseReconnectTimer = null;
  }

  const streamUrl = getBridgeUrl();
  if (!streamUrl) return null;
  const es = new EventSource(`${streamUrl}/session/stream`);
  currentEventSource = es;

  // Reset reconnect counter on successful open
  es.onopen = () => {
    sseReconnectAttempts = 0;
  };

  const eventTypes = [
    "answer", "tool_start", "tool_request", "usage", "ready", "info", "end", "goodbye",
    "error", "cid_mismatch", "config_repaired", "config_repair_failed"
  ];

  for (const type of eventTypes) {
    es.addEventListener(type, (e) => {
      try {
        const data = JSON.parse(e.data);
        _postToActivePort({ type, ...data });
      } catch {
        _postToActivePort({ type, raw: e.data });
      }
    });
  }

  es.onerror = () => {
    // Close broken connection
    es.close();
    currentEventSource = null;

    // Exponential backoff reconnect while session is alive
    if (sseReconnectAttempts >= SSE_MAX_RECONNECT_ATTEMPTS) {
      console.log("[bg] SSE max reconnect attempts reached");
      _postToActivePort({ type: "stream_error" });
      return;
    }

    const delay = Math.min(SSE_RECONNECT_BASE_DELAY * Math.pow(1.5, sseReconnectAttempts), 10000);
    sseReconnectAttempts++;

    if (!sseReconnectTimer) {
      sseReconnectTimer = setTimeout(async () => {
        sseReconnectTimer = null;
        try {
          const health = await healthCheck();
          if (health.status === "ok" && health.session_active) {
            console.log(`[bg] SSE reconnecting (attempt ${sseReconnectAttempts})...`);
            startStreaming();
          } else if (health.status === "ok" && !health.session_active) {
            // Session ended while SSE was disconnected — notify UI
            _postToActivePort({ type: "stream_error" });
          } else {
            // Bridge unreachable — retry
            sseReconnectTimer = setTimeout(() => {
              sseReconnectTimer = null;
              startStreaming();
            }, delay);
          }
        } catch {
          _postToActivePort({ type: "stream_error" });
        }
      }, delay);
    }
  };

  return es;
}

// ── Message handling from sidepanel ────────────────────────────────────────

let isStarting = false;

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "sidepanel") return;

  // Update global active port — SSE events will now route to this port
  activePort = port;

  port.onMessage.addListener(async (msg) => {
    try {
      switch (msg.action) {
        case "health": {
          const health = await healthCheck();
          port.postMessage({ action: "health_result", ...health });
          // If session is active but SSE stream is disconnected, re-establish it
          if (health.session_active && !currentEventSource) {
            console.log("[bg] Re-establishing SSE stream after health check");
            startStreaming();
            startKeepAlive();
          }
          break;
        }

        case "start_session": {
          if (isStarting) {
            port.postMessage({ type: "startup_status", message: "Already starting..." });
            break;
          }
          isStarting = true;

          try {
            // Ensure bridge is running (auto-launch if needed)
            const bridgeReady = await ensureBridgeRunning((status) => {
              port.postMessage({ type: "startup_status", message: status });
            });

            if (!bridgeReady) {
              port.postMessage({ action: "bridge_unavailable" });
              break;
            }

            // Start chat session
            port.postMessage({ type: "startup_status", message: "Starting chat session..." });
            const startResult = await startSession(msg.assistant, msg.conversation_id);
            // Surface errors from /session/start (e.g. dt not found in PATH)
            if (startResult.error) {
              port.postMessage({ action: "session_start_error", error: startResult.error });
              break;
            }
            port.postMessage({ action: "session_started", ...startResult });
            startStreaming();
            startKeepAlive();
          } finally {
            isStarting = false;
          }
          break;
        }

        case "send": {
          const sendResult = await sendMessage(msg.message);
          if (sendResult.error === "session_busy") {
            port.postMessage({ type: "send_rejected", reason: "session_busy", message: sendResult.message || "AI is still processing." });
          }
          // Ensure SSE is connected after successful send
          if (!currentEventSource && bridgePort) {
            startStreaming();
          }
          break;
        }

        case "stop_session":
          stopKeepAlive();
          if (currentEventSource) {
            currentEventSource.close();
            currentEventSource = null;
          }
          const stopResult = await stopSession();
          port.postMessage({ action: "session_stopped", ...stopResult });
          break;

        default:
          port.postMessage({ action: "sw_error", error: `unknown action: ${msg.action}` });
      }
    } catch (err) {
      port.postMessage({ action: "sw_error", error: err.message || String(err) });
    }
  });

  port.onDisconnect.addListener(() => {
    // Clear active port reference if it's the one disconnecting
    if (activePort === port) activePort = null;
    // Don't close SSE on port disconnect — Service Worker may revive and
    // sidepanel will reconnect. Keep SSE alive to avoid losing events.
    // Only stop keep-alive if no EventSource is active.
    if (!currentEventSource) {
      stopKeepAlive();
    }
  });
});

// ── Side panel setup ───────────────────────────────────────────────────────

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

// ── Pop-out / Pop-in Window Management ─────────────────────────────────────

let popoutWindowId = null;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === "popout_open") {
    // Close sidepanel by disabling it, then open popup window
    chrome.sidePanel.setOptions({ enabled: false }, () => {
      chrome.windows.create({
        url: chrome.runtime.getURL("sidepanel.html?popup=1"),
        type: "popup",
        width: 480,
        height: 780,
      }, (win) => {
        popoutWindowId = win.id;
        // Re-enable sidepanel option (won't show until user clicks action icon)
        chrome.sidePanel.setOptions({ enabled: true });
      });
    });
  } else if (msg.action === "popout_close") {
    // Close popup window → re-open sidepanel
    const winId = popoutWindowId || (sender.tab ? sender.tab.windowId : null);
    popoutWindowId = null;
    if (winId) {
      chrome.windows.remove(winId, () => {
        // Give Chrome a moment to focus the browser window, then open sidepanel
        setTimeout(() => {
          chrome.windows.getLastFocused({ windowTypes: ["normal"] }, (browserWin) => {
            if (!browserWin) return;
            // Focus the window first, then get its active tab to open sidepanel
            chrome.windows.update(browserWin.id, { focused: true }, () => {
              chrome.tabs.query({ active: true, windowId: browserWin.id }, (tabs) => {
                if (tabs && tabs[0]) {
                  chrome.sidePanel.open({ tabId: tabs[0].id });
                } else {
                  chrome.sidePanel.open({ windowId: browserWin.id });
                }
              });
            });
          });
        }, 200);
      });
    }
  }
});

// Clean up popoutWindowId when the window is closed by user
chrome.windows.onRemoved.addListener((windowId) => {
  if (windowId === popoutWindowId) {
    popoutWindowId = null;
  }
});
