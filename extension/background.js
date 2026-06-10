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

function launchViaNativeMessaging() {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage(NM_HOST_NAME, { action: "launch" }, (response) => {
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
 * 2. If not running → try Native Messaging launch (returns actual port)
 * 3. Poll /health until ready
 * Returns true if bridge is ready.
 */
async function ensureBridgeRunning(sendStatus) {
  // Step 1: Try to recover persisted port from a previous launch
  sendStatus("Checking bridge...");
  if (!bridgePort) {
    try {
      const stored = await chrome.storage.session.get("bridgePort");
      if (stored.bridgePort) {
        bridgePort = stored.bridgePort;
      }
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

  // Step 2: Try native messaging launch (native_host returns actual port)
  sendStatus("Starting bridge server...");
  let nmAvailable = true;
  try {
    const result = await launchViaNativeMessaging();
    if (result.status === "error") {
      sendStatus(`Launch error: ${result.message}`);
      return false;
    }
    // native_host always returns {status, port}
    if (result.port) {
      saveBridgePort(result.port);
    }
    // result.status is "launched" or "already_running"
    sendStatus("Bridge process started, waiting for ready...");
  } catch (err) {
    nmAvailable = false;
    sendStatus("Auto-launch not set up. Checking if bridge starts...");
  }

  // Step 3: Poll until bridge is ready
  const maxWait = nmAvailable ? 45 : 8;
  for (let i = 0; i < maxWait; i++) {
    await sleep(1000);
    sendStatus(`Waiting for bridge... (${i + 1}s)`);
    const health = await healthCheck();
    if (health.status === "ok") {
      sendStatus("Bridge connected");
      return true;
    }
  }

  if (!nmAvailable) {
    sendStatus("Bridge not running. Run: cd bridge && python bridge_server.py");
  } else {
    sendStatus("Bridge failed to start. Check console for errors.");
  }
  return false;
}

// ── Service Worker keep-alive ───────────────────────────────────────────────
// Chrome suspends Service Workers after ~30s of inactivity. During long tool
// execution (RAG search, Sherlog), no events flow back, causing suspension.
// This keep-alive prevents that by periodic self-ping while a session is active.

let keepAliveInterval = null;

function startKeepAlive() {
  if (keepAliveInterval) return;
  keepAliveInterval = setInterval(() => {
    // Any async operation keeps the Service Worker alive
    fetch(`${getBridgeUrl() || ''}/health`).catch(() => {});
  }, 20000); // every 20s
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
let activePort = null; // Global reference to current sidepanel/popup port
const SSE_RECONNECT_DELAY = 2000; // ms

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
  const eventTypes = [
    "answer", "tool_start", "tool_request", "usage", "ready", "info", "end", "goodbye", "error"
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
    // Don't immediately give up — try to reconnect
    es.close();
    currentEventSource = null;

    // Check if session is still alive before reconnecting
    if (!sseReconnectTimer) {
      sseReconnectTimer = setTimeout(async () => {
        sseReconnectTimer = null;
        try {
          const health = await healthCheck();
          if (health.status === "ok" && health.session_active) {
            console.log("[bg] SSE reconnecting...");
            startStreaming();
          } else {
            _postToActivePort({ type: "stream_error" });
          }
        } catch {
          _postToActivePort({ type: "stream_error" });
        }
      }, SSE_RECONNECT_DELAY);
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
          port.postMessage({ action: "error", error: `unknown action: ${msg.action}` });
      }
    } catch (err) {
      port.postMessage({ action: "error", error: err.message });
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
