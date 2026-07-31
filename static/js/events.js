import {
  state, $,
  messagesEl, inputAreaEl, messageInput, renameBtn, downloadBtn, topStarBtn, chatTitleDisplay,
  dropdownBackdrop, personaDropdownBackdrop, personaSelectorBtn, modelSearch, lightbox, lightboxImg,
  autoResize, updateSendBtn, setWebSearch, setProvider, scrollToBottom,
  collapsedNewChatBtn, collapsedStarBtn, collapsedRecentBtn,
  duoToggleBtn, duoModelSelectorBtn, PROVIDER_UI_CONFIG, getProviderModels
} from './state.js';
import { api } from './api.js';
import { openDropdown, closeDropdown, renderDropdownList, updateModelLabel, openPersonaDropdown, closePersonaDropdown } from './models.js';
import {
  readFileAsDataUrl, readFileAsText, isImageFile, isTextFile,
  renderPendingFiles, openDocViewer, closeDocViewer, _docStore,
} from './files.js';
import { openSettings, closeSettings, saveSettings, updateTempSlider, setKeyStatus, refreshApiKeyWarning } from './settings.js';
import { toggleTheme } from './theme.js';
import {
  sendMessage, showWelcome, loadChats, startInlineRename, toggleSidebar, toggleDuo, confirmDialog, downloadChat, closeContextMenu
} from './chat.js';

const MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024;
const MAX_PENDING_FILES = 10;

function stopStreaming() {
  if (state.abortController) state.abortController.abort();
}

function openLightbox(src) {
  lightboxImg.src = src;
  lightbox.style.display = 'flex';
}

function closeLightbox() {
  lightbox.style.display = 'none';
  lightboxImg.src = '';
}

async function addPendingFiles(files) {
  for (const file of files) {
    if (state.pendingFiles.length >= MAX_PENDING_FILES) break;
    if (file.size > MAX_ATTACHMENT_BYTES) {
      alert(`"${file.name}" exceeds the 25 MB limit.`);
      continue;
    }

    if (isImageFile(file)) {
      const dataUrl = await readFileAsDataUrl(file);
      state.pendingFiles.push({ kind: 'image', name: file.name || 'pasted-image', dataUrl });
      continue;
    }

    let text;
    if (isTextFile(file)) {
      text = await readFileAsText(file);
    } else {
      const form = new FormData();
      form.append('file', file);
      try {
        const res = await fetch('/api/extract-text', { method: 'POST', body: form });
        if (!res.ok) {
          const error = await res.json();
          alert(`Could not read "${file.name}": ${error.detail}`);
          continue;
        }
        ({ text } = await res.json());
      } catch {
        alert(`Could not read "${file.name}"`);
        continue;
      }
    }
    state.pendingFiles.push({ kind: 'document', name: file.name, text });
  }
  renderPendingFiles();
}

