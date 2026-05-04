/**
 * background.js — Service Worker
 * Manages bridge connection, auto-launch, and relays events between sidepanel and bridge server.
 */

const BRIDGE_URL = "http://127.0.0.1:8776";
const NM_HOST_NAME = "com.chat_mode_assistant.bridge";

// ── Helpers ────────────────────────────────────────────────────────────────

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ── Bridge API helpers ─────────────────────────────────────────────────────

async function bridgeFetch(path, options = {}) {
  const url = `${BRIDGE_URL}${path}`;
  const resp = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  return resp;
}

async function startSession(assistant) {
  const resp = await bridgeFetch("/session/start", {
    method: "POST",
    body: JSON.stringify({ assistant: assistant || "sighting_assistant" }),
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

/**
 * Ensure the bridge server is running.
 * 1. Check /health
 * 2. If not running → try Native Messaging launch
 * 3. Poll /health until ready
 * Returns true if bridge is ready.
 */
async function ensureBridgeRunning(sendStatus) {
  // Step 1: Quick health check
  sendStatus("Checking bridge...");
  let health = await healthCheck();
  if (health.status === "ok") {
    sendStatus("Bridge connected");
    return true;
  }

  // Step 2: Try native messaging launch
  sendStatus("Starting bridge server...");
  let nmAvailable = true;
  try {
    const result = await launchViaNativeMessaging();
    if (result.status === "error") {
      sendStatus(`Launch error: ${result.message}`);
      return false;
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
    health = await healthCheck();
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

// ── SSE Stream consumer ────────────────────────────────────────────────────

let currentEventSource = null;
let sseReconnectTimer = null;
const SSE_RECONNECT_DELAY = 2000; // ms

function startStreaming(port) {
  if (currentEventSource) {
    currentEventSource.close();
  }
  if (sseReconnectTimer) {
    clearTimeout(sseReconnectTimer);
    sseReconnectTimer = null;
  }

  const es = new EventSource(`${BRIDGE_URL}/session/stream`);
  currentEventSource = es;

  const eventTypes = [
    "answer", "tool_start", "tool_request", "usage", "ready", "info", "end", "goodbye", "error"
  ];

  for (const type of eventTypes) {
    es.addEventListener(type, (e) => {
      try {
        const data = JSON.parse(e.data);
        port.postMessage({ type, ...data });
      } catch {
        port.postMessage({ type, raw: e.data });
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
            startStreaming(port);
          } else {
            port.postMessage({ type: "stream_error" });
          }
        } catch {
          port.postMessage({ type: "stream_error" });
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

  port.onMessage.addListener(async (msg) => {
    try {
      switch (msg.action) {
        case "health": {
          const health = await healthCheck();
          port.postMessage({ action: "health_result", ...health });
          // If session is active but SSE stream is disconnected, re-establish it
          if (health.session_active && !currentEventSource) {
            console.log("[bg] Re-establishing SSE stream after health check");
            startStreaming(port);
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
            const startResult = await startSession(msg.assistant);
            port.postMessage({ action: "session_started", ...startResult });
            startStreaming(port);
          } finally {
            isStarting = false;
          }
          break;
        }

        case "send":
          await sendMessage(msg.message);
          break;

        case "stop_session":
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
    if (currentEventSource) {
      currentEventSource.close();
      currentEventSource = null;
    }
  });
});

// ── Side panel setup ───────────────────────────────────────────────────────

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
