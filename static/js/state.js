export const state = {
  chats: [],
  activeChatId: null,
  provider: localStorage.getItem('provider') || null,
  modelsNim: [],
  modelsOllama: [],
  modelsCloudflare: [],
  defaultModelNim: null,
  defaultModelOllama: null,
  defaultModelCloudflare: null,
  models: [],
  selectedModel: null,
  defaultModel: null,
  streaming: false,
  abortController: null,
  duoMode: false,
  selectedModel2: null,
  _pickingSlot: 'left',
  pendingFiles: [],
  webSearch: false,
  debugMode: false,
  personas: [],
  defaultPersona: 'default',
  selectedPersona: 'default',
  searchTriggers: [
    'search', 'lookup', 'google', 'bing', 'find', 'news', 'breaking', 'weather', 'trending',
    'look up', 'look for', 'find out', 'right now', 'as of now', 'as of today', 'at the moment',
    'this week', 'this month', 'this year',
    'how much is', 'how much does', 'how much are',
    "what's the price", 'what is the price', 'what time is it', 'what time in',
    'current price', 'current rate', 'current score', 'current standings',
    'stock price', 'live score', 'live results',
    'latest news', 'recent news', 'any news',
    'what are the latest', 'what is the latest', 'what happened', 'what has happened',
    'who won', 'who is winning', "today's", 'this morning', 'this afternoon', 'this evening',
  ],
  autoSearchDetect: localStorage.getItem('autoSearchDetect') !== '0',
  autoScroll: localStorage.getItem('autoScroll') !== '0',
  hasKeyNim: false,
  hasKeyOllama: false,
  hasKeyCloudflare: false,
};

export const PROVIDER_UI_CONFIG = {
  nim: {
    name: 'NVIDIA NIM',
    keyPlaceholder: 'Enter API key...',
    defaultBaseUrl: 'https://integrate.api.nvidia.com/v1',
    showAccountId: false,
    showBaseUrl: true,
    baseUrlHint: 'Change this to use a different OpenAI-compatible provider.'
  },
  ollama: {
    name: 'Ollama Cloud',
    keyPlaceholder: 'Enter API key...',
    defaultBaseUrl: 'https://api.ollama.com/v1',
    showAccountId: false,
    showBaseUrl: true,
    baseUrlHint: 'Update if the Ollama Cloud endpoint is different'
  },
  cloudflare: {
    name: 'Cloudflare Worker AI',
    keyPlaceholder: 'Enter API key...',
    defaultBaseUrl: 'https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1',
    showAccountId: true,
    showBaseUrl: false,
    baseUrlHint: ''
  }
};

export const PROVIDERS = Object.keys(PROVIDER_UI_CONFIG);
const PROVIDER_STATE_KEYS = {
  nim: ['modelsNim', 'defaultModelNim', 'hasKeyNim'],
  ollama: ['modelsOllama', 'defaultModelOllama', 'hasKeyOllama'],
  cloudflare: ['modelsCloudflare', 'defaultModelCloudflare', 'hasKeyCloudflare'],
};

export function getProviderModels(provider) {
  return state[PROVIDER_STATE_KEYS[provider]?.[0]] || [];
}

export function getModelProvider(modelId) {
  return PROVIDERS.find(
    (provider) => getProviderModels(provider).some((model) => model.id === modelId),
  ) || null;
}

export function providerHasKey(provider) {
  return Boolean(state[PROVIDER_STATE_KEYS[provider]?.[2]]);
}

export const $ = (id) => document.getElementById(id);

export const starredList      = $('starredList');
export const recentList       = $('recentList');
export const starredLabel     = $('starredLabel');
export const recentsLabel     = $('recentsLabel');
export const messagesEl       = $('messages');
export const welcomeEl        = $('welcome');
export const inputAreaEl      = $('inputArea');
export const messageInput     = $('messageInput');
export const sendBtn          = $('sendBtn');
export const modelSelectorBtn = $('modelSelectorBtn');
export const modelSelectorLbl = $('modelSelectorLabel');
export const personaSelectorBtn = $('personaSelectorBtn');
export const personaSelectorLbl = $('personaSelectorLabel');
export const dropdownBackdrop = $('dropdownBackdrop');
export const dropdownList     = $('dropdownList');
export const personaDropdownBackdrop = $('personaDropdownBackdrop');
export const personaDropdownList     = $('personaDropdownList');
export const modelSearch      = $('modelSearch');
export const chatTitleDisplay = $('chatTitleDisplay');
export const renameBtn        = $('renameBtn');
export const downloadBtn      = $('downloadBtn');
export const topStarBtn       = $('topStarBtn');
export const sidebar          = $('sidebar');

