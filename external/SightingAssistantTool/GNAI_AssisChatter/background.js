// background.js - SightingAssistant_Chatter service worker (bridge mode)

chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.open({ windowId: tab.windowId });
});

const BRIDGE_CONFIG = {
  gnaiBaseUrl: "http://127.0.0.1:8775/v1",
  gnaiApiKey: "",
  gnaiModel: "gpt-4o",
  gnaiAssistant: "sighting_assistant",
  gnaiTemperature: 0.3,
  gnaiMaxTokens: 2000
};

const ENGLISH_SYSTEM_PROMPT = "You are a professional and helpful GNAI assistant. Answer in clear English and prioritize the provided webpage context.";
let activeChatController = null;
let activeStreamController = null;
let activeStreamPort = null;
const BRIDGE_NATIVE_HOST_NAME = "com.gnai.bridge_launcher";
const BRIDGE_START_WAIT_MS = 12000;
const BRIDGE_HEALTH_RETRY = 12;
const BRIDGE_HEALTH_INTERVAL_MS = 500;
const BRIDGE_AUTO_START_SHOW_WINDOW = true;

const bridgeStartupState = {
  phase: "idle",
  ok: null,
  trigger: "",
  checkedAt: "",
  error: "",
  healthUrl: "",
  healthStatus: null,
  startedByNativeHost: false,
  native: null,
  healthChecks: []
};

let bridgeStartupPromise = null;

function safePostToPort(port, payload) {
  try {
    port.postMessage(payload);
    return true;
  } catch (_) {
    return false;
  }
}

async function getConfig() {
  return {
    gnaiBaseUrl: BRIDGE_CONFIG.gnaiBaseUrl,
    gnaiApiKey: BRIDGE_CONFIG.gnaiApiKey,
    gnaiModel: BRIDGE_CONFIG.gnaiModel,
    gnaiAssistant: BRIDGE_CONFIG.gnaiAssistant,
    gnaiTemperature: BRIDGE_CONFIG.gnaiTemperature,
    gnaiMaxTokens: BRIDGE_CONFIG.gnaiMaxTokens
  };
}

function buildHealthCandidates(baseUrl) {
  const normalized = String(baseUrl || "").trim().replace(/\/+$/, "");
  if (!normalized) return [];

  const candidates = [
    `${normalized}/health`,
    `${normalized}/v1/health`,
    `${normalized.replace(/\/v\d+$/i, "")}/health`,
    `${normalized.replace(/\/v\d+$/i, "")}/v1/health`
  ];

  return [...new Set(candidates.filter(Boolean))];
}

function buildEndpointCandidates(baseUrl) {
  const normalized = String(baseUrl || "").trim().replace(/\/+$/, "");
  if (!normalized) return [];

  const hasVersionSuffix = /\/v\d+$/i.test(normalized);
  const v1Base = hasVersionSuffix ? normalized : `${normalized}/v1`;

  const candidates = [
    `${v1Base}/chat/completions`,
    `${normalized}/chat/completions`
  ];

  return [...new Set(candidates)];
}

function buildStreamEndpointCandidates(baseUrl) {
  const normalized = String(baseUrl || "").trim().replace(/\/+$/, "");
  if (!normalized) return [];

  const hasVersionSuffix = /\/v\d+$/i.test(normalized);
  const v1Base = hasVersionSuffix ? normalized : `${normalized}/v1`;

  const candidates = [
    `${v1Base}/chat/completions/stream`,
    `${normalized}/chat/completions/stream`
  ];

  return [...new Set(candidates)];
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function updateBridgeStartupState(patch = {}) {
  Object.assign(bridgeStartupState, patch, {
    checkedAt: new Date().toISOString()
  });
}

async function probeBridgeHealth(config, options = {}) {
  const attempts = Math.max(1, Number(options.attempts) || 1);
  const intervalMs = Math.max(50, Number(options.intervalMs) || 500);
  const candidates = buildHealthCandidates(config.gnaiBaseUrl);
  const checks = [];

  for (let i = 0; i < attempts; i += 1) {
    for (const url of candidates) {
      try {
        const response = await fetch(url, { method: "GET" });
        const body = await response.text().catch(() => "");
        const item = {
          url,
          ok: response.ok,
          status: response.status,
          bodySnippet: String(body || "").slice(0, 200)
        };
        checks.push(item);
        if (response.ok) {
          return {
            ok: true,
            url,
            status: response.status,
            checks
          };
        }
      } catch (err) {
        checks.push({
          url,
          ok: false,
          error: err.message || String(err)
        });
      }
    }

    if (i < attempts - 1) {
      await sleep(intervalMs);
    }
  }

  return {
    ok: false,
    checks,
    error: checks.find((x) => x?.error)?.error || "Bridge health check failed"
  };
}

async function requestNativeBridgeStart(config) {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendNativeMessage(
        BRIDGE_NATIVE_HOST_NAME,
        {
          action: "start_bridge",
          bridgeBaseUrl: config.gnaiBaseUrl,
          waitMs: BRIDGE_START_WAIT_MS,
          showWindow: BRIDGE_AUTO_START_SHOW_WINDOW
        },
        (response) => {
          if (chrome.runtime.lastError) {
            resolve({
              ok: false,
              error: chrome.runtime.lastError.message,
              noNativeHost: true
            });
            return;
          }

          if (!response || typeof response !== "object") {
            resolve({ ok: false, error: "Native host returned empty response" });
            return;
          }

          resolve(response);
        }
      );
    } catch (err) {
      resolve({ ok: false, error: err.message || String(err) });
    }
  });
}