export function setupEventListeners() {
  const ro = new ResizeObserver(() => {
    if (inputAreaEl.style.display !== 'none') {
      const pad = (inputAreaEl.offsetHeight + 16) + 'px';
      const wasAtBottom = (messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight) < 20;
      messagesEl.style.setProperty('--messages-pad-bottom', pad);
      if (wasAtBottom) scrollToBottom();
    } else {
      messagesEl.style.setProperty('--messages-pad-bottom', '28px');
    }
  });
  ro.observe(inputAreaEl);

  $('newChatBtn').addEventListener('click', showWelcome);

  $('webSearchToggle').addEventListener('click', () => {
    setWebSearch(!state.webSearch);
    if (state.activeChatId) {
      localStorage.setItem(`webSearch_${state.activeChatId}`, state.webSearch ? '1' : '0');
    }
  });
  $('sidebarToggle').addEventListener('click', toggleSidebar);
  $('collapsedSidebarToggle').addEventListener('click', toggleSidebar);
  $('sidebarToggleMobile').addEventListener('click', toggleSidebar);

  collapsedNewChatBtn.addEventListener('click', showWelcome);

  const closePopups = () => {
    document.querySelectorAll('.sidebar-popup-wrap.active').forEach(w => w.classList.remove('active'));
  };

  [collapsedStarBtn, collapsedRecentBtn].forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const wrap = btn.closest('.sidebar-popup-wrap');
      const isActive = wrap.classList.contains('active');
      closePopups();
      if (!isActive) wrap.classList.add('active');
    });
  });

  document.addEventListener('click', (e) => {
    if (!e.target.closest('.sidebar-popup-wrap')) {
      closePopups();
    }
    if (!e.target.closest('.chat-context-menu') && !e.target.closest('.dots-btn')) {
      closeContextMenu();
    }
  });
  $('themeToggleBtn').addEventListener('click', toggleTheme);

  downloadBtn.addEventListener('click', () => downloadChat(state.activeChatId));

  $('settingsBtn').addEventListener('click', openSettings);
  $('apiKeyWarningLink').addEventListener('click', openSettings);
  refreshApiKeyWarning();

  // Wire pill toggle buttons
  document.querySelectorAll('.provider-pill').forEach(pill => {
    pill.addEventListener('click', e => {
      const btn = e.target.closest('.pill-opt');
      if (!btn || btn.disabled) return;
      const newProv = btn.dataset.provider;

      // If we clicked inside the Model Picker while selecting for the duo RIGHT slot,
      // don't change the global provider — just swap the displayed list so that the
      // left-slot model and state.provider remain unaffected.
      if (pill.id === 'pickerProviderPill' && state._pickingSlot === 'right') {
        pill.querySelectorAll('.pill-opt').forEach(b => b.classList.toggle('active', b === btn));
        renderDropdownList(getProviderModels(newProv));
        return;
      }

      if (newProv === state.provider) return;
      setProvider(newProv);

      // If we clicked inside Settings, reload settings for the new provider.
      if (pill.id === 'settingsProviderPill') {
        openSettings();
      }
      // If we clicked inside the Model Picker (left slot), re-render and update label.
      if (pill.id === 'pickerProviderPill') {
        renderDropdownList(state.models);
        updateModelLabel();
      }
    });
  });

  renameBtn.addEventListener('click', () => {
    if (state.activeChatId) {
      const chat = state.chats.find((c) => c.id === state.activeChatId);
      startInlineRename(chatTitleDisplay, state.activeChatId, chat?.title || '');
    }
  });

  topStarBtn.addEventListener('click', async () => {
    if (!state.activeChatId) return;
    const chat = state.chats.find(c => c.id === state.activeChatId);
    if (!chat) return;
    await api(`/chats/${chat.id}`, { method: 'PATCH', body: { starred: !chat.starred } });
    await loadChats();
    // Update SVG fill locally
    const isStarred = !chat.starred;
    topStarBtn.querySelector('svg').setAttribute('fill', isStarred ? 'currentColor' : 'none');
    topStarBtn.classList.toggle('starred', isStarred);
  });



  $('sendBtn').addEventListener('click', () => state.streaming ? stopStreaming() : sendMessage());

  $('attachBtn').addEventListener('click', () => $('fileInput').click());

  $('fileInput').addEventListener('change', async () => {
    await addPendingFiles($('fileInput').files);
    $('fileInput').value = '';
  });

  $('attachmentPreviews').addEventListener('click', (e) => {
    const image = e.target.closest('.attachment-thumb img');
    if (image) openLightbox(image.src);
  });

  messagesEl.addEventListener('click', (e) => {
    if (e.target.classList.contains('msg-image')) { openLightbox(e.target.src); return; }
    const chip = e.target.closest('.msg-doc-chip[data-doc-key]');
    if (chip) {
      const entry = _docStore.get(+chip.dataset.docKey);
      if (entry) openDocViewer(entry.name, entry.text);
    }
  });

  lightbox.addEventListener('click', closeLightbox);
  $('docViewerBackdrop').addEventListener('click', (e) => { if (e.target === $('docViewerBackdrop')) closeDocViewer(); });
  $('docViewerClose').addEventListener('click', closeDocViewer);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeLightbox(); closeDocViewer(); } });

  messageInput.addEventListener('input', () => { autoResize(); updateSendBtn(); });
  messageInput.addEventListener('paste', async (e) => {
    const images = Array.from(e.clipboardData?.items || [])
      .filter(item => item.kind === 'file' && item.type.startsWith('image/'))
      .map(item => item.getAsFile())
      .filter(Boolean);
    if (!images.length) return;

    e.preventDefault();
    await addPendingFiles(images);
  });
  messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });

  $('modelSelectorBtn').addEventListener('click', (e) => {
    e.stopPropagation();
    state._pickingSlot = 'left';
    dropdownBackdrop.style.display === 'none' ? openDropdown() : closeDropdown();
  });

  // Duo toggle button
  if (duoToggleBtn) {
    duoToggleBtn.addEventListener('click', () => toggleDuo());
  }

  // Second model selector for duo mode
  if (duoModelSelectorBtn) {
    duoModelSelectorBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      state._pickingSlot = 'right';
      dropdownBackdrop.style.display === 'none' ? openDropdown() : closeDropdown();
    });
  }

  personaSelectorBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    personaDropdownBackdrop.style.display === 'none' ? openPersonaDropdown() : closePersonaDropdown();
  });

  personaDropdownBackdrop.addEventListener('click', (e) => {
    if (e.target === personaDropdownBackdrop) closePersonaDropdown();
  });
  $('personaModalCloseBtn').addEventListener('click', closePersonaDropdown);

  dropdownBackdrop.addEventListener('click', (e) => {
    if (e.target === dropdownBackdrop) closeDropdown();
  });

  $('modelModalCloseBtn').addEventListener('click', closeDropdown);

  modelSearch.addEventListener('input', () => {
    const q = modelSearch.value.toLowerCase();
    // Determine the source list: for the duo right slot, use whichever provider pill is active.
    let sourceList;
    if (state._pickingSlot === 'right') {
      const activePill = document.querySelector('#pickerProviderPill .pill-opt.active');
      const activeProv = activePill?.dataset?.provider;
      sourceList = getProviderModels(activeProv);
    } else {
      sourceList = state.models;
    }
    const filtered = sourceList.filter(
      (m) => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q)
    );
    renderDropdownList(filtered);
  });

  $('settingsCloseBtn').addEventListener('click', closeSettings);
  $('settingsCancelBtn').addEventListener('click', closeSettings);
  $('settingsBackdrop').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeSettings();
  });
  $('settingsSaveBtn').addEventListener('click', saveSettings);
  $('apiKeyInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); $('verifyKeyBtn').click(); }
  });

  $('tempSlider').addEventListener('input', () => updateTempSlider($('tempSlider').value));

  $('toggleKeyVisibility').addEventListener('click', async () => {
    const input = $('apiKeyInput');
    const show = input.type === 'password';
    if (show && input.dataset.sentinel) {
      try {
        const data = await api(`/settings?provider=${state.provider}&reveal_key=1`);
        if (data.key) { input.value = data.key; delete input.dataset.sentinel; }
      } catch { /* keep sentinel */ }
    }
    input.type = show ? 'text' : 'password';
    $('eyeOpen').style.display = show ? 'none' : '';
    $('eyeClosed').style.display = show ? '' : 'none';
  });

  $('apiKeyInput').addEventListener('input', () => {
    const el = $('apiKeyInput');
    if (el.dataset.sentinel) {
      delete el.dataset.sentinel;
      setKeyStatus('Enter a new key or keep current.');
    }
    if (el.dataset.removeKey) {
      delete el.dataset.removeKey;
      setKeyStatus('Enter a new key or keep current.');
    }
  });

  $('removeKeyBtn').addEventListener('click', () => {
    const input = $('apiKeyInput');
    input.value = '';
    delete input.dataset.sentinel;
    input.dataset.removeKey = '1';
    $('removeKeyBtn').style.display = 'none';
    setKeyStatus('Key will be removed on save.', 'warn');
  });

  $('verifyKeyBtn').addEventListener('click', async () => {
    const input = $('apiKeyInput');
    const key = input.dataset.sentinel ? null : input.value.trim();
    const baseUrl = $('baseUrlInput').value.trim();
    const accountId = $('accountIdInput') ? $('accountIdInput').value.trim() : '';
    if (!key && !input.dataset.sentinel) {
      setKeyStatus('Enter a key first.', 'warn');
      return;
    }
    const btn = $('verifyKeyBtn');
    btn.textContent = 'Verifying…';
    btn.disabled = true;
    setKeyStatus('');
    try {
      const config = PROVIDER_UI_CONFIG[state.provider] || PROVIDER_UI_CONFIG.nim;
      const body = {
        provider: state.provider,
        base_url: baseUrl || config.defaultBaseUrl
      };
      if (config.showAccountId) body.account_id = accountId;
      if (key) body.key = key;
      else {
        const cur = await api(`/settings?provider=${state.provider}&reveal_key=1`);
        body.key = cur.key;
      }
      const res = await fetch('/api/verify-key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.valid) {
        setKeyStatus(data.message || 'Key is valid!', 'ok');
      } else {
        setKeyStatus(data.error || 'Key is invalid.', 'warn');
      }
    } catch {
      setKeyStatus('Verification failed — server error.', 'warn');
    } finally {
      btn.textContent = 'Verify key';
      btn.disabled = false;
    }
  });
}
