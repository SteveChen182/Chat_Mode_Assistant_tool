// models.js — 集中管理所有語言模型清單
// 此檔案由 sidepanel.html 與 options.html 共同引入

const EXPERTGPT_MODELS = [
  'claude-haiku-4-5',
  'gpt-4.1-mini',
  'gpt-4.1-nano',
  'gpt-4o',
  'gpt-5.1-chat',
  'gpt-5.2',
  'gpt-5.2-chat',
  'gpt-5.3-chat',
  'gpt-5-chat',
  'gpt-5-mini',
  'gpt-5-nano'
];

const OAUTH2_MODELS = [
  // OpenAI 系列（走 GNAI /providers/openai/v1）
  'gpt-4o',
  'gpt-4.1',
  'gpt-5-mini',
  'gpt-5-nano',
  'gpt-5.1',
  'gpt-5.2',
  'gpt-5.4',
  'gpt-5.4-mini',
  'gpt-5.4-nano',
  'o3',
  'o3-mini',
  'o4-mini'
];
