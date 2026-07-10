import { $, state, setAutoSearchDetect, setAutoScroll, setProvider, PROVIDER_UI_CONFIG } from './state.js';
import { api } from './api.js';
import { loadModels } from './models.js';

// Show/hide the "no API key" warning banner.
export async function refreshApiKeyWarning() {
  const banner = $('apiKeyWarning');
  if (!banner) return;
  try {
    const data = await api(`/settings?provider=${state.provider}`);
    if (data.has_key) {
      // Fade out, then hide (only if currently visible).
      if (banner.style.display !== 'none' && !banner.classList.contains('hiding')) {
        banner.classList.add('hiding');
        banner.addEventListener('animationend', () => {
          banner.style.display = 'none';
          banner.classList.remove('hiding');
        }, { once: true });
      }
    } else {
      banner.classList.remove('hiding');
      banner.style.display = 'flex';
    }
  } catch {
    // network/server error — leave banner as-is
  }
}

// Set the settings-modal key status line.
export function setKeyStatus(msg, variant = '') {
  const el = $('keyStatus');
  el.textContent = msg;
  el.className = 'settings-hint' + (variant ? ' ' + variant : '');
}

export async function openSettings() {
  const keyInput = $('apiKeyInput');
  keyInput.value = '';
  delete keyInput.dataset.sentinel;
  delete keyInput.dataset.removeKey;
  $('baseUrlInput').value = '';
  setKeyStatus('Loading…');
  $('settingsBackdrop').style.display = 'flex';

  try {
    if (!state.provider) {
      setProvider('nim');
    }
    
    const config = PROVIDER_UI_CONFIG[state.provider] || PROVIDER_UI_CONFIG.nim;

    const apiKeyLabel = $('apiKeyLabel');
    if (apiKeyLabel) {
      apiKeyLabel.textContent = `Enter ${config.name} API Key`;
    }
    keyInput.placeholder = config.keyPlaceholder;

    const data = await api(`/settings?provider=${state.provider}`);
    $('baseUrlInput').value = data.base_url || '';
    if ($('accountIdInput')) $('accountIdInput').value = data.account_id || '';
    $('accountIdContainer').style.display = config.showAccountId ? '' : 'none';
    $('baseUrlContainer').style.display = config.showBaseUrl ? '' : 'none';
    $('baseUrlHint').textContent = config.baseUrlHint;
    
    keyInput.dataset.hadKey = data.has_key ? '1' : '';
    $('removeKeyBtn').style.display = data.has_key ? '' : 'none';
    if (data.has_key) {
      const hintLen = (data.key_hint || '').length;
      if (state.provider === 'nim') {
        const bulletsCount = Math.max(0, data.key_len - 6 - hintLen);
        keyInput.value = `nvapi-${'•'.repeat(bulletsCount)}${data.key_hint}`;
      } else {
        const bulletsCount = Math.max(0, data.key_len - hintLen);
        keyInput.value = `${'•'.repeat(bulletsCount)}${data.key_hint}`;
      }
      keyInput.dataset.sentinel = '1';
      setKeyStatus('Key verified!', 'ok');
    } else {
      setKeyStatus('No API key set. Enter one below.', 'warn');
    }
    const temp = data.temperature ?? 0.7;
    $('tempSlider').value = temp;
    updateTempSlider(temp);
    $('autoSearchDetectToggle').checked = state.autoSearchDetect;
    $('autoScrollToggle').checked = state.autoScroll;
  } catch {
    setKeyStatus('Could not load current settings.', 'warn');
  }
}

export function updateTempSlider(val) {
  $('tempValueBadge').textContent = parseFloat(val).toFixed(2);
}

export function closeSettings() {
  $('settingsBackdrop').style.display = 'none';
}

export async function saveSettings() {
  const keyInput = $('apiKeyInput');
  const rawKey = keyInput.value.trim();
  const sentinel = !!keyInput.dataset.sentinel;
  const hadKey = !!keyInput.dataset.hadKey;
  const removing = !!keyInput.dataset.removeKey;

  if (!sentinel && !rawKey && !hadKey && !removing) {
    let msg = 'API key cannot be empty.';
    if (state.provider === 'nim') msg = 'Key cannot be empty. Enter a valid NVIDIA NIM key.';
    setKeyStatus(msg, 'warn');
    return;
  }

  let key;
  if (removing) key = '';
  else if (sentinel || (!rawKey && hadKey)) key = null;
  else key = rawKey;

  const baseUrl = $('baseUrlInput').value.trim();
  const accountId = $('accountIdInput') ? $('accountIdInput').value.trim() : '';
  const temperature = parseFloat($('tempSlider').value);

  const body = { provider: state.provider };
  if (key !== null) body.key = key;
  if (baseUrl) body.base_url = baseUrl;
  
  const config = PROVIDER_UI_CONFIG[state.provider] || PROVIDER_UI_CONFIG.nim;
  if (config.showAccountId) body.account_id = accountId;
  if (!isNaN(temperature)) body.temperature = temperature;
  if (Object.keys(body).length <= 1) { 
    setAutoSearchDetect($('autoSearchDetectToggle').checked); 
    setAutoScroll($('autoScrollToggle').checked);
    closeSettings(); 
    return; 
  }

  const saveBtn = $('settingsSaveBtn');
  saveBtn.textContent = 'Saving…';
  saveBtn.disabled = true;

  try {
    await api('/settings', { method: 'PATCH', body });
    setAutoSearchDetect($('autoSearchDetectToggle').checked);
    setAutoScroll($('autoScrollToggle').checked);
    closeSettings();
    
    await loadModels();

    refreshApiKeyWarning();
  } catch (err) {
    setKeyStatus(`Save failed: ${err.message}`, 'warn');
  } finally {
    saveBtn.textContent = 'Save changes';
    saveBtn.disabled = false;
  }
}
