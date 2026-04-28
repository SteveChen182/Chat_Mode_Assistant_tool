// options.js
// Manage provider settings via chrome.storage.local

const DEFAULTS = {
  provider: "openai-compatible",
  azureBearerToken: "",
  openaiBaseUrl: "",
  openaiApiKey: "",
  openaiModel: "gpt-4o"
};

function setStatus(message, isError = false) {
  const status = document.getElementById("saveStatus");
  status.textContent = message;
  status.style.color = isError ? "#b91c1c" : "#065f46";
}

function syncModelControlByProvider(provider) {
  const modelSelect = document.getElementById("openaiModel");
  const models = provider === "oauth2" ? OAUTH2_MODELS : EXPERTGPT_MODELS;
  const currentVal = modelSelect.value;

  modelSelect.innerHTML = '';
  models.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m;
    modelSelect.appendChild(opt);
  });

  modelSelect.value = models.includes(currentVal) ? currentVal : 'gpt-4o';
  modelSelect.disabled = false;
  modelSelect.title = '';
}

function syncQuotaCheckControlByProvider(provider) {
  const checkQuotaBtn = document.getElementById("checkQuotaBtn");
  const quotaStatus = document.getElementById("quotaStatus");
  const quotaResult = document.getElementById("quotaResult");
  const isOAuth2 = provider === "oauth2";

  checkQuotaBtn.disabled = isOAuth2;
  checkQuotaBtn.title = isOAuth2 ? "OAuth2 模式不進行配額檢查" : "";

  if (isOAuth2) {
    quotaStatus.textContent = "OAuth2 模式不檢查配額";
    quotaStatus.style.color = "#6b7280";
    quotaResult.textContent = "已停用：目前 Provider 為 OAuth2。";
  } else if (quotaStatus.textContent === "OAuth2 模式不檢查配額") {
    quotaStatus.textContent = "";
    quotaResult.textContent = "尚未檢查";
  }
}

function normalizeEndpoint(endpoint) {
  return String(endpoint || "").trim().replace(/\/+$/, "");
}

function collectFormData() {
  const provider = document.getElementById("provider").value;
  const modelSelect = document.getElementById("openaiModel");
  const openaiModel = modelSelect.value.trim() || "gpt-4o";

  return {
    provider,
    azureBearerToken: document.getElementById("azureBearerToken").value.trim(),
    openaiBaseUrl: normalizeEndpoint(document.getElementById("openaiBaseUrl").value),
    openaiApiKey: document.getElementById("openaiApiKey").value.trim(),
    openaiModel
  };
}

function applyFormData(config) {
  document.getElementById("provider").value = config.provider || "openai-compatible";
  document.getElementById("azureBearerToken").value = config.azureBearerToken || "";
  document.getElementById("openaiBaseUrl").value = config.openaiBaseUrl || "";
  document.getElementById("openaiApiKey").value = config.openaiApiKey || "";
  document.getElementById("openaiModel").value = config.openaiModel || "gpt-4o";
}

async function loadConfig() {
  const config = await chrome.storage.local.get(DEFAULTS);
  applyFormData(config);
  syncModelControlByProvider(config.provider || "openai-compatible");
  syncQuotaCheckControlByProvider(config.provider || "openai-compatible");
}

function validateConfig(config) {
  if (config.provider === "openai-compatible") {
    if (!config.openaiBaseUrl) {
      return "請填寫 OpenAI-compatible Base URL";
    }
    if (!config.openaiApiKey) {
      return "請填寫 OpenAI-compatible API Key";
    }
    if (!config.openaiModel) {
      return "請填寫 OpenAI-compatible Model";
    }
    return "";
  }

  if (!config.azureBearerToken) {
    return "請填寫 OAuth2 Bearer Token";
  }
  return "";
}

function parseEnvText(text) {
  const result = {};
  const lines = String(text || "").split(/\r?\n/);

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) {
      continue;
    }

    const equalIndex = line.indexOf("=");
    if (equalIndex <= 0) {
      continue;
    }

    const key = line.slice(0, equalIndex).trim();
    let value = line.slice(equalIndex + 1).trim();

    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }

    result[key] = value;
  }

  return result;
}

