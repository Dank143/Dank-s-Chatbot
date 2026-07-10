import { state, $, dropdownList, dropdownBackdrop, modelSearch, modelSelectorLbl, modelSelectorBtn, escHtml, setProvider, updateSendBtn } from './state.js';
import { api } from './api.js';

const PROVIDER_NAMES = {
  'openai': 'OpenAI', 'moonshotai': 'Moonshot AI', 'google': 'Google',
  'microsoft': 'Microsoft', 'mistralai': 'Mistral AI', 'minimaxai': 'MiniMax AI',
  'meta': 'Meta', 'bytedance': 'ByteDance', 'stepfun-ai': 'StepFun AI',
  'deepseek-ai': 'DeepSeek AI', 'qwen': 'Qwen', 'nvidia': 'NVIDIA', 'z-ai': 'Z.ai',
};

// Resolve a model object from any of the provider lists by its id.
export function findModelById(id) {
  if (!id) return null;
  return state.modelsNim?.find(m => m.id === id)
      || state.modelsOllama?.find(m => m.id === id)
      || state.modelsCloudflare?.find(m => m.id === id)
      || state.models?.find(m => m.id === id)
      || null;
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
  if (icon.includes('google')) return 'Google';
  if (icon.includes('cloudflare')) return 'Cloudflare Workers AI';
  if (icon.includes('deepseek')) return 'DeepSeek AI';
  if (icon.includes('meta')) return 'Meta';
  if (icon.includes('minimax')) return 'MiniMax AI';
  if (icon.includes('mistral')) return 'Mistral AI';
  if (icon.includes('moonshot')) return 'Moonshot AI';
  if (icon.includes('nvidia')) return 'NVIDIA';
  if (icon.includes('openai')) return 'OpenAI';
  if (icon.includes('qwen')) return 'Qwen';
  if (icon.includes('stepfun')) return 'StepFun AI';
  if (icon.includes('zai')) return 'Z.ai';
  if (icon.includes('essentialai')) return 'Essential AI';
  if (icon.includes('bytedance')) return 'ByteDance';
  if (icon.includes('microsoft')) return 'Microsoft';

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

      const STAT_COLOR = '#0088FF';
      const statColors = Array(10).fill(STAT_COLOR);

      const statBar = v => Array.from({ length: 10 }, (_, i) =>
        `<span class="model-stat-seg${i < v ? ' filled' : ''}"${i < v ? ` style="background:${statColors[i]}"` : ''}></span>`).join('');
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
  const inNim = state.modelsNim?.some(m => m.id === id);
  const inOllama = state.modelsOllama?.some(m => m.id === id);
  const inCloudflare = state.modelsCloudflare?.some(m => m.id === id);
  if (inNim && state.provider !== 'nim') setProvider('nim');
  else if (inOllama && state.provider !== 'ollama') setProvider('ollama');
  else if (inCloudflare && state.provider !== 'cloudflare') setProvider('cloudflare');
  state.selectedModel = id;
  updateModelLabel();
  closeDropdown();
  // Warm the newly selected model.
  fetch('/api/warmup', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: id }),
  }).catch(() => { });
  if (state.activeChatId) {
    api(`/chats/${state.activeChatId}`, { method: 'PATCH', body: { model: id } }).catch(() => { });
  }
}

export function selectModel2(id) {
  state.selectedModel2 = id;
  updateDuoModelLabel();
  closeDropdown();
  // Warm the newly selected model.
  fetch('/api/warmup', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: id }),
  }).catch(() => { });
}

export function openDropdown() {
  dropdownBackdrop.style.display = 'flex';
  modelSearch.value = '';
  // Sync provider pill UI state for the picker
  const hasKeyMap = {
    'nim': state.hasKeyNim,
    'ollama': state.hasKeyOllama,
    'cloudflare': state.hasKeyCloudflare
  };

  // When picking for the duo right slot, determine which provider the current
  // selectedModel2 belongs to and pre-select that provider's pill/list.
  let effectiveProvider = state.provider;
  if (state._pickingSlot === 'right' && state.selectedModel2) {
    const inNim = state.modelsNim?.some(m => m.id === state.selectedModel2);
    const inOllama = state.modelsOllama?.some(m => m.id === state.selectedModel2);
    const inCloudflare = state.modelsCloudflare?.some(m => m.id === state.selectedModel2);
    if (inNim) effectiveProvider = 'nim';
    else if (inOllama) effectiveProvider = 'ollama';
    else if (inCloudflare) effectiveProvider = 'cloudflare';
  }

  document.querySelectorAll('#pickerProviderPill .pill-opt').forEach(btn => {
    btn.classList.toggle('active', effectiveProvider && btn.dataset.provider === effectiveProvider);

    // Gray out/disable the pill toggle if the API key for that provider is blank
    const prov = btn.dataset.provider;
    btn.disabled = !hasKeyMap[prov];
  });
  setTimeout(() => modelSearch.focus(), 50);

  // Show the model list for the effective provider (may differ from state.provider for duo right slot).
  const listToShow = effectiveProvider === 'nim' ? (state.modelsNim || [])
                   : effectiveProvider === 'ollama' ? (state.modelsOllama || [])
                   : state.models;
  renderDropdownList(listToShow);
}

export function closeDropdown() {
  dropdownBackdrop.style.display = 'none';
  state._pickingSlot = 'left';
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
  const providerHasKey = (p) => p === 'nim' ? hasNim : p === 'ollama' ? hasOllama : p === 'cloudflare' ? hasCloudflare : false;
  if (!hasNim && !hasOllama && !hasCloudflare) {
    initialProvider = null;
  } else if (!providerHasKey(initialProvider)) {
    if (hasNim) initialProvider = 'nim';
    else if (hasOllama) initialProvider = 'ollama';
    else if (hasCloudflare) initialProvider = 'cloudflare';
  }

  setProvider(initialProvider);
  if (!state.selectedModel) {
    state.selectedModel = state.defaultModel;
  }

  updateModelLabel();
  renderDropdownList(state.models);
  updateSendBtn();
}
