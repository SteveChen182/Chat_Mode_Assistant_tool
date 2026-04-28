// background.js (service worker, MV3)
// Chatter - Supports Azure OpenAI and OpenAI-compatible endpoints

const DEBUG = false; // 設為 true 可開啟除錯輸出
const dbg = (...args) => { if (DEBUG) console.log(...args); };

const GNAI_OPENAI_BASE_URL = "https://gnai.intel.com/api/providers/openai/v1";

// Open side panel when extension icon is clicked
chrome.action.onClicked.addListener((tab) => {
  chrome.sidePanel.open({ windowId: tab.windowId });
});

async function getModelConfig() {
  const stored = await chrome.storage.local.get({
    provider: "openai-compatible",
    azureBearerToken: "",
    openaiBaseUrl: "",
    openaiApiKey: "",
    openaiModel: "gpt-4o"
  });

  const provider = String(stored.provider || "openai-compatible").trim();

  return {
    provider,
    azureBearerToken: String(stored.azureBearerToken || "").trim(),
    openaiBaseUrl: String(stored.openaiBaseUrl || "").trim().replace(/\/+$/, ""),
    openaiApiKey: String(stored.openaiApiKey || "").trim(),
    openaiModel: String(stored.openaiModel || "gpt-4o").trim()
  };
}

function resolveProvider(config) {
  const requested = String(config?.provider || "openai-compatible").trim();
  return requested === "openai-compatible" ? "openai-compatible" : "oauth2";
}

// System prompts for different languages
const SYSTEM_PROMPTS = {
  'zh-TW': "你是一位友善且樂於助人的 AI 助理。使用者將提供網頁內容，並可能針對該內容提出問題。你必須全程以繁體中文回覆（包含標題、條列、程式碼註解外的自然語言說明），除非使用者明確要求改用其他語言。請提供準確、清晰且有幫助的回覆。如果問題與網頁內容相關，請基於提供的內容回答；如果問題超出網頁內容範圍，也請盡力協助。",
  'zh-CN': "你是一位友善且乐于助人的 AI 助理。用户将提供网页内容，并可能针对该内容提出问题。请使用简体中文回答问题，提供准确、清晰且有帮助的回复。如果问题与网页内容相关，请基于提供的内容回答；如果问题超出网页内容范围，也请尽力协助。",
  'en': "You are a friendly and helpful AI assistant. The user will provide webpage content and may ask questions about it. You must respond in English for the entire reply (including headings and bullet points), unless the user explicitly asks for another language. Provide accurate, clear, and helpful responses. If the question is related to the webpage content, base your answer on the provided content; if it's beyond the scope, still try your best to assist."
};

async function callOAuth2GNAI(messages, language = 'zh-TW', config) {
  if (!config.azureBearerToken) {
    throw new Error("OAuth2 設定不完整，請填入 Bearer Token。");
  }

  const selectedModel = config.openaiModel || "gpt-4o";
  const url = `${GNAI_OPENAI_BASE_URL}/chat/completions`;

  // Get system prompt based on language
  const systemPrompt = SYSTEM_PROMPTS[language] || SYSTEM_PROMPTS['zh-TW'];

  // Prepend system message
  const fullMessages = [
    { role: "system", content: systemPrompt },
    ...messages
  ];

  const isReasoningModel = /^o\d/i.test(selectedModel) || /^gpt-5/i.test(selectedModel);
  const body = {
    model: selectedModel,
    messages: fullMessages,
    ...(isReasoningModel
      ? { max_completion_tokens: 2000 }
      : { temperature: 0.7, max_tokens: 2000, top_p: 0.9, frequency_penalty: 0, presence_penalty: 0 })
  };

  const headers = {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${config.azureBearerToken}`
  };

  const response = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error("OAuth2 API error: " + response.status + " " + text);
  }

  const data = await response.json();

  const choice = data.choices && data.choices[0];
  const message = choice && (choice.message?.content || choice.delta?.content);
  return message || "(No content returned from OAuth2 provider)";
}

async function callOpenAICompatible(messages, language = 'zh-TW', config) {
  if (!config.openaiBaseUrl || !config.openaiApiKey || !config.openaiModel) {
    throw new Error("OpenAI-compatible 設定不完整，請先到 Options 填入 Base URL、API Key、Model。");
  }

  const [url] = getOpenAICompatibleEndpointCandidates(config.openaiBaseUrl, "/chat/completions");
  const systemPrompt = SYSTEM_PROMPTS[language] || SYSTEM_PROMPTS['zh-TW'];

  const selectedModelCompat = config.openaiModel;
  const isReasoningModelCompat = /^o\d/i.test(selectedModelCompat) || /^gpt-5/i.test(selectedModelCompat);
  const body = {
    model: selectedModelCompat,
    messages: [
      { role: "system", content: systemPrompt },
      ...messages
    ],
    ...(isReasoningModelCompat
      ? { max_completion_tokens: 2000 }
      : { temperature: 0.7, max_tokens: 2000, top_p: 0.9, frequency_penalty: 0, presence_penalty: 0 })
  };

  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${config.openaiApiKey}`
    },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error("OpenAI-compatible API error: " + response.status + " " + text);
  }

  const data = await response.json();
  const choice = data.choices && data.choices[0];
  const message = choice && (choice.message?.content || choice.delta?.content);
  return message || "(No content returned from OpenAI-compatible API)";
}