document.addEventListener("DOMContentLoaded", async () => {
  const form = document.getElementById("azureConfigForm");
  const clearBtn = document.getElementById("clearConfigBtn");
  const importEnvBtn = document.getElementById("importEnvBtn");
  const envInput = document.getElementById("envInput");
  const checkQuotaBtn = document.getElementById("checkQuotaBtn");
  const quotaStatus = document.getElementById("quotaStatus");
  const quotaResult = document.getElementById("quotaResult");
  const providerSelect = document.getElementById("provider");
  const openaiModelSelect = document.getElementById("openaiModel");

  await loadConfig();
  setStatus("已載入目前設定");

  providerSelect.addEventListener("change", async () => {
    syncModelControlByProvider(providerSelect.value);
    syncQuotaCheckControlByProvider(providerSelect.value);
    await chrome.storage.local.set({ provider: providerSelect.value });
    setStatus("已切換 Provider，若其他欄位有修改請按「儲存設定」");
  });

  openaiModelSelect.addEventListener("change", async () => {
    const models = providerSelect.value === "oauth2" ? OAUTH2_MODELS : EXPERTGPT_MODELS;
    const model = models.includes(openaiModelSelect.value) ? openaiModelSelect.value : 'gpt-4o';
    openaiModelSelect.value = model;
    await chrome.storage.local.set({ openaiModel: model });
    setStatus("已更新模型選項");
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const config = collectFormData();
    const validationError = validateConfig(config);
    if (validationError) {
      setStatus(validationError, true);
      return;
    }

    await chrome.storage.local.set(config);
    setStatus("已儲存模型設定");
  });

  clearBtn.addEventListener("click", async () => {
    await chrome.storage.local.set(DEFAULTS);
    applyFormData(DEFAULTS);
    syncModelControlByProvider(DEFAULTS.provider);
    syncQuotaCheckControlByProvider(DEFAULTS.provider);
    setStatus("已清空設定");
  });

  importEnvBtn.addEventListener("click", () => {
    const parsed = parseEnvText(envInput.value);
    const hasOAuth2Input = Boolean(
      parsed.AZURE_OPENAI_BEARER_TOKEN ||
      parsed.GNAI_BEARER_TOKEN
    );
    const hasOpenAIInput = Boolean(
      parsed.OPENAI_BASE_URL ||
      parsed.OPENAI_API_BASE ||
      parsed.OPENAI_API_KEY
    );

    let inferredProvider = providerSelect.value || "openai-compatible";
    if (hasOAuth2Input && !hasOpenAIInput) {
      inferredProvider = "oauth2";
    } else if (!hasOAuth2Input && hasOpenAIInput) {
      inferredProvider = "openai-compatible";
    }

    const mapped = {
      provider: inferredProvider,
      azureBearerToken: (parsed.AZURE_OPENAI_BEARER_TOKEN || parsed.GNAI_BEARER_TOKEN || "").trim(),
      openaiBaseUrl: normalizeEndpoint(parsed.OPENAI_BASE_URL || parsed.OPENAI_API_BASE || ""),
      openaiApiKey: (parsed.OPENAI_API_KEY || "").trim(),
      openaiModel: inferredProvider === "oauth2"
        ? "gpt-4o"
        : (parsed.OPENAI_MODEL || "gpt-4o").trim()
    };

    const hasAnyValue =
      mapped.azureBearerToken ||
      mapped.openaiBaseUrl ||
      mapped.openaiApiKey;

    if (!hasAnyValue) {
      setStatus("找不到可用參數（OAuth2/AZURE_OPENAI_* 或 OPENAI_*）", true);
      return;
    }

    applyFormData(mapped);
    syncModelControlByProvider(mapped.provider);
    syncQuotaCheckControlByProvider(mapped.provider);
    setStatus("已從 .env 解析完成，請按「儲存設定」");
  });

  checkQuotaBtn.addEventListener("click", async () => {
    if (providerSelect.value === "oauth2") {
      syncQuotaCheckControlByProvider("oauth2");
      return;
    }

    quotaStatus.textContent = "檢查中...";
    quotaStatus.style.color = "#374151";
    quotaResult.textContent = "正在向供應商查詢...";

    const response = await new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: "CHECK_QUOTA" }, resolve);
    });

    if (!response || !response.ok) {
      quotaStatus.textContent = "檢查失敗";
      quotaStatus.style.color = "#b91c1c";
      quotaResult.textContent = response?.error || "Unknown error";
      return;
    }

    const result = response.result || {};
    const headers = result.quotaHeaders || {};
    const modelQuotas = result.modelQuotas || {};
    const selectedModel = document.getElementById("openaiModel").value;
    const selectedQuota = modelQuotas[selectedModel] || null;
    const headerLines = Object.keys(headers).length
      ? Object.entries(headers).map(([k, v]) => `${k}: ${v}`).join("\n")
      : "(供應商未回傳可讀取的 quota/rate-limit 標頭)";

    let selectedModelLines = "";
    if (selectedQuota) {
      const used = Number.isFinite(Number(selectedQuota.used)) ? Number(selectedQuota.used) : "N/A";
      const limit = Number.isFinite(Number(selectedQuota.limit)) ? Number(selectedQuota.limit) : "N/A";
      const remaining = Number.isFinite(Number(selectedQuota.remaining)) ? Number(selectedQuota.remaining) : "N/A";
      const quotaType = selectedQuota.quota_type || "N/A";

      selectedModelLines =
        `\n\nSelected Model: ${selectedModel}\n` +
        `Quota Type: ${quotaType}\n` +
        `Used: ${used}/${limit}\n` +
        `Remaining: ${remaining}`;
    } else if (selectedModel) {
      selectedModelLines = `\n\nSelected Model: ${selectedModel}\n(未取得此模型配額資料)`;
    }

    quotaStatus.textContent = "檢查完成";
    quotaStatus.style.color = "#065f46";
    quotaResult.textContent =
      `Provider: ${result.provider || "unknown"}\n` +
      `Endpoint: ${result.endpoint || "unknown"}\n` +
      `HTTP Status: ${result.status || "unknown"}\n\n` +
      `${headerLines}` +
      `${selectedModelLines}`;
  });
});
