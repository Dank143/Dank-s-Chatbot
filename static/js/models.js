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

function updateModelDropdownScrollbar() {
  const dropdown = $('modelDropdown');
  const track = $('modelDropdownScrollbar');
  const thumb = track?.firstElementChild;
  if (!dropdown || !track || !thumb) return;

  const scrollRange = dropdownList.scrollHeight - dropdownList.clientHeight;
  const hasOverflow = scrollRange > 1;
  dropdown.classList.toggle('has-overflow', hasOverflow);
  if (!hasOverflow || track.clientHeight === 0) {
    thumb.style.height = '0px';
    thumb.style.top = '0px';
    return;
  }

  const trackHeight = track.clientHeight;
  const thumbHeight = Math.min(trackHeight, Math.max(18, trackHeight * dropdownList.clientHeight / dropdownList.scrollHeight));
  const thumbRange = trackHeight - thumbHeight;
  thumb.style.height = `${thumbHeight}px`;
  thumb.style.top = `${thumbRange * dropdownList.scrollTop / scrollRange}px`;
}

function initModelDropdownScrollbar() {
  const track = $('modelDropdownScrollbar');
  if (!track || track.dataset.bound) return;
  track.dataset.bound = 'true';

  let dragStartY = null;
  let dragStartScroll = 0;
  dropdownList.addEventListener('scroll', updateModelDropdownScrollbar, { passive: true });
  window.addEventListener('resize', updateModelDropdownScrollbar);
  track.addEventListener('pointerdown', event => {
    const thumb = track.firstElementChild;
    if (event.target === thumb) {
      dragStartY = event.clientY;
      dragStartScroll = dropdownList.scrollTop;
      track.setPointerCapture(event.pointerId);
      event.preventDefault();
      return;
    }

    const bounds = track.getBoundingClientRect();
    const position = Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height));
    dropdownList.scrollTop = position * dropdownList.scrollHeight - dropdownList.clientHeight / 2;
  });
  track.addEventListener('pointermove', event => {
    if (dragStartY === null) return;
    const thumb = track.firstElementChild;
    const thumbRange = track.clientHeight - thumb.offsetHeight;
    const scrollRange = dropdownList.scrollHeight - dropdownList.clientHeight;
    if (thumbRange > 0) {
      dropdownList.scrollTop = dragStartScroll + (event.clientY - dragStartY) * scrollRange / thumbRange;
    }
  });
  const stopDragging = () => { dragStartY = null; };
  track.addEventListener('pointerup', stopDragging);
  track.addEventListener('pointercancel', stopDragging);
}

export function renderDropdownList(models) {
  const frag = document.createDocumentFragment();
  models.forEach(m => {
    const item = document.createElement('div');
    const activeModel = state._pickingSlot === 'right' ? state.selectedModel2 : state.selectedModel;
    item.className = 'model-dropup-item' + (m.id === activeModel ? ' selected' : '');

    item.innerHTML = `
      ${badgeHtml(m.id, 18)}
      <span class="model-dropup-item-name">${escHtml(m.name)}</span>
    `;
    item.addEventListener('click', () => selectModel(m.id));
    frag.appendChild(item);
  });
  dropdownList.innerHTML = '';
  dropdownList.appendChild(frag);
  updateModelDropdownScrollbar();
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
  dropdownBackdrop.style.display = 'block';
  const dropdown = document.getElementById('modelDropdown');
  dropdown.style.display = 'flex';
  initModelDropdownScrollbar();
  if (state.duoMode) {
    const anchor = $(state._pickingSlot === 'right' ? 'duoModelSelectorBtn' : 'modelSelectorBtn');
    dropdown.style.left = `${anchor.offsetLeft + anchor.offsetWidth / 2}px`;
  } else {
    dropdown.style.left = '50%';
  }
  
  let effectiveProvider = state.provider;
  if (state._pickingSlot === 'right' && state.selectedModel2) {
    effectiveProvider = getModelProvider(state.selectedModel2) || effectiveProvider;
  }

  updateProviderSelect(effectiveProvider);
  renderDropdownList(getProviderModels(effectiveProvider));
}

export function updateProviderSelect(prov) {
  const labelMap = { nim: 'NVIDIA NIM', ollama: 'Ollama Cloud', cloudflare: 'Cloudflare AI' };
  document.getElementById('providerSelectLabel').textContent = labelMap[prov] || 'Select Provider';
  document.querySelectorAll('.provider-opt').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.provider === prov);
    btn.disabled = !providerHasKey(btn.dataset.provider);
  });
  document.getElementById('providerSelectMenu').style.display = 'none';
}

export function closeDropdown() {
  dropdownBackdrop.style.display = 'none';
  document.getElementById('modelDropdown').style.display = 'none';
  document.getElementById('providerSelectMenu').style.display = 'none';
  state._pickingSlot = 'left';
}

// Attach event listeners for custom provider dropdown
document.getElementById('providerSelectBtn').addEventListener('click', (e) => {
  e.stopPropagation();
  const menu = document.getElementById('providerSelectMenu');
  if (menu.style.display !== 'none') {
    menu.style.display = 'none';
    return;
  }

  menu.classList.remove('opens-down');
  menu.style.display = 'flex';
  const buttonRect = e.currentTarget.getBoundingClientRect();
  const menuHeight = menu.getBoundingClientRect().height;
  if (buttonRect.top < menuHeight + 4) menu.classList.add('opens-down');
});

