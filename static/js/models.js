import { state, $, dropdownList, dropdownBackdrop, modelSearch, modelSelectorLbl, modelSelectorBtn, personaSelectorLbl, personaDropdownList, personaDropdownBackdrop, escHtml, setProvider, updateSendBtn, PROVIDERS, getProviderModels, getModelProvider, providerHasKey } from './state.js';
import { api } from './api.js';

const PROVIDER_NAMES = {
  'openai': 'OpenAI', 'moonshotai': 'Moonshot AI', 'google': 'Google',
  'microsoft': 'Microsoft', 'mistralai': 'Mistral AI', 'minimaxai': 'MiniMax AI',
  'meta': 'Meta', 'bytedance': 'ByteDance', 'stepfun-ai': 'StepFun AI',
  'deepseek-ai': 'DeepSeek AI', 'qwen': 'Qwen', 'nvidia': 'NVIDIA', 'z-ai': 'Z.ai',
};
const ICON_PROVIDER_NAMES = {
  google: 'Google', cloudflare: 'Cloudflare Workers AI', deepseek: 'DeepSeek AI',
  meta: 'Meta', minimax: 'MiniMax AI', mistral: 'Mistral AI', moonshot: 'Moonshot AI',
  nvidia: 'NVIDIA', openai: 'OpenAI', qwen: 'Qwen', stepfun: 'StepFun AI',
  zai: 'Z.ai', essentialai: 'Essential AI', bytedance: 'ByteDance', microsoft: 'Microsoft',
};

// Resolve a model object from any of the provider lists by its id.
export function findModelById(id) {
  if (!id) return null;
  for (const provider of PROVIDERS) {
    const model = getProviderModels(provider).find((item) => item.id === id);
    if (model) return model;
  }
  return null;
}

export function getProviderName(model) {
  let modelId = '';
  let icon = '';

  if (typeof model === 'string') {
    modelId = model;
    icon = findModelById(model)?.icon || '';
  } else if (model && typeof model === 'object') {
    modelId = model.id || '';
    icon = model.icon || '';
  }

  icon = icon.toLowerCase();
  const iconProvider = Object.entries(ICON_PROVIDER_NAMES).find(([key]) => icon.includes(key));
  if (iconProvider) return iconProvider[1];

  const prefix = modelId.split('/')[0].split(':')[0].split('-')[0];
  return PROVIDER_NAMES[prefix] || prefix.replace(/\b\w/g, c => c.toUpperCase());
}

// First word of model name, or 3-letter provider fallback.
function badgeLabel(model, fallbackId) {
  return model?.name?.split(' ')[0]
    || (fallbackId || model?.id || '').split('/')[0].toUpperCase().slice(0, 3);
}

// Icon <img> with text fallback, or the bare label.
function badgeInner(icon, label, imgPx) {
  return icon
    ? `<img src="/icon/${icon}" width="${imgPx}" height="${imgPx}" alt="${label}" style="object-fit:contain;display:block" onerror="this.outerHTML='${label}'">`
    : label;
}

// Apply provider badge styles + icon to a small badge element.
function applyBadge(badgeEl, m) {
  if (!badgeEl || !m) return;
  const icon = m.icon || null;
  Object.assign(badgeEl.style, {
    background: icon ? 'transparent' : '#06b6d4',
    color: icon ? '#333' : '#fff',
    width: '16px', height: '16px', fontSize: '7px',
    display: '', borderRadius: ''
  });
  badgeEl.innerHTML = badgeInner(icon, badgeLabel(m, m.id), 11);
}

export function badgeHtml(modelId, size) {
  const model = findModelById(modelId);
  const icon = model?.icon || null;
  const label = badgeLabel(model, modelId);
  const fs = Math.round(size * 0.38);
  const inner = badgeInner(icon, label, Math.round(size * 0.65));
  const bg = icon ? 'transparent' : '#06b6d4';
  const textColor = icon ? '#333' : '#fff';
  return `<span class="provider-badge" style="background:${bg};color:${textColor};width:${size}px;height:${size}px;font-size:${fs}px">${inner}</span>`;
}