async function ensureBridgeReady(trigger = "unknown") {
  if (bridgeStartupPromise) {
    return bridgeStartupPromise;
  }

  bridgeStartupPromise = (async () => {
    const config = await getConfig();
    if (!config.gnaiBaseUrl) {
      updateBridgeStartupState({
        phase: "failed",
        ok: false,
        trigger,
        error: "GNAI bridge base URL is empty",
        startedByNativeHost: false
      });
      return { ...bridgeStartupState };
    }

    updateBridgeStartupState({
      phase: "checking",
      ok: null,
      trigger,
      error: "",
      healthUrl: "",
      healthStatus: null,
      startedByNativeHost: false,
      native: null,
      healthChecks: []
    });

    const initialHealth = await probeBridgeHealth(config, { attempts: 1, intervalMs: 100 });
    if (initialHealth.ok) {
      updateBridgeStartupState({
        phase: "ready",
        ok: true,
        healthUrl: initialHealth.url,
        healthStatus: initialHealth.status,
        healthChecks: initialHealth.checks
      });
      return { ...bridgeStartupState };
    }

    updateBridgeStartupState({
      phase: "starting",
      ok: null,
      healthChecks: initialHealth.checks
    });

    const nativeResult = await requestNativeBridgeStart(config);

    updateBridgeStartupState({
      phase: "waiting_health",
      native: nativeResult,
      startedByNativeHost: Boolean(nativeResult?.started)
    });

    const health = await probeBridgeHealth(config, {
      attempts: BRIDGE_HEALTH_RETRY,
      intervalMs: BRIDGE_HEALTH_INTERVAL_MS
    });

    if (health.ok) {
      updateBridgeStartupState({
        phase: "ready",
        ok: true,
        error: "",
        healthUrl: health.url,
        healthStatus: health.status,
        healthChecks: health.checks
      });
      return { ...bridgeStartupState };
    }

    const startupError = nativeResult?.error || health.error || "Bridge startup failed";
    updateBridgeStartupState({
      phase: "failed",
      ok: false,
      error: startupError,
      healthChecks: health.checks
    });
    return { ...bridgeStartupState };
  })();

  try {
    return await bridgeStartupPromise;
  } finally {
    bridgeStartupPromise = null;
  }
}