export const duoToggleBtn        = $('duoToggleBtn');
export const duoModelSelectorBtn = $('duoModelSelectorBtn');
export const duoModelSelectorLbl = $('duoModelSelectorLabel');
export const duoModelSep         = $('duoModelSep');

export const collapsedNewChatBtn  = $('collapsedNewChatBtn');
export const collapsedSearchBtn   = $('collapsedSearchBtn');
export const collapsedStarBtn     = $('collapsedStarBtn');
export const collapsedRecentBtn   = $('collapsedRecentBtn');
export const collapsedStarList    = $('collapsedStarList');
export const collapsedRecentList  = $('collapsedRecentList');
export const lightbox         = $('lightbox');
export const lightboxImg      = $('lightboxImg');

export function escHtml(str = '') {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
export const escAttr = escHtml;

export function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

export function autoResize() {
  const isScrolledToBottom = messageInput.scrollHeight - messageInput.clientHeight <= messageInput.scrollTop + 5;
  const scrollTop = messageInput.scrollTop;
  const scrollY = window.scrollY;

  messageInput.style.height = 'auto';
  const newHeight = Math.min(messageInput.scrollHeight, 220);
  messageInput.style.height = newHeight + 'px';

  if (isScrolledToBottom) {
    messageInput.scrollTop = messageInput.scrollHeight;
  } else {
    messageInput.scrollTop = scrollTop;
  }
  if (window.scrollY !== scrollY) {
    window.scrollTo(window.scrollX, scrollY);
  }
}

export function updateSendBtn() {
  if (state.streaming) {
    sendBtn.disabled = false;
    return;
  }
  const noKeys = !state.hasKeyNim && !state.hasKeyOllama && !state.hasKeyCloudflare;
  sendBtn.disabled = noKeys || (!messageInput.value.trim() && state.pendingFiles.length === 0);
}

export function setStopMode(on) {
  $('sendIcon').style.display = on ? 'none' : '';
  $('stopIcon').style.display = on ? '' : 'none';
  sendBtn.title = on ? 'Stop Generating' : 'Send';
  sendBtn.classList.toggle('stop-mode', on);
  sendBtn.disabled = false;
}

export function setWebSearch(on) {
  state.webSearch = on;
  const btn = $('webSearchToggle');
  if (!btn) return;
  btn.classList.toggle('active', on);
  btn.title = on ? 'Web Search: ON' : 'Web Search: OFF';
}

export function setAutoSearchDetect(on) {
  state.autoSearchDetect = on;
  localStorage.setItem('autoSearchDetect', on ? '1' : '0');
}

export function setAutoScroll(on) {
  state.autoScroll = on;
  localStorage.setItem('autoScroll', on ? '1' : '0');
}

export function setDebugMode(on) {
  state.debugMode = on;
  const btn = $('debugToggleBtn');
  if (btn) {
    btn.classList.toggle('active', on);
    btn.title = on ? 'Debug Mode: ON' : 'Debug Mode: OFF';
  }
  document.querySelectorAll('.search-debug-panel').forEach(el => {
    el.style.display = on ? '' : 'none';
  });
}

export function needsWebSearch(text) {
  if (!state.autoSearchDetect || !state.searchTriggers.length) return false;
  const lower = text.toLowerCase();
  return state.searchTriggers.some(t => lower.includes(t));
}

// Client timestamp for date-aware replies.
export function clientTime() {
  return new Date().toLocaleString('en-US', {
    weekday: 'short', year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
  });
}

export function beginStreaming() {
  state.streaming = true;
  state.abortController = new AbortController();
  setStopMode(true);
}

export function endStreaming() {
  state.streaming = false;
  state.abortController = null;
  setStopMode(false);
}

export function setProvider(p) {
  state.provider = p;
  if (p) {
    localStorage.setItem('provider', p);
  } else {
    localStorage.removeItem('provider');
  }
  
  const keys = PROVIDER_STATE_KEYS[p];
  state.models = keys ? state[keys[0]] : [];
  state.defaultModel = keys ? state[keys[1]] : null;
  
  // If selected model isn't in new provider, fallback to default
  if (!p || !state.models.find(m => m.id === state.selectedModel)) {
    state.selectedModel = state.defaultModel;
  }
  
  // Sync the UI pills
  document.querySelectorAll('.pill-opt').forEach(btn => {
    btn.classList.toggle('active', p && btn.dataset.provider === p);
  });
}