export function updateModelLabel() {
  const hasNim = state.hasKeyNim;
  const hasOllama = state.hasKeyOllama;
  const hasCloudflare = state.hasKeyCloudflare;
  const noKeys = !hasNim && !hasOllama && !hasCloudflare;

  modelSelectorBtn.disabled = noKeys;

  if (noKeys) {
    modelSelectorLbl.textContent = 'No API keys configured';
    const badgeEl = $('modelSelectorBadge');
    if (badgeEl) {
      Object.assign(badgeEl.style, {
        background: 'transparent', color: '#ff0000',
        width: '16px', height: '16px', fontSize: '11px',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        borderRadius: '50%'
      });
      badgeEl.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="#fff" stroke="currentColor" stroke-width="4" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>`;
    }
    return;
  }

  const m = findModelById(state.selectedModel);
  modelSelectorLbl.textContent = m ? m.name : state.selectedModel || 'Select model';
  applyBadge($('modelSelectorBadge'), m);
}

export function updateDuoModelLabel() {
  const m = findModelById(state.selectedModel2);
  const lbl = $('duoModelSelectorLabel');
  if (lbl) lbl.textContent = m ? m.name : state.selectedModel2 || 'Pick model…';
  applyBadge($('duoModelSelectorBadge'), m);
}

export function renderDropdownList(models) {
  const groups = {};
  models.forEach(m => {
    const p = getProviderName(m);
    (groups[p] = groups[p] || []).push(m);
  });
  const frag = document.createDocumentFragment();
  Object.keys(groups).sort().forEach(provider => {
    const section = document.createElement('div');
    const label = document.createElement('div');
    label.className = 'provider-group-label';
    label.textContent = provider;
    section.appendChild(label);
    const grid = document.createElement('div');
    grid.className = 'model-grid';
    groups[provider].forEach(m => {
      const card = document.createElement('div');
      const activeModel = state._pickingSlot === 'right' ? state.selectedModel2 : state.selectedModel;
      card.className = 'model-card' + (m.id === activeModel ? ' selected' : '');

      const statBar = v => Array.from({ length: 10 }, (_, i) =>
        `<span class="model-stat-seg${i < v ? ' filled' : ''}"${i < v ? ' style="background:#0088FF"' : ''}></span>`).join('');
      const statLabel = k => k.charAt(0).toUpperCase() + k.slice(1);
      const statRows = m.stats ? Object.entries(m.stats).map(([k, v]) =>
        `<div class="model-stat-row"><span class="model-stat-label">${statLabel(k)}</span><div class="model-stat-bar">${statBar(v)}</div></div>`
      ).join('') : '';
      const stats = statRows ? `<div class="model-card-stats">${statRows}</div>` : '';
      card.innerHTML = `
        <div class="model-card-top">
          ${badgeHtml(m.id, 28)}
          <span class="model-card-name">${escHtml(m.name)}</span>
        </div>
        ${m.description ? `<div class="model-card-desc">${escHtml(m.description)}</div>` : ''}
        ${stats}
      `;
      card.addEventListener('click', () => selectModel(m.id));
      grid.appendChild(card);
    });
    section.appendChild(grid);
    frag.appendChild(section);
  });
  dropdownList.innerHTML = '';
  dropdownList.appendChild(frag);
}

export function selectModel(id) {
  if (state._pickingSlot === 'right') {
    selectModel2(id);
    return;
  }
  // Sync state.provider to whichever provider owns this model so the picker opens on the correct tab next time. 
  const provider = getModelProvider(id);
  if (provider && provider !== state.provider) setProvider(provider);
  state.selectedModel = id;
  updateModelLabel();
  closeDropdown();
  warmAndPersistModel('model', id);
}

export function selectModel2(id) {
  state.selectedModel2 = id;
  updateDuoModelLabel();
  closeDropdown();
  warmAndPersistModel('model2', id);
}

function warmAndPersistModel(field, id) {
  fetch('/api/warmup', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: id }),
  }).catch(() => { });
  if (state.activeChatId) {
    api(`/chats/${state.activeChatId}`, {
      method: 'PATCH',
      body: { [field]: id },
    }).catch(() => { });
  }
}

export function openDropdown() {
  dropdownBackdrop.style.display = 'flex';
  modelSearch.value = '';
  // Sync provider pill UI state for the picker
  // When picking for the duo right slot, determine which provider the current
  // selectedModel2 belongs to and pre-select that provider's pill/list.
  let effectiveProvider = state.provider;
  if (state._pickingSlot === 'right' && state.selectedModel2) {
    effectiveProvider = getModelProvider(state.selectedModel2) || effectiveProvider;
  }

  document.querySelectorAll('#pickerProviderPill .pill-opt').forEach(btn => {
    btn.classList.toggle('active', effectiveProvider && btn.dataset.provider === effectiveProvider);

    // Gray out/disable the pill toggle if the API key for that provider is blank
    btn.disabled = !providerHasKey(btn.dataset.provider);
  });
  setTimeout(() => modelSearch.focus(), 50);

  // Show the model list for the effective provider (may differ from state.provider for duo right slot).
  renderDropdownList(getProviderModels(effectiveProvider));
}

export function closeDropdown() {
  dropdownBackdrop.style.display = 'none';
  state._pickingSlot = 'left';
}

const emojiMap = {
  'default': '🤖',
  'unhinged': '🤪',
  'furious': '🤬',
  'horny': '🥵',
  'caveman': '🗿',
  'weeboo': '🤩',
  'drunk': '🫩',
  'batman': '💀',
  'shakespeare': '🧐',
  'god': '😇',
  'emo': '😒',
  'sassy': '🙄',
  'british': '😎',
  'french': '🥸',
  'american': '🤠',
  'asian': '😑'
};

export function updatePersonaLabel() {
  const p = state.selectedPersona || state.defaultPersona || 'default';
  if (personaSelectorLbl) {
    personaSelectorLbl.textContent = p.charAt(0).toUpperCase() + p.slice(1);
    const iconSpan = document.getElementById('personaSelectorIcon');
    if (iconSpan) {
      iconSpan.textContent = emojiMap[p.toLowerCase()] || '🎭';
    }
  }
}

export function selectPersona(id) {
  state.selectedPersona = id;
  updatePersonaLabel();
  closePersonaDropdown();
  if (state.activeChatId) {
    api(`/chats/${state.activeChatId}`, { method: 'PATCH', body: { persona: id } }).catch(() => { });
  }
}

export function renderPersonaDropdown() {
  const frag = document.createDocumentFragment();


  state.personas.forEach(p => {
    const isSelected = p.id === state.selectedPersona;
    const card = document.createElement('div');
    card.className = 'model-card' + (isSelected ? ' selected' : '');
    const emoji = emojiMap[p.id.toLowerCase()] || '🎭';
    
    card.innerHTML = `
      <div class="model-card-top">
        <span style="font-size: 16px; margin-right: 2px;">${emoji}</span>
        <span class="model-card-name" style="text-transform: capitalize;">${escHtml(p.id)}${p.id === 'horny' ? ' <span style="font-size: 0.8em; font-weight: normal; text-transform: none;">(might not pass the safety filter)</span>' : ''}</span>
      </div>
      <div class="model-card-desc" style="-webkit-line-clamp: 2; display: -webkit-box; -webkit-box-orient: vertical; overflow: hidden; margin-top: 4px;">
        ${escHtml((p.description || '').split(/(?<=[.!?])\s/)[0])}
      </div>
    `;
    card.addEventListener('click', () => selectPersona(p.id));
    frag.appendChild(card);
  });
  personaDropdownList.innerHTML = '';
  personaDropdownList.appendChild(frag);
}

export function openPersonaDropdown() {
  personaDropdownBackdrop.style.display = 'flex';
  renderPersonaDropdown();
}

export function closePersonaDropdown() {
  personaDropdownBackdrop.style.display = 'none';
}

export async function loadModels() {
  const [nimData, ollamaData, cfData, settingsNim, settingsOllama, settingsCf] = await Promise.all([
    api('/models?provider=nim').catch(() => ({ models: [], default: null })),
    api('/models?provider=ollama').catch(() => ({ models: [], default: null })),
    api('/models?provider=cloudflare').catch(() => ({ models: [], default: null })),
    api('/settings?provider=nim').catch(() => ({ has_key: false })),
    api('/settings?provider=ollama').catch(() => ({ has_key: false })),
    api('/settings?provider=cloudflare').catch(() => ({ has_key: false }))
  ]);

  state.modelsNim = nimData.models || [];
  state.defaultModelNim = nimData.default || nimData.models[0]?.id;

  state.modelsOllama = ollamaData.models || [];
  state.defaultModelOllama = ollamaData.default || ollamaData.models[0]?.id;

  state.modelsCloudflare = cfData.models || [];
  state.defaultModelCloudflare = cfData.default || cfData.models[0]?.id;

  state.hasKeyNim = settingsNim.has_key;
  state.hasKeyOllama = settingsOllama.has_key;
  state.hasKeyCloudflare = settingsCf.has_key;

  const hasNim = state.hasKeyNim;
  const hasOllama = state.hasKeyOllama;
  const hasCloudflare = state.hasKeyCloudflare;

  let initialProvider = state.provider;
  if (!hasNim && !hasOllama && !hasCloudflare) {
    initialProvider = null;
  } else if (!providerHasKey(initialProvider)) {
    initialProvider = PROVIDERS.find(providerHasKey);
  }

  setProvider(initialProvider);
  if (!state.selectedModel) {
    state.selectedModel = state.defaultModel;
  }

  updateModelLabel();
  renderDropdownList(state.models);
  updateSendBtn();
}

export async function loadPersonas() {
  try {
    const data = await api('/personas');
    state.personas = data.personas || [{id: 'default', description: 'Default system prompt.'}];
    state.defaultPersona = data.default || 'default';
    if (!state.selectedPersona) {
      state.selectedPersona = state.defaultPersona;
    }
    updatePersonaLabel();
  } catch (e) {
    console.error('Failed to load personas:', e);
  }
}