async function callGnaiDetailed(messages, language, config, options = {}) {
  if (!config.gnaiBaseUrl) {
    throw new Error("GNAI bridge base URL 設定缺失，請檢查 background.js。");
  }

  const endpoints = buildEndpointCandidates(config.gnaiBaseUrl);
  if (endpoints.length === 0) {
    throw new Error("無效的 GNAI Base URL");
  }

  const payload = {
    model: config.gnaiModel,
    messages: [{ role: "system", content: ENGLISH_SYSTEM_PROMPT }, ...messages],
    temperature: Number.isFinite(config.gnaiTemperature) ? config.gnaiTemperature : 0.3,
    max_tokens: Number.isFinite(config.gnaiMaxTokens) ? config.gnaiMaxTokens : 2000,
    assistant: config.gnaiAssistant
  };

  if (options.conversationId) {
    payload.conversation_id = String(options.conversationId);
  }

  if (options.gnaiMode) {
    payload.gnai_mode = options.gnaiMode;
  }

  let lastError = "";
  let lastDetails = null;
  const attempts = [];

  for (const url of endpoints) {
    try {
      const headers = {
        "Content-Type": "application/json",
        "x-gnai-assistant": config.gnaiAssistant
      };

      if (config.gnaiApiKey) {
        headers.Authorization = `Bearer ${config.gnaiApiKey}`;
      }

      const response = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        signal: options.signal
      });

      attempts.push({ endpoint: url, status: response.status, ok: response.ok });

      if (!response.ok) {
        const text = await response.text().catch(() => "");
        let parsed = null;
        try {
          parsed = text ? JSON.parse(text) : null;
        } catch (_) {
          parsed = null;
        }

        if (parsed && typeof parsed === "object") {
          lastDetails = {
            endpoint: url,
            status: response.status,
            error: parsed.error,
            assistant: parsed.assistant,
            dtSource: parsed.dt_source,
            durationMs: parsed.duration_ms,
            returnCode: parsed.return_code,
            stdout: parsed.stdout,
            stderr: parsed.stderr,
            hint: parsed.hint
          };
          lastError = `API error ${response.status} at ${url}: ${parsed.error || "Unknown bridge error"}`;
        } else {
          lastDetails = {
            endpoint: url,
            status: response.status,
            rawBody: text
          };
          lastError = `API error ${response.status} at ${url}: ${text}`;
        }
        continue;
      }

      const data = await response.json();
      const content = data?.choices?.[0]?.message?.content || data?.choices?.[0]?.delta?.content;
      if (!content) {
        throw new Error("GNAI 回傳內容為空");
      }

      return {
        content,
        endpoint: url,
        status: response.status,
        attempts
      };
    } catch (err) {
      if (err?.name === "AbortError") {
        const abortError = new Error("使用者已取消請求");
        abortError.isCancelled = true;
        abortError.attempts = attempts;
        abortError.details = {
          endpoint: url,
          cancelled: true
        };
        throw abortError;
      }
      lastError = `${url}: ${err.message || String(err)}`;
      attempts.push({ endpoint: url, error: err.message || String(err), ok: false });
    }
  }

  const error = new Error(lastError || "呼叫 GNAI 失敗");
  error.attempts = attempts;
  error.details = lastDetails;
  throw error;
}

async function callGnai(messages, language, config) {
  const detailed = await callGnaiDetailed(messages, language, config);
  return detailed.content;
}

