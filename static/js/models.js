import { state, $, dropdownList, dropdownBackdrop, modelSearch, modelSelectorLbl, duoModelSelectorLbl, escHtml } from './state.js';
import { api } from './api.js';

const PROVIDER_NAMES = {
  'openai': 'OpenAI', 'moonshotai': 'Moonshot AI', 'google': 'Google',
  'microsoft': 'Microsoft', 'mistralai': 'Mistral AI', 'minimaxai': 'MiniMax AI',
  'meta': 'Meta', 'bytedance': 'ByteDance', 'stepfun-ai': 'StepFun AI',
  'deepseek-ai': 'DeepSeek AI', 'qwen': 'Qwen', 'nvidia': 'NVIDIA', 'z-ai': 'Z.ai',
};

export function getProviderName(model) {
  let modelId = '';
  let icon = '';

  if (typeof model === 'string') {
    modelId = model;
    const fullModel = state.modelsNim?.find(m => m.id === model) 
                   || state.modelsOllama?.find(m => m.id === model) 
                   || state.models?.find(m => m.id === model);
    if (fullModel) {
      icon = fullModel.icon || '';
    }
  } else if (model && typeof model === 'object') {
    modelId = model.id || '';
    icon = model.icon || '';
  }

  icon = icon.toLowerCase();
  if (icon.includes('google')) return 'Google';
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

export function badgeHtml(modelId, size) {
  const model = state.modelsNim?.find(m => m.id === modelId) 
             || state.modelsOllama?.find(m => m.id === modelId) 
             || state.models?.find(m => m.id === modelId);
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
  const noKeys = !hasNim && !hasOllama;

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

  // Search across all provider lists so a cross-provider duo model resolves correctly.
  const m = state.models?.find((x) => x.id === state.selectedModel)
         || state.modelsNim?.find((x) => x.id === state.selectedModel)
         || state.modelsOllama?.find((x) => x.id === state.selectedModel);
  modelSelectorLbl.textContent = m ? m.name : state.selectedModel || 'Select model';
  const badgeEl = $('modelSelectorBadge');
  if (badgeEl && m) {
    const icon = m.icon || null;
    Object.assign(badgeEl.style, {
      background: icon ? 'transparent' : '#06b6d4', color: icon ? '#333' : '#fff',
      width: '16px', height: '16px', fontSize: '7px', display: '',
      borderRadius: ''
    });
    badgeEl.innerHTML = badgeInner(icon, badgeLabel(m, m.id), 11);
  }
}

export function updateDuoModelLabel() {
  const m = state.models.find((x) => x.id === state.selectedModel2)
         || state.modelsNim?.find((x) => x.id === state.selectedModel2)
         || state.modelsOllama?.find((x) => x.id === state.selectedModel2);
  const lbl = $('duoModelSelectorLabel');
  if (lbl) lbl.textContent = m ? m.name : state.selectedModel2 || 'Pick model…';
  const badgeEl = $('duoModelSelectorBadge');
  if (badgeEl && m) {
    const icon = m.icon || null;
    Object.assign(badgeEl.style, {
      background: icon ? 'transparent' : '#06b6d4', color: icon ? '#333' : '#fff',
      width: '16px', height: '16px', fontSize: '7px', display: '',
      borderRadius: ''
    });
    badgeEl.innerHTML = badgeInner(icon, badgeLabel(m, m.id), 11);
  }
}

export function renderDropdownList(models) {
  dropdownList.innerHTML = '';
  const groups = {};
  models.forEach(m => {
    const p = getProviderName(m);
    (groups[p] = groups[p] || []).push(m);
  });
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

      // Single color bar (swap comment blocks for gradient).
      const STAT_COLOR = '#0088FF';
      const statColors = Array(10).fill(STAT_COLOR);
      // const statColors = ['#7A6BFF','#3B9EFF','#22C7E6','#1FD6A0','#3BD23B','#A8E635','#FFE030','#FFB52E','#FF7A30','#FF3B30'];
      // const statColors = ['#4DA6FF','#3B9DFF','#2B95FF','#1A8CFF','#0884FF','#007BF7','#0073E6','#006AD4','#0062C4','#0059B3'];

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
    dropdownList.appendChild(section);
  });
}

export function selectModel(id) {
  if (state._pickingSlot === 'right') {
    selectModel2(id);
    return;
  }
  // Sync state.provider to whichever provider owns this model so the picker
  // opens on the correct tab next time. Re-apply id after setProvider since
  // setProvider resets selectedModel to the provider's default.
  const inNim = state.modelsNim?.some(m => m.id === id);
  const inOllama = state.modelsOllama?.some(m => m.id === id);
  if (inNim && state.provider !== 'nim') setProvider('nim');
  else if (inOllama && state.provider !== 'ollama') setProvider('ollama');
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
    'ollama': state.hasKeyOllama
  };

  // When picking for the duo right slot, determine which provider the current
  // selectedModel2 belongs to and pre-select that provider's pill/list.
  let effectiveProvider = state.provider;
  if (state._pickingSlot === 'right' && state.selectedModel2) {
    const inNim = state.modelsNim?.some(m => m.id === state.selectedModel2);
    const inOllama = state.modelsOllama?.some(m => m.id === state.selectedModel2);
    if (inNim) effectiveProvider = 'nim';
    else if (inOllama) effectiveProvider = 'ollama';
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

import { setProvider, updateSendBtn } from './state.js';

export async function loadModels() {
  const [nimData, ollamaData, settingsNim, settingsOllama] = await Promise.all([
    api('/models?provider=nim').catch(() => ({ models: [], default: null })),
    api('/models?provider=ollama').catch(() => ({ models: [], default: null })),
    api('/settings?provider=nim').catch(() => ({ has_key: false })),
    api('/settings?provider=ollama').catch(() => ({ has_key: false }))
  ]);

  state.modelsNim = nimData.models || [];
  state.defaultModelNim = nimData.default || nimData.models[0]?.id;

  state.modelsOllama = ollamaData.models || [];
  state.defaultModelOllama = ollamaData.default || ollamaData.models[0]?.id;

  state.hasKeyNim = settingsNim.has_key;
  state.hasKeyOllama = settingsOllama.has_key;

  const hasNim = state.hasKeyNim;
  const hasOllama = state.hasKeyOllama;

  let initialProvider = state.provider;
  if (!hasNim && !hasOllama) {
    initialProvider = null;
  } else if (hasNim && hasOllama) {
    if (!initialProvider) initialProvider = 'nim';
  } else if (hasNim && !hasOllama) {
    initialProvider = 'nim';
    state.selectedModel = state.defaultModelNim;
  } else if (!hasNim && hasOllama) {
    initialProvider = 'ollama';
    state.selectedModel = state.defaultModelOllama;
  }

  setProvider(initialProvider);
  if (!state.selectedModel) {
    state.selectedModel = state.defaultModel;
  }

  updateModelLabel();
  renderDropdownList(state.models);
  updateSendBtn();
}