document.querySelectorAll('.provider-opt').forEach(btn => {
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const newProv = e.target.dataset.provider;
    if (!newProv || e.target.disabled) return;
    
    if (state._pickingSlot === 'right') {
      updateProviderSelect(newProv);
      renderDropdownList(getProviderModels(newProv));
    } else {
      setProvider(newProv);
      updateProviderSelect(newProv);
      renderDropdownList(getProviderModels(newProv));
    }
  });
});


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
  const personas = state.personas || [];
  const selected = personas.find(persona => persona.id === state.selectedPersona) || personas[0];
  const wheelSize = 640;
  const center = wheelSize / 2;
  const outerRadius = 302;
  const innerRadius = 124;
  const middleRadius = (outerRadius + innerRadius) / 2;
  const sliceAngle = 360 / Math.max(personas.length, 1);
  const defaultIndex = Math.max(0, personas.findIndex(persona => persona.id === 'default'));
  const wheelStartAngle = -90 - (defaultIndex + 0.5) * sliceAngle;
  const sectorPaths = new Map();
  const displayName = id => id ? id.charAt(0).toUpperCase() + id.slice(1) : '';
  const pointAt = (radius, angle) => {
    const radians = angle * Math.PI / 180;
    return [center + radius * Math.cos(radians), center + radius * Math.sin(radians)];
  };
  const sectors = personas.map((persona, index) => {
    const startAngle = wheelStartAngle + index * sliceAngle;
    const endAngle = startAngle + sliceAngle;
    const [outerStartX, outerStartY] = pointAt(outerRadius, startAngle);
    const [outerEndX, outerEndY] = pointAt(outerRadius, endAngle);
    const [innerEndX, innerEndY] = pointAt(innerRadius, endAngle);
    const [innerStartX, innerStartY] = pointAt(innerRadius, startAngle);
    const midAngle = startAngle + sliceAngle / 2;
    const labelRadius = middleRadius + 5;
    const [labelX, labelY] = pointAt(labelRadius, midAngle);
    const emoji = emojiMap[persona.id.toLowerCase()] || '🎭';
    const shortDescription = (persona.description || '').split(/(?<=[.!?])\s/)[0];
    const active = persona.id === selected?.id;
    const wedgePath = `M ${outerStartX} ${outerStartY} A ${outerRadius} ${outerRadius} 0 0 1 ${outerEndX} ${outerEndY} L ${innerEndX} ${innerEndY} A ${innerRadius} ${innerRadius} 0 0 0 ${innerStartX} ${innerStartY} Z`;
    sectorPaths.set(persona.id, wedgePath);
    return `
      <g class="persona-wheel-sector${active ? ' selected' : ''}" data-persona="${escHtml(persona.id)}" role="button" tabindex="0" aria-label="${escHtml(displayName(persona.id))}: ${escHtml(shortDescription)}" aria-pressed="${active}">
        <title>${escHtml(displayName(persona.id))}</title>
        <path class="persona-wheel-wedge" d="${wedgePath}" />
        <g class="persona-wheel-label" transform="translate(${labelX} ${labelY})">
          <text class="persona-wheel-emoji" text-anchor="middle" y="-5">${emoji}</text>
          <text class="persona-wheel-name" text-anchor="middle" y="12">${escHtml(displayName(persona.id))}</text>
        </g>
      </g>`;
  }).join('');

  personaDropdownList.innerHTML = `
    <div class="persona-wheel" data-selected-persona="${escHtml(selected?.id || '')}">
      <svg class="persona-wheel-svg" viewBox="0 0 ${wheelSize} ${wheelSize}" aria-label="Choose a persona">
        ${sectors}
        <circle class="persona-wheel-core" cx="${center}" cy="${center}" r="${innerRadius}" />
        <path class="persona-wheel-outline" d="${sectorPaths.get(selected?.id) || ''}" />
      </svg>
      <div class="persona-wheel-center" aria-live="polite">
        <span class="persona-wheel-center-icon">${selected ? (emojiMap[selected.id.toLowerCase()] || '🎭') : ''}</span>
        <strong class="persona-wheel-center-name">${escHtml(displayName(selected?.id || 'Personas'))}</strong>
        <span class="persona-wheel-center-description">${escHtml((selected?.description || '').split(/(?<=[.!?])\s/)[0])}</span>
      </div>
    </div>`;

  const wheel = personaDropdownList.querySelector('.persona-wheel');
  const centerIcon = wheel.querySelector('.persona-wheel-center-icon');
  const centerName = wheel.querySelector('.persona-wheel-center-name');
  const centerDescription = wheel.querySelector('.persona-wheel-center-description');
  const outline = wheel.querySelector('.persona-wheel-outline');
  const previewPersona = (id) => {
    const persona = personas.find(item => item.id === id);
    if (!persona) return;
    centerIcon.textContent = emojiMap[persona.id.toLowerCase()] || '🎭';
    centerName.textContent = displayName(persona.id);
    centerDescription.textContent = (persona.description || '').split(/(?<=[.!?])\s/)[0];
    outline.setAttribute('d', sectorPaths.get(persona.id) || '');
  };
  wheel.querySelectorAll('.persona-wheel-sector').forEach(sector => {
    sector.addEventListener('pointerenter', () => previewPersona(sector.dataset.persona));
    sector.addEventListener('pointerleave', () => previewPersona(selected?.id));
    sector.addEventListener('focus', () => previewPersona(sector.dataset.persona));
    sector.addEventListener('blur', () => previewPersona(selected?.id));
    sector.addEventListener('click', () => selectPersona(sector.dataset.persona));
    sector.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        selectPersona(sector.dataset.persona);
      }
    });
  });
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