async function callGnaiStream(messages, language, config, options = {}) {
  if (!config.gnaiBaseUrl) {
    throw new Error("GNAI bridge base URL 設定缺失，請檢查 background.js。");
  }

  const endpoints = buildStreamEndpointCandidates(config.gnaiBaseUrl);
  if (endpoints.length === 0) {
    throw new Error("無效的 GNAI Base URL");
  }

  const payload = {
    model: config.gnaiModel,
    messages: [{ role: "system", content: ENGLISH_SYSTEM_PROMPT }, ...messages],
    temperature: Number.isFinite(config.gnaiTemperature) ? config.gnaiTemperature : 0.3,
    max_tokens: Number.isFinite(config.gnaiMaxTokens) ? config.gnaiMaxTokens : 2000,
    assistant: config.gnaiAssistant
  };

  if (options.conversationId) {
    payload.conversation_id = String(options.conversationId);
  }

  if (options.gnaiMode) {
    payload.gnai_mode = options.gnaiMode;
  }

  const attempts = [];
  let lastError = "";
  let lastDetails = null;

  for (const url of endpoints) {
    try {
      const headers = {
        "Content-Type": "application/json",
        "x-gnai-assistant": config.gnaiAssistant
      };

      if (config.gnaiApiKey) {
        headers.Authorization = `Bearer ${config.gnaiApiKey}`;
      }

      const response = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        signal: options.signal
      });

      attempts.push({ endpoint: url, status: response.status, ok: response.ok });

      if (!response.ok) {
        const text = await response.text().catch(() => "");
        lastError = `API error ${response.status} at ${url}: ${text || "Unknown bridge error"}`;
        lastDetails = {
          endpoint: url,
          status: response.status,
          rawBody: text
        };
        continue;
      }

      const body = response.body;
      if (!body) {
        throw new Error("Bridge stream body is empty");
      }

      const reader = body.getReader();
      const decoder = new TextDecoder("utf-8");
      let pending = "";
      let finalContent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        pending += decoder.decode(value, { stream: true });
        const lines = pending.split(/\r?\n/);
        pending = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;

          let event = null;
          try {
            event = JSON.parse(trimmed);
          } catch (_) {
            continue;
          }

          if (event?.type === "chunk" && typeof event.delta === "string") {
            options.onChunk?.(event.delta);
          } else if (event?.type === "heartbeat") {
            options.onHeartbeat?.(event);
          } else if (event?.type === "done") {
            finalContent = String(event.content || finalContent || "");
            return {
              content: finalContent,
              endpoint: url,
              status: response.status,
              attempts
            };
          } else if (event?.type === "error") {
            const error = new Error(event.error || "Bridge stream failed");
            error.attempts = attempts;
            error.details = event;
            throw error;
          }
        }
      }

      if (pending.trim()) {
        try {
          const event = JSON.parse(pending.trim());
          if (event?.type === "done") {
            finalContent = String(event.content || "");
          }
        } catch (_) {
          // ignore trailing incomplete json line
        }
      }

      if (!finalContent) {
        throw new Error("GNAI 串流回傳內容為空");
      }

      return {
        content: finalContent,
        endpoint: url,
        status: response.status,
        attempts
      };
    } catch (err) {
      if (err?.name === "AbortError") {
        const abortError = new Error("使用者已取消請求");
        abortError.isCancelled = true;
        abortError.attempts = attempts;
        abortError.details = {
          endpoint: url,
          cancelled: true
        };
        throw abortError;
      }

      if (err?.details) {
        lastDetails = err.details;
      }

      lastError = `${url}: ${err.message || String(err)}`;
      attempts.push({ endpoint: url, error: err.message || String(err), ok: false });
    }
  }

  const error = new Error(lastError || "呼叫 GNAI 串流失敗");
  error.attempts = attempts;
  error.details = lastDetails;
  throw error;
}

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "chat-stream") return;

  const disconnect = () => {
    if (activeStreamPort === port && activeStreamController) {
      activeStreamController.abort();
    }
    if (activeStreamPort === port) {
      activeStreamPort = null;
      activeStreamController = null;
    }
  };

  port.onDisconnect.addListener(disconnect);

  port.onMessage.addListener((message) => {
    if (message?.type === "CANCEL_CHAT_STREAM") {
      if (activeStreamPort === port && activeStreamController) {
        activeStreamController.abort();
      }
      return;
    }

    if (message?.type !== "CHAT_STREAM") return;

    (async () => {
      try {
        if (activeStreamController) {
          safePostToPort(port, {
            type: "error",
            error: "上一個請求仍在進行中，請稍候或先中止。",
            busy: true
          });
          return;
        }

        activeStreamPort = port;
        activeStreamController = new AbortController();
        const config = await getConfig();

        if (!safePostToPort(port, { type: "start" })) {
          return;
        }
        const detailed = await callGnaiStream(message.messages || [], "en", config, {
          signal: activeStreamController.signal,
          conversationId: message.conversationId,
          gnaiMode: message.gnaiMode || "ask",
          onChunk: (delta) => {
            const ok = safePostToPort(port, { type: "chunk", delta });
            if (!ok && activeStreamController) {
              activeStreamController.abort();
            }
          },
          onHeartbeat: () => {
            const ok = safePostToPort(port, { type: "heartbeat" });
            if (!ok && activeStreamController) {
              activeStreamController.abort();
            }
          }
        });

        safePostToPort(port, {
          type: "done",
          result: detailed.content,
          debug: {
            endpoint: detailed.endpoint,
            status: detailed.status,
            attempts: detailed.attempts
          }
        });
      } catch (err) {
        safePostToPort(port, {
          type: "error",
          error: err.message || String(err),
          attempts: err.attempts || [],
          details: err.details || null,
          cancelled: Boolean(err.isCancelled)
        });
      } finally {
        if (activeStreamPort === port) {
          activeStreamPort = null;
          activeStreamController = null;
        }
      }
    })();
  });
});

