/**
 * background.js — Service Worker
 * Manages bridge connection, auto-launch, and relays events between sidepanel and bridge server.
 */

// NOTE: Native Messaging discovers a bridge instance at runtime. Cache its
// port and identity together so a restarted Service Worker cannot accidentally
// attach to a different process that later occupies the same port.
let bridgePort = null;   // set after first successful NM launch/check
let bridgeInstanceId = null;
let bridgeProtocolVersion = null;
const NM_HOST_NAME = "com.chat_mode_assistant.bridge";

function getBridgeUrl() {
  return bridgePort ? `http://127.0.0.1:${bridgePort}` : null;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ── Bridge API helpers ─────────────────────────────────────────────────────

async function bridgeFetch(path, options = {}, timeoutMs = 10000) {
  // Recover port from session storage if lost (e.g. after Service Worker restart)
  if (!bridgePort) {
    try {
      const stored = await chrome.storage.session.get([
        "bridgePort",
        "bridgeInstanceId",
        "bridgeProtocolVersion",
      ]);
      if (stored.bridgePort) bridgePort = stored.bridgePort;
      bridgeInstanceId = stored.bridgeInstanceId || null;
      bridgeProtocolVersion = stored.bridgeProtocolVersion || null;
    } catch { /* ignore */ }
  }
  const base = getBridgeUrl();
  if (!base) throw new Error("Bridge port not yet known");
  const url = `${base}${path}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
      signal: controller.signal,
    });
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error(`Bridge request timed out after ${timeoutMs}ms: ${path}`);
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
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

async function switchSession(assistant, conversationId) {
  const body = { assistant: assistant || "sighting_assistant" };
  if (conversationId) body.conversation_id = conversationId;
  const resp = await bridgeFetch("/session/switch", {
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
    const resp = await bridgeFetch("/health", {}, 3000);
    const health = await resp.json();
    if (bridgeInstanceId && health.instance_id !== bridgeInstanceId) {
      return {
        status: "stale_instance",
        expected_instance_id: bridgeInstanceId,
        actual_instance_id: health.instance_id || null,
      };
    }
    return health;
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

/** Persist the discovered bridge identity so it survives service worker restarts. */
function saveBridgeIdentity(identity) {
  bridgePort = identity.port;
  bridgeInstanceId = identity.instance_id || null;
  bridgeProtocolVersion = identity.protocol_version || 1;
  chrome.storage.session.set({
    bridgePort,
    bridgeInstanceId,
    bridgeProtocolVersion,
  }).catch(() => {});
}

function clearBridgeIdentity() {
  bridgePort = null;
  bridgeInstanceId = null;
  bridgeProtocolVersion = null;
  chrome.storage.session.remove([
    "bridgePort",
    "bridgeInstanceId",
    "bridgeProtocolVersion",
  ]).catch(() => {});
}

function diagnoseConnection(health) {
  if (!health || health.status === "unreachable") {
    return { layer: "bridge", code: "BRIDGE_UNREACHABLE", detail: "Bridge did not answer its health check." };
  }
  if (health.status === "stale_instance") {
    return { layer: "bridge", code: "STALE_INSTANCE", detail: "Chrome was connected to an outdated bridge instance." };
  }
  if (health.cli?.last_error) {
    return {
      layer: "cli",
      code: health.cli.last_error.code || "CLI_ERROR",
      detail: health.cli.last_error.detail || "The dt chat process reported an error.",
    };
  }
  if (health.cli?.state === "exited") {
    return { layer: "cli", code: "CLI_EXITED", detail: "The dt chat process exited unexpectedly." };
  }
  if (health.cli?.state === "processing") {
    return {
      layer: "cli",
      code: "CLI_PROCESSING",
      detail: "The dt chat process was still running but had not returned to its input prompt.",
    };
  }
  if (health.cli?.state === "stopped") {
    return { layer: "cli", code: "CLI_NOT_STARTED", detail: "Bridge was running without an active dt chat process." };
  }
  if (health.status === "ok") {
    return {
      layer: "interface",
      code: "BRIDGE_AND_CLI_RESPONSIVE",
      detail: "Bridge and CLI were ready; the stale state was likely in the UI or event stream.",
    };
  }
  return { layer: "unknown", code: "UNKNOWN", detail: "The previous connection state could not be classified." };
}

async function waitForBridgeDiscovery(sendStatus, maxSeconds = 45) {
  for (let i = 0; i < maxSeconds; i++) {
    await sleep(1000);
    sendStatus(`Waiting for fresh bridge... (${i + 1}s)`);
    try {
      const check = await sendNativeMessage({ action: "check" });
      if (check.status === "running" && check.port) {
        saveBridgeIdentity(check);
        return true;
      }
    } catch { /* keep waiting until timeout */ }
  }
  return false;
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
      const stored = await chrome.storage.session.get([
        "bridgePort",
        "bridgeInstanceId",
        "bridgeProtocolVersion",
      ]);
      if (stored.bridgePort) bridgePort = stored.bridgePort;
      bridgeInstanceId = stored.bridgeInstanceId || null;
      bridgeProtocolVersion = stored.bridgeProtocolVersion || null;
    } catch { /* session storage unavailable */ }
  }
  if (bridgePort) {
    const health = await healthCheck();
    if (health.status === "ok") {
      sendStatus("Bridge connected");
      return true;
    }
    // Stored port is stale — clear it
    clearBridgeIdentity();
  }

  // Step 2: NM "launch" — native_host responds immediately (no blocking wait)
  sendStatus("Starting bridge server...");
  let nmAvailable = false;
  try {
    // Read debug mode setting and pass to native host
    let debugMode = false;
    try {
      const stored = await chrome.storage.local.get({ debugMode: false });
      debugMode = !!stored.debugMode;
    } catch {}
    const result = await sendNativeMessage({ action: "launch", debug_mode: debugMode });
    if (result.status === "error") {
      sendStatus(`Bridge launch error: ${result.message}`);
      return false;
    }
    if (result.status === "already_running" && result.port) {
      saveBridgeIdentity(result);
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
        saveBridgeIdentity(check);
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
// This is mitigated by the lazy SSE reconnect below (no periodic self-ping).
// ── Lazy SSE reconnect (no idle polling) ──────────────────────────────────
// SSE is reconnected on-demand when the user sends a message, not periodically.

/**
 * Ensure the SSE stream is connected before sending a message.
 * If already open, resolves immediately.
 * If not, calls startStreaming() and waits up to 3s for onopen.
 */
async function ensureSseConnected() {
  if (currentEventSource && currentEventSource.readyState === EventSource.OPEN) return;
  startStreaming();
  // Poll up to 3s (30 × 100ms) for SSE to open
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 100));
    if (currentEventSource && currentEventSource.readyState === EventSource.OPEN) return;
  }
  // Proceed after timeout — sendMessage will fail gracefully if bridge is gone
}

// ── SSE Stream consumer ────────────────────────────────────────────────────

let currentEventSource = null;
let sseReconnectTimer = null;
let sseReconnectAttempts = 0;
const uiPorts = new Set();
let activePort = null; // Most recently ready sidepanel/popup port
let pendingPopoutWindowId = null;
let pendingPopupReady = false;
let pendingPopinWindowId = null;
let popoutHostWindowId = null;

function completePopoutHandoff() {
  if (!pendingPopoutWindowId || !pendingPopupReady) return;
  popoutWindowId = pendingPopoutWindowId;
  pendingPopoutWindowId = null;
  pendingPopupReady = false;
  chrome.sidePanel.setOptions({ enabled: false }, () => {
    chrome.sidePanel.setOptions({ enabled: true });
  });
}
const SSE_RECONNECT_BASE_DELAY = 2000; // ms
const SSE_MAX_RECONNECT_ATTEMPTS = 15; // give up after ~2 min of retries

function _postToActivePort(msg) {
  for (const port of [...uiPorts]) {
    try {
      port.postMessage(msg);
    } catch {
      uiPorts.delete(port);
      if (activePort === port) activePort = null;
    }
  }
}

function startStreaming() {
  if (
    currentEventSource
    && (currentEventSource.readyState === EventSource.CONNECTING
      || currentEventSource.readyState === EventSource.OPEN)
  ) {
    return currentEventSource;
  }
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
    "error", "cid_mismatch", "cid_expired", "config_repaired", "config_repair_failed"
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
let isRecovering = false;

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "sidepanel") return;

  uiPorts.add(port);
  activePort = port;

  port.onMessage.addListener(async (msg) => {
    try {
      switch (msg.action) {
        case "view_ready": {
          activePort = port;
          if (msg.view === "popup") {
            pendingPopupReady = true;
            completePopoutHandoff();
          } else if (msg.view === "sidepanel" && pendingPopinWindowId) {
            const popupId = pendingPopinWindowId;
            pendingPopinWindowId = null;
            popoutWindowId = null;
            chrome.windows.remove(popupId).catch(() => {});
          }
          break;
        }

        case "initialize_view": {
          const bridgeReady = await ensureBridgeRunning((status) => {
            port.postMessage({ type: "startup_status", message: status });
          });
          if (!bridgeReady) {
            port.postMessage({ action: "bridge_unavailable" });
            break;
          }

          const health = await healthCheck();
          if (health.status === "ok" && health.session_active) {
            port.postMessage({ action: "health_result", ...health });
            startStreaming();
            break;
          }

          if (isStarting) {
            port.postMessage({ type: "startup_status", message: "Already starting..." });
            break;
          }
          isStarting = true;
          try {
            port.postMessage({ type: "startup_status", message: "Starting chat session..." });
            const startResult = await startSession(msg.assistant, msg.conversation_id);
            if (startResult.error) {
              port.postMessage({ action: "session_start_error", error: startResult.error });
              break;
            }
            port.postMessage({ action: "session_started", ...startResult });
            startStreaming();
          } finally {
            isStarting = false;
          }
          break;
        }

        case "health": {
          let health = await healthCheck();
          if (health.status === "stale_instance") {
            clearBridgeIdentity();
            port.postMessage({ type: "startup_status", message: "Bridge restarted; reconnecting..." });
            const bridgeReady = await ensureBridgeRunning((status) => {
              port.postMessage({ type: "startup_status", message: status });
            });
            health = bridgeReady ? await healthCheck() : { status: "unreachable" };
          }
          port.postMessage({ action: "health_result", ...health });
          // If session is active but SSE stream is disconnected, re-establish it
          if (health.session_active && !currentEventSource) {
            console.log("[bg] Re-establishing SSE stream after health check");
            startStreaming();
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
          } finally {
            isStarting = false;
          }
          break;
        }

        case "send": {
          // Ensure SSE is connected before sending so we don't miss the response
          await ensureSseConnected();
          const sendResult = await sendMessage(msg.message);
          if (sendResult.error === "session_busy") {
            port.postMessage({ type: "send_rejected", reason: "session_busy", message: sendResult.message || "AI is still processing." });
          }
          break;
        }

        case "stop_session": {
          if (currentEventSource) {
            currentEventSource.close();
            currentEventSource = null;
          }
          const stopResult = await stopSession();
          port.postMessage({ action: "session_stopped", ...stopResult });
          break;
        }

        case "interrupt_session": {
          if (isStarting) {
            port.postMessage({ type: "startup_status", message: "Already restarting..." });
            break;
          }
          isStarting = true;
          try {
            if (currentEventSource) {
              currentEventSource.close();
              currentEventSource = null;
            }
            port.postMessage({ type: "startup_status", message: "Stopping current analysis..." });
            const bridgeReady = await ensureBridgeRunning((status) => {
              port.postMessage({ type: "startup_status", message: status });
            });
            if (!bridgeReady) {
              port.postMessage({ action: "bridge_unavailable" });
              break;
            }
            const restartResult = await switchSession(msg.assistant, msg.conversation_id);
            if (restartResult.error) {
              port.postMessage({ action: "session_start_error", error: restartResult.error });
              break;
            }
            port.postMessage({ action: "session_interrupted" });
            port.postMessage({ action: "session_started", ...restartResult });
            startStreaming();
          } finally {
            isStarting = false;
          }
          break;
        }

        case "restart_bridge": {
          // Kill current bridge and re-launch with updated settings (e.g. debug mode)
          if (currentEventSource) {
            currentEventSource.close();
            currentEventSource = null;
          }
          // Shut down bridge process completely (so it can relaunch with new flags)
          try { await bridgeFetch("/bridge/shutdown", { method: "POST" }); } catch {}
          clearBridgeIdentity();
          // Wait a moment for process to exit, then re-launch
          await sleep(1000);
          const ready = await ensureBridgeRunning((status) => {
            port.postMessage({ type: "startup_status", message: status });
          });
          if (ready) {
            const startMsg = { action: "start_session" };
            port.postMessage({ action: "session_started", status: "restarted" });
            const startResult = await startSession();
            if (!startResult.error) {
              port.postMessage({ action: "session_started", ...startResult });
              startStreaming();
            }
          }
          break;
        }

        case "recover_connection": {
          if (isRecovering) {
            port.postMessage({
              action: "recovery_result",
              ok: false,
              diagnosis: { layer: "interface", code: "RECOVERY_IN_PROGRESS", detail: "A reset is already running." },
            });
            break;
          }
          isRecovering = true;
          const previousHealth = await healthCheck();
          const diagnosis = diagnoseConnection(previousHealth);
          try {
            port.postMessage({ action: "recovery_progress", message: "Resetting Bridge and CLI..." });
            if (currentEventSource) {
              currentEventSource.close();
              currentEventSource = null;
            }
            if (sseReconnectTimer) {
              clearTimeout(sseReconnectTimer);
              sseReconnectTimer = null;
            }

            let debugMode = false;
            try {
              const stored = await chrome.storage.local.get({ debugMode: false });
              debugMode = !!stored.debugMode;
            } catch {}

            const reset = await sendNativeMessage({ action: "reset", debug_mode: debugMode });
            if (reset.status === "error") throw new Error(reset.message || "Native reset failed");
            clearBridgeIdentity();

            const ready = await waitForBridgeDiscovery((message) => {
              port.postMessage({ action: "recovery_progress", message });
            });
            if (!ready) throw new Error("Fresh bridge did not become ready within 45 seconds");

            port.postMessage({ action: "recovery_progress", message: "Starting a fresh CLI session..." });
            const startResult = await startSession(msg.assistant, msg.conversation_id);
            if (startResult.error) throw new Error(startResult.error);
            startStreaming();
            port.postMessage({ action: "session_started", ...startResult });
            port.postMessage({
              action: "recovery_result",
              ok: true,
              diagnosis,
              instance_id: bridgeInstanceId,
              protocol_version: bridgeProtocolVersion,
            });
          } catch (err) {
            port.postMessage({
              action: "recovery_result",
              ok: false,
              diagnosis,
              error: err.message || String(err),
            });
          } finally {
            isRecovering = false;
          }
          break;
        }

        case "restart_session": {
          if (isStarting) {
            port.postMessage({ type: "startup_status", message: "Already starting..." });
            break;
          }
          isStarting = true;
          try {
            if (currentEventSource) {
              currentEventSource.close();
              currentEventSource = null;
            }

            // Ensure bridge is still running
            const bridgeReady = await ensureBridgeRunning((status) => {
              port.postMessage({ type: "startup_status", message: status });
            });
            if (!bridgeReady) {
              port.postMessage({ action: "bridge_unavailable" });
              break;
            }

            // Start new session with the specified assistant
            port.postMessage({ type: "startup_status", message: `Starting ${msg.assistant || "assistant"}...` });
            const restartResult = await switchSession(msg.assistant, msg.conversation_id);
            if (restartResult.error) {
              port.postMessage({ action: "session_start_error", error: restartResult.error });
              break;
            }
            port.postMessage({ action: "session_started", ...restartResult });
            startStreaming();
          } finally {
            isStarting = false;
          }
          break;
        }

        case "file_dialog": {
          // Ask bridge to open a native Windows file-picker; wait up to 5 min
          // Use _postToActivePort instead of the closed-over `port` so the result
          // reaches the sidepanel even if it disconnected and reconnected while
          // the file picker was open (stale `port` would silently drop the message).
          try {
            const title = encodeURIComponent(msg.title || "Open File");
            const resp = await bridgeFetch(`/dialog/file?title=${title}`, {}, 305000);
            const data = await resp.json();
            _postToActivePort({ action: "file_dialog_result", field: msg.field, ...data });
          } catch (err) {
            _postToActivePort({ action: "file_dialog_result", field: msg.field, path: "", selected: false, error: err.message });
          }
          break;
        }

        default:
          port.postMessage({ action: "sw_error", error: `unknown action: ${msg.action}` });
      }
    } catch (err) {
      port.postMessage({ action: "sw_error", error: err.message || String(err) });
    }
  });

  port.onDisconnect.addListener(() => {
    uiPorts.delete(port);
    if (activePort === port) activePort = [...uiPorts].at(-1) || null;
    // Don't close SSE on port disconnect — Service Worker may revive and
    // sidepanel will reconnect. Keep SSE alive to avoid losing events.
  });
});

// ── Side panel setup ───────────────────────────────────────────────────────

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });

// ── Pop-out / Pop-in Window Management ─────────────────────────────────────

let popoutWindowId = null;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === "popout_open") {
    // Keep the sidepanel alive until the popup confirms its runtime port is ready.
    pendingPopupReady = false;
    chrome.windows.getLastFocused({ windowTypes: ["normal"] }, (browserWin) => {
      const hostWindowId = browserWin?.id;
      popoutHostWindowId = hostWindowId || null;
      const popupUrl = new URL(chrome.runtime.getURL("sidepanel.html"));
      popupUrl.searchParams.set("popup", "1");
      if (hostWindowId) popupUrl.searchParams.set("hostWindowId", String(hostWindowId));
      chrome.windows.create({
        url: popupUrl.href,
        type: "popup",
        width: 480,
        height: 780,
      }, (win) => {
        if (win?.id) {
          pendingPopoutWindowId = win.id;
          completePopoutHandoff();
        }
      });
    });
  } else if (msg.action === "popout_close") {
    // Open the sidepanel first; close the popup only after its port is ready.
    const winId = popoutWindowId || (sender.tab ? sender.tab.windowId : null);
    const hostWindowId = Number.isInteger(msg.hostWindowId) ? msg.hostWindowId : popoutHostWindowId;
    if (winId && hostWindowId) {
      pendingPopinWindowId = winId;
      chrome.sidePanel.open({ windowId: hostWindowId }).then(() => {
        popoutHostWindowId = null;
        chrome.windows.update(hostWindowId, { focused: true }).catch(() => {});
      }).catch((error) => {
        console.error("[popin] failed to open side panel:", error);
        if (pendingPopinWindowId === winId) {
          pendingPopinWindowId = null;
        }
      });
    }
  }
});

// Clean up popoutWindowId when the window is closed by user
chrome.windows.onRemoved.addListener((windowId) => {
  if (windowId === popoutWindowId) {
    popoutWindowId = null;
  }
  if (windowId === pendingPopinWindowId) {
    pendingPopinWindowId = null;
  }
  if (windowId === pendingPopoutWindowId) {
    pendingPopoutWindowId = null;
    pendingPopupReady = false;
  }
});