function getOpenAICompatibleEndpointCandidates(baseUrl, resourcePath) {
  const normalizedBase = String(baseUrl || "").trim().replace(/\/+$/, "");
  const normalizedPath = resourcePath.startsWith("/") ? resourcePath : `/${resourcePath}`;
  const hasVersionSuffix = /\/v\d+$/i.test(normalizedBase);

  const primary = hasVersionSuffix
    ? `${normalizedBase}${normalizedPath}`
    : `${normalizedBase}/v1${normalizedPath}`;
  const secondary = hasVersionSuffix
    ? `${normalizedBase.replace(/\/v\d+$/i, "")}/v1${normalizedPath}`
    : `${normalizedBase}${normalizedPath}`;

  return primary === secondary ? [primary] : [primary, secondary];
}

function collectQuotaHeaders(headers) {
  const interesting = [
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-reset-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-tokens",
    "ratelimit-limit",
    "ratelimit-remaining",
    "ratelimit-reset",
    "retry-after"
  ];

  const result = {};
  for (const key of interesting) {
    const value = headers.get(key);
    if (value !== null && value !== "") {
      result[key] = value;
    }
  }
  return result;
}

async function checkQuota(config) {
  const effectiveProvider = resolveProvider(config);

  if (effectiveProvider === "openai-compatible") {
    if (!config.openaiBaseUrl || !config.openaiApiKey) {
      throw new Error("OpenAI-compatible 設定不完整，請先填入 Base URL 與 API Key。");
    }

    const candidateUrls = getOpenAICompatibleEndpointCandidates(config.openaiBaseUrl, "/quota");
    let lastError = null;

    for (const url of candidateUrls) {
      const response = await fetch(url, {
        method: "GET",
        headers: {
          "Authorization": `Bearer ${config.openaiApiKey}`
        }
      });

      const quotaHeaders = collectQuotaHeaders(response.headers);
      if (response.ok) {
        const body = await response.json().catch(() => ({}));
        return {
          provider: "openai-compatible",
          endpoint: url,
          status: response.status,
          quotaHeaders,
          modelQuotas: body.model_quotas || {},
          rawBody: body
        };
      }

      const text = await response.text().catch(() => "");
      lastError = `Quota check failed (${response.status}): ${text || "Unknown error"} [endpoint: ${url}]`;

      // 404 often means path mismatch; try next candidate automatically.
      if (response.status !== 404) {
        break;
      }
    }

    throw new Error(lastError || "Quota check failed: Unknown error");
  }

  throw new Error("OAuth2 模式不支援配額檢查");
}

const HSDES_ISSUE_URL_PATTERNS = [
  {
    name: "article-one-direct-id",
    regex: /^https:\/\/hsdes\.intel\.com\/appstore\/article-one\/#\/(\d+)\/?$/i
  },
  {
    name: "article-one-article-id",
    regex: /^https:\/\/hsdes\.intel\.com\/appstore\/article-one\/#\/article\/(\d+)\/?$/i
  }
];

function extractHsdesIssueId(url) {
  const normalizedUrl = String(url || "").trim();

  for (const pattern of HSDES_ISSUE_URL_PATTERNS) {
    const match = normalizedUrl.match(pattern.regex);
    if (match && match[1]) {
      return match[1];
    }
  }

  return null;
}

async function getPageContent(tabId) {
  dbg('[Background] getPageContent called');

  // Execute script to get full page content
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      let text = document.body ? document.body.innerText || "" : "";
      let title = document.title || "";
      let url = window.location.href || "";
      
      // Limit length to avoid over-long prompts
      const MAX_LEN = 15000;
      const originalLength = text.length;
      if (text.length > MAX_LEN) {
        text = text.slice(0, MAX_LEN) + "\n\n[... content truncated ...]";
      }
      
      return {
        text: text,
        title: title,
        url: url,
        originalLength: originalLength
      };
    }
  });

  const issueId = extractHsdesIssueId(result?.url);
  if (issueId) {
    result.issueId = issueId;
    dbg(`Issue ID:${issueId}`);
  }

  dbg('[Background] getPageContent result:', result?.title, result?.url);
  return result;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "GET_PAGE_CONTENT") {
    (async () => {
      try {
        const tabId = message.tabId;
        dbg('[Background] GET_PAGE_CONTENT - tabId:', tabId);

        const contentResult = await getPageContent(tabId);

        if (!contentResult || !contentResult.text || contentResult.text.trim().length === 0) {
          const errorMsg = "無法取得頁面內容或文字為空。";
          console.error('[Background] No content:', errorMsg);
          sendResponse({ ok: false, error: errorMsg });
          return;
        }

        sendResponse({ ok: true, content: contentResult });
      } catch (err) {
        console.error("GET_PAGE_CONTENT error:", err);
        sendResponse({ ok: false, error: err.message || String(err) });
      }
    })();

    return true; // Indicate async response
  }

  if (message.type === "CHAT") {
    (async () => {
      try {
        const messages = message.messages;
        const language = message.language || "zh-TW";

        dbg('[Background] CHAT - messages count:', messages.length, 'language:', language);

        const config = await getModelConfig();
        const effectiveProvider = resolveProvider(config);
        dbg('[Background] CHAT provider:', effectiveProvider);
        let result = "";

        if (effectiveProvider === "openai-compatible") {
          result = await callOpenAICompatible(messages, language, config);
        } else {
          result = await callOAuth2GNAI(messages, language, config);
        }

        sendResponse({ ok: true, result, provider: effectiveProvider });
      } catch (err) {
        console.error("CHAT error:", err);
        sendResponse({ ok: false, error: err.message || String(err) });
      }
    })();

    return true; // Indicate async response
  }

  if (message.type === "CHECK_QUOTA") {
    (async () => {
      try {
        const config = await getModelConfig();
        const result = await checkQuota(config);
        sendResponse({ ok: true, result });
      } catch (err) {
        console.error("CHECK_QUOTA error:", err);
        sendResponse({ ok: false, error: err.message || String(err) });
      }
    })();

    return true;
  }
});