async function debugBridgeConnection(config) {
  const healthChecks = [];
  const healthCandidates = buildHealthCandidates(config.gnaiBaseUrl);

  for (const url of healthCandidates) {
    try {
      const response = await fetch(url, { method: "GET" });
      const text = await response.text().catch(() => "");
      healthChecks.push({
        url,
        ok: response.ok,
        status: response.status,
        bodySnippet: text.slice(0, 300)
      });
    } catch (err) {
      healthChecks.push({
        url,
        ok: false,
        error: err.message || String(err)
      });
    }
  }

  const pingMessages = [{ role: "user", content: "ping" }];
  const pingResult = await callGnaiDetailed(pingMessages, "en", config);

  return {
    bridgeBaseUrl: config.gnaiBaseUrl,
    assistant: config.gnaiAssistant,
    model: config.gnaiModel,
    healthChecks,
    ping: {
      ok: true,
      endpoint: pingResult.endpoint,
      status: pingResult.status,
      contentSnippet: String(pingResult.content || "").slice(0, 300),
      attempts: pingResult.attempts
    }
  };
}

async function getPageContent(tabId) {
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      let text = document.body ? document.body.innerText || "" : "";
      const title = document.title || "";
      const url = window.location.href || "";

      const MAX_LEN = 15000;
      if (text.length > MAX_LEN) {
        text = text.slice(0, MAX_LEN) + "\n\n[... content truncated ...]";
      }

      return { text, title, url, originalLength: text.length };
    }
  });

  return result;
}

chrome.runtime.onInstalled.addListener(() => {
  ensureBridgeReady("onInstalled").catch((err) => {
    console.warn("[bridge] auto-start failed during install", err);
  });
});

chrome.runtime.onStartup.addListener(() => {
  ensureBridgeReady("onStartup").catch((err) => {
    console.warn("[bridge] auto-start failed during startup", err);
  });
});

ensureBridgeReady("serviceWorkerBoot").catch((err) => {
  console.warn("[bridge] auto-start failed during worker boot", err);
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "ENSURE_BRIDGE_READY") {
    (async () => {
      try {
        const status = await ensureBridgeReady("sidePanelRequest");
        sendResponse({ ok: true, status });
      } catch (err) {
        sendResponse({ ok: false, error: err.message || String(err) });
      }
    })();
    return true;
  }

  if (message.type === "GET_BRIDGE_STARTUP_STATUS") {
    sendResponse({ ok: true, status: { ...bridgeStartupState } });
    return true;
  }

  if (message.type === "GET_PAGE_CONTENT") {
    (async () => {
      try {
        const content = await getPageContent(message.tabId);
        if (!content?.text?.trim()) {
          sendResponse({ ok: false, error: "無法取得頁面內容或內容為空" });
          return;
        }
        sendResponse({ ok: true, content });
      } catch (err) {
        sendResponse({ ok: false, error: err.message || String(err) });
      }
    })();
    return true;
  }

  if (message.type === "CHAT") {
    (async () => {
      try {
        if (activeChatController) {
          sendResponse({ ok: false, error: "上一個請求仍在進行中，請稍候或先中止。", busy: true });
          return;
        }

        activeChatController = new AbortController();
        const config = await getConfig();
        const detailed = await callGnaiDetailed(message.messages || [], "en", config, {
          signal: activeChatController.signal,
          conversationId: message.conversationId,
          gnaiMode: message.gnaiMode || "ask"
        });
        sendResponse({
          ok: true,
          result: detailed.content,
          debug: {
            endpoint: detailed.endpoint,
            status: detailed.status,
            attempts: detailed.attempts
          }
        });
      } catch (err) {
        sendResponse({
          ok: false,
          error: err.message || String(err),
          attempts: err.attempts || [],
          details: err.details || null,
          cancelled: Boolean(err.isCancelled)
        });
      } finally {
        activeChatController = null;
      }
    })();
    return true;
  }

  if (message.type === "CANCEL_CHAT") {
    if (activeChatController) {
      activeChatController.abort();
      sendResponse({ ok: true, cancelled: true });
      return true;
    }

    sendResponse({ ok: false, cancelled: false, error: "目前沒有進行中的請求" });
    return true;
  }

  if (message.type === "CHECK_CONNECTION") {
    (async () => {
      try {
        const config = await getConfig();
        if (!config.gnaiBaseUrl) {
          sendResponse({ ok: false, error: "請先設定 Base URL" });
          return;
        }

        const details = await debugBridgeConnection(config);
        sendResponse({ ok: true, details });
      } catch (err) {
        sendResponse({ ok: false, error: err.message || String(err), attempts: err.attempts || [] });
      }
    })();
    return true;
  }
});
