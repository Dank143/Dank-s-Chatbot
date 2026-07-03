import {
  state, $,
  messagesEl, welcomeEl, inputAreaEl, messageInput,
  chatTitleDisplay, renameBtn,
  starredList, recentList, starredLabel, recentsLabel, sidebar,
  escHtml, autoResize, updateSendBtn, setWebSearch, needsWebSearch,
  clientTime, beginStreaming, endStreaming, setProvider,
  topStarBtn, topDeleteBtn,
  duoToggleBtn, duoModelSelectorBtn, duoModelSep,
} from './state.js';
import { api } from './api.js';
import { clearPendingFiles } from './files.js';
import { updateModelLabel, updateDuoModelLabel } from './models.js';
import { appendMessage, injectRetryDuoButton } from './messages.js';
import { streamAssistant } from './stream.js';

const GREETINGS = [
  'Hello there!', "What's up?", 'Greetings!', 'Good to see you!',
  'Hey, Dang!', 'Welcome back!', "How's it going?", 'Ready when you are.',
  "Let's do this!", 'What can I help with?',
];

const TOPICS = [
  {
    name: 'Code',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
    prompts: [
      'Review my code for bugs and improvements',
      'Help me debug this error message',
      'Explain this code snippet line by line',
    ],
  },
  {
    name: 'Learn',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/></svg>',
    prompts: [
      'Explain quantum computing in simple terms',
      'Describe the SOLID principles in software design',
      'Explain how machine learning works',
    ],
  },
  {
    name: 'Strategize',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="3" x2="3" y2="21"/><line x1="3" y1="21" x2="21" y2="21"/><polyline points="7 14 11 10 14 13 20 7"/></svg>',
    prompts: [
      'Help me plan a product launch roadmap',
      'Suggest a go-to-market strategy for a SaaS app',
      'Analyze the pros and cons of this business decision',
    ],
  },
  {
    name: 'Write',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
    prompts: [
      'Draft a professional email to a client',
      'Write a compelling cover letter for a job',
      'Help me outline a blog post about AI',
    ],
  },
  {
    name: 'Life',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8h1a4 4 0 0 1 0 8h-1"/><path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4z"/><line x1="6" y1="1" x2="6" y2="4"/><line x1="10" y1="1" x2="10" y2="4"/><line x1="14" y1="1" x2="14" y2="4"/></svg>',
    prompts: [
      'Suggest a healthy weekly meal plan',
      'Give me tips to improve my sleep',
      'Help me plan a weekend trip itinerary',
    ],
  },
];

export function setupHomeScreen() {
  const greeting = $('welcomeGreeting');
  greeting.textContent = GREETINGS[Math.floor(Math.random() * GREETINGS.length)];
  greeting.classList.remove('fade-in-up');
  void greeting.offsetWidth;
  greeting.classList.add('fade-in-up');

  const chips = $('questionChips');
  const panel = $('topicPanel');
  chips.innerHTML = '';
  panel.innerHTML = '';
  panel.classList.remove('open', 'closing');
  let activeTopic = null;

  TOPICS.forEach((topic, i) => {
    const btn = document.createElement('button');
    btn.className = 'topic-chip fade-in-up';
    btn.style.animationDelay = `${0.18 + i * 0.08}s`;
    btn.innerHTML = `${topic.icon}<span>${topic.name}</span>`;
    btn.onclick = () => {
      if (activeTopic === topic.name) {
        closeTopicPanel();
        btn.classList.remove('active');
        activeTopic = null;
        return;
      }
      activeTopic = topic.name;
      chips.querySelectorAll('.topic-chip').forEach((c) => c.classList.remove('active'));
      btn.classList.add('active');
      openTopicPanel(topic.prompts, btn);
    };
    chips.appendChild(btn);
  });
}

function positionCaret(panel, btn) {
  const pr = panel.getBoundingClientRect();
  const br = btn.getBoundingClientRect();
  panel.style.setProperty('--caret-x', `${br.left + br.width / 2 - pr.left}px`);
}

function openTopicPanel(prompts, btn) {
  const panel = $('topicPanel');
  panel.innerHTML = '';
  prompts.forEach((q, i) => {
    const row = document.createElement('button');
    row.className = 'topic-prompt';
    row.style.animationDelay = `${i * 0.05}s`;
    row.textContent = q;
    row.onclick = () => {
      messageInput.value = q;
      autoResize();
      updateSendBtn();
      sendMessage();
    };
    panel.appendChild(row);
  });
  panel.classList.remove('closing');
  panel.classList.add('open');
  positionCaret(panel, btn);
}

function closeTopicPanel() {
  const panel = $('topicPanel');
  if (!panel.classList.contains('open')) return;
  panel.classList.add('closing');
  panel.addEventListener('animationend', function done(e) {
    if (e.target !== panel || e.animationName !== 'panelOut') return;
    panel.classList.remove('open', 'closing');
    panel.removeEventListener('animationend', done);
  });
}

export async function loadChats() {
  state.chats = await api('/chats');
  renderSidebar();
}

export function renderSidebar() {
  const visibleChats = state.chats;

  const starred = visibleChats.filter((c) => c.starred);
  const recents  = visibleChats.filter((c) => !c.starred);

  starredLabel.style.display = starred.length ? '' : 'none';
  starredList.innerHTML = '';
  starred.forEach((c) => starredList.appendChild(makeChatItem(c)));

  recentsLabel.style.display = recents.length ? '' : 'none';
  recentList.innerHTML = '';
  recents.forEach((c) => recentList.appendChild(makeChatItem(c)));

  if (collapsedStarList) {
    collapsedStarList.innerHTML = '';
    const topStarred = starred.slice(0, 10);
    if (topStarred.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'sidebar-popup-item';
      empty.style.color = 'var(--text-muted)';
      empty.style.cursor = 'default';
      empty.style.pointerEvents = 'none';
      empty.textContent = 'No starred chats';
      collapsedStarList.appendChild(empty);
    } else {
      topStarred.forEach(c => {
        const item = document.createElement('div');
        item.className = 'sidebar-popup-item';
        item.textContent = c.title || 'New Chat';
        item.onclick = () => openChat(c.id);
        collapsedStarList.appendChild(item);
      });
    }
  }

  if (collapsedRecentList) {
    collapsedRecentList.innerHTML = '';
    const topRecents = recents.slice(0, 10);
    if (topRecents.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'sidebar-popup-item';
      empty.style.color = 'var(--text-muted)';
      empty.style.cursor = 'default';
      empty.style.pointerEvents = 'none';
      empty.textContent = 'No recent chats';
      collapsedRecentList.appendChild(empty);
    } else {
      topRecents.forEach(c => {
        const item = document.createElement('div');
        item.className = 'sidebar-popup-item';
        item.textContent = c.title || 'New Chat';
        item.onclick = () => openChat(c.id);
        collapsedRecentList.appendChild(item);
      });
    }
  }
}

function makeChatItem(chat) {
  const el = document.createElement('div');
  el.className = 'chat-item' + (chat.id === state.activeChatId ? ' active' : '');
  el.dataset.id = chat.id;

  el.innerHTML = `
    <span class="chat-item-title">${escHtml(chat.title)}</span>
    <div class="chat-item-actions">
      <button class="chat-action-btn rename-item-btn" title="Rename">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
        </svg>
      </button>
      <button class="chat-action-btn star-btn ${chat.starred ? 'starred' : ''}" title="${chat.starred ? 'Unstar' : 'Star'}">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="${chat.starred ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2">
          <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
        </svg>
      </button>
      <button class="chat-action-btn delete-btn" title="Delete">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6"/>
          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
          <path d="M10 11v6"/><path d="M14 11v6"/>
        </svg>
      </button>
    </div>
  `;

  el.querySelector('.chat-item-title').addEventListener('click', (e) => {
    if (e.currentTarget.isContentEditable) return;  // mid-rename: don't navigate
    openChat(chat.id);
  });

  el.querySelector('.star-btn').addEventListener('click', async (e) => {
    e.stopPropagation();
    await api(`/chats/${chat.id}`, { method: 'PATCH', body: { starred: !chat.starred } });
    await loadChats();
  });

  el.querySelector('.rename-item-btn').addEventListener('click', (e) => {
    e.stopPropagation();
    startInlineRename(el.querySelector('.chat-item-title'), chat.id, chat.title);
  });

  el.querySelector('.delete-btn').addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!await confirmDialog(`Delete "${chat.title}"?`)) return;
    await api(`/chats/${chat.id}`, { method: 'DELETE' });
    if (state.activeChatId === chat.id) showWelcome();
    await loadChats();
  });

  return el;
}

export async function openChat(chatId) {
  if (state.streaming) {
    state.abortController?.abort();
    endStreaming();
  }
  state.activeChatId = chatId;
  setWebSearch(localStorage.getItem(`webSearch_${chatId}`) === '1');
  clearPendingFiles();
  renderSidebar();

  const chat = await api(`/chats/${chatId}`);

  const hasNim = state.hasKeyNim;
  const hasOllama = state.hasKeyOllama;
  const bothAvailable = hasNim && hasOllama;
  const onlyNim = hasNim && !hasOllama;
  const onlyOllama = !hasNim && hasOllama;

  let targetModel = chat.model || state.defaultModel;

  if (bothAvailable && targetModel) {
    const isNimModel = state.modelsNim?.some(m => m.id === targetModel);
    const isOllamaModel = state.modelsOllama?.some(m => m.id === targetModel);
    if (isNimModel && state.provider !== 'nim') {
      setProvider('nim');
    } else if (isOllamaModel && state.provider !== 'ollama') {
      setProvider('ollama');
    }
  } else if (onlyNim) {
    setProvider('nim');
    const isNimModel = state.modelsNim?.some(m => m.id === targetModel);
    if (!isNimModel) {
      targetModel = state.defaultModelNim;
      api(`/chats/${chatId}`, { method: 'PATCH', body: { model: targetModel } }).catch(() => {});
    }
  } else if (onlyOllama) {
    setProvider('ollama');
    const isOllamaModel = state.modelsOllama?.some(m => m.id === targetModel);
    if (!isOllamaModel) {
      targetModel = state.defaultModelOllama;
      api(`/chats/${chatId}`, { method: 'PATCH', body: { model: targetModel } }).catch(() => {});
    }
  }

  state.selectedModel = targetModel;
  updateModelLabel();
  chatTitleDisplay.textContent = chat.title;
  renameBtn.style.display = '';
  topStarBtn.style.display = '';
  topDeleteBtn.style.display = '';
  topStarBtn.querySelector('svg').setAttribute('fill', chat.starred ? 'currentColor' : 'none');
  topStarBtn.classList.toggle('starred', chat.starred);

  welcomeEl.style.display = 'none';
  document.querySelector('.main').appendChild(inputAreaEl);
  messagesEl.style.display = 'flex';
  inputAreaEl.style.display = 'flex';
  messagesEl.innerHTML = '';

  state.duoMode = chat.duo_mode === 1;
  document.querySelector('.main').classList.toggle('duo-mode', state.duoMode);
  duoModelSep.style.display = state.duoMode ? '' : 'none';
  duoModelSelectorBtn.style.display = state.duoMode ? '' : 'none';
  duoToggleBtn.classList.toggle('active', state.duoMode);
  let lastModel1 = null;
  let lastModel2 = null;

  let i = 0;
  while (i < chat.messages.length) {
    const msg = chat.messages[i];
    if (msg.role === 'assistant' && i + 1 < chat.messages.length && chat.messages[i+1].role === 'assistant') {
      const row = document.createElement('div');
      row.className = 'duo-message-row';
      messagesEl.appendChild(row);
      
      let leftMsg = msg;
      let rightMsg = chat.messages[i+1];
      if (msg.duo_side === 1 && chat.messages[i+1].duo_side === 0) {
        leftMsg = chat.messages[i+1];
        rightMsg = msg;
      }

      appendMessage(leftMsg, false, row);
      appendMessage(rightMsg, false, row);
      lastModel1 = leftMsg.model;
      lastModel2 = rightMsg.model;
      injectRetryDuoButton(row);
      i += 2;
      continue;
    }
    if (msg.role === 'assistant') {
      // Orphaned assistant message. Check if it was part of an interrupted duo generation.
      let isOrphanedDuo = false;
      const prevMsg = i > 0 ? chat.messages[i-1] : null;
      if (msg.duo_side === 1) {
        isOrphanedDuo = true; // Definitely the right side of a duo
      } else if (chat.duo_mode === 1 && i === chat.messages.length - 1 && prevMsg && prevMsg.role === 'user') {
        isOrphanedDuo = true; // Last message in a duo chat, partner probably didn't finish
      }

      if (isOrphanedDuo) {
        const row = document.createElement('div');
        row.className = 'duo-message-row';
        messagesEl.appendChild(row);

        const placeholder = { role: 'assistant', content: '_Generation interrupted or failed_', model: state.selectedModel, duo_side: msg.duo_side === 0 ? 1 : 0 };
        const leftMsg = msg.duo_side === 0 ? msg : placeholder;
        const rightMsg = msg.duo_side === 1 ? msg : placeholder;

        appendMessage(leftMsg, false, row);
        appendMessage(rightMsg, false, row);
        lastModel1 = leftMsg.model;
        lastModel2 = rightMsg.model;
        injectRetryDuoButton(row);

        // Retroactively mark the preceding user prompt as duo so it gets centered properly
        const userWrappers = messagesEl.querySelectorAll('.message-wrapper.user');
        const lastUserWrapper = userWrappers[userWrappers.length - 1];
        if (lastUserWrapper) lastUserWrapper.classList.add('duo');

        i++;
        continue;
      }

      lastModel1 = msg.model;
      lastModel2 = null;
    }
    
    if (msg.role === 'user') {
      let isDuo = false;
      // Normal duo pair check
      if (i + 1 < chat.messages.length && chat.messages[i+1].role === 'assistant' && 
          i + 2 < chat.messages.length && chat.messages[i+2].role === 'assistant') {
        isDuo = true;
      }
      // Orphaned duo check for the user prompt
      else if (chat.duo_mode === 1 && i === chat.messages.length - 2 && chat.messages[i+1].role === 'assistant') {
        isDuo = true;
      }
      
      const wrapper = appendMessage(msg);
      if (isDuo) wrapper.classList.add('duo');
      i++;
      continue;
    }
    appendMessage(msg);
    i++;
  }

  // Restore the models in the UI selectors from the last conversation turn.
  // Also sync state.provider so the picker opens on the correct NIM/Ollama tab.
  if (lastModel1) {
    state.selectedModel = lastModel1;
    const inNim = state.modelsNim?.some(m => m.id === lastModel1);
    const inOllama = state.modelsOllama?.some(m => m.id === lastModel1);
    if (inNim && state.provider !== 'nim') setProvider('nim');
    else if (inOllama && state.provider !== 'ollama') setProvider('ollama');
    // Re-apply the correct selected model because setProvider may have reset it.
    state.selectedModel = lastModel1;
    updateModelLabel();
  }
  if (state.duoMode) {
    if (lastModel2) {
      state.selectedModel2 = lastModel2;
    } else if (!state.selectedModel2) {
      state.selectedModel2 = state.selectedModel;
    }
    updateDuoModelLabel();
  }

  messageInput.focus();
}

export async function createNewChat() {
  const chat = await api('/chats', { 
    method: 'POST', 
    body: { model: state.selectedModel, duo_mode: state.duoMode } 
  });
  state.chats.unshift(chat);
  if (state.webSearch) localStorage.setItem(`webSearch_${chat.id}`, '1');
  await openChat(chat.id);
}

export function showWelcome() {
  state.activeChatId = null;
  
  const hasNim = state.hasKeyNim;
  const hasOllama = state.hasKeyOllama;
  
  if (hasNim && hasOllama) {
    setProvider('nim');
    state.selectedModel = state.defaultModelNim;
  } else if (!hasNim && hasOllama) {
    setProvider('ollama');
    state.selectedModel = state.defaultModelOllama;
  } else if (hasNim && !hasOllama) {
    setProvider('nim');
    state.selectedModel = state.defaultModelNim;
  } else {
    state.selectedModel = state.defaultModel;
  }
  
  state.duoMode = false;
  document.querySelector('.main').classList.toggle('duo-mode', false);
  duoModelSep.style.display = 'none';
  duoModelSelectorBtn.style.display = 'none';
  duoToggleBtn.classList.remove('active');
  
  setWebSearch(false);
  clearPendingFiles();
  updateModelLabel();
  welcomeEl.insertBefore(inputAreaEl, $('questionChips'));
  welcomeEl.style.display = 'flex';
  messagesEl.style.display = 'none';
  inputAreaEl.style.display = 'flex';
  setupHomeScreen();
  chatTitleDisplay.textContent = "Dank's Chatbot";
  renameBtn.style.display = 'none';
  topStarBtn.style.display = 'none';
  topDeleteBtn.style.display = 'none';
  renderSidebar();
}

// Collect input + attachments, create chat if needed, and stream the reply.
export async function sendMessage() {
  const content = messageInput.value.trim();
  const images = state.pendingFiles.filter(f => f.kind === 'image').map(f => f.dataUrl);
  const documents = state.pendingFiles.filter(f => f.kind === 'document').map(f => ({ name: f.name, text: f.text }));
  if ((!content && images.length === 0 && documents.length === 0) || state.streaming) return;

  if (!state.activeChatId) {
    await createNewChat();
  }

  messageInput.value = '';
  autoResize();
  clearPendingFiles();
  beginStreaming();

  const attJson = (images.length || documents.length)
    ? JSON.stringify({ images, documents })
    : null;

  if (state.duoMode && state.selectedModel2) {
    // ── Duo mode: stream both models in parallel ──
    const userWrapper = appendMessage({ role: 'user', content, attachments: attJson });
    userWrapper.classList.add('duo');
    const row = document.createElement('div');
    row.className = 'duo-message-row';
    messagesEl.appendChild(row);

    const asstWrapperL = appendMessage({ role: 'assistant', content: '', model: state.selectedModel }, true, row, 0);
    const asstWrapperR = appendMessage({ role: 'assistant', content: '', model: state.selectedModel2 }, true, row, 1);

    const bodyBase = {
      content,
      images: images.length ? images : undefined,
      documents: documents.length ? documents : undefined,
      web_search: state.webSearch || needsWebSearch(content) || undefined,
      client_time: clientTime(),
    };

    await Promise.allSettled([
      streamAssistant(
        `/api/chats/${state.activeChatId}/messages`,
        { ...bodyBase, model: state.selectedModel, duo_side: 0 },
        userWrapper, asstWrapperL
      ),
      streamAssistant(
        `/api/chats/${state.activeChatId}/messages`,
        { ...bodyBase, model: state.selectedModel2, skip_user_save: true, duo_side: 1 },
        null, asstWrapperR
      ),
    ]);

    injectRetryDuoButton(row);
  } else {
    // ── Normal single-model path ──
    const userWrapper = appendMessage({ role: 'user', content, attachments: attJson });
    const assistantWrapper = appendMessage({ role: 'assistant', content: '', model: state.selectedModel }, true);

    await streamAssistant(
      `/api/chats/${state.activeChatId}/messages`,
      { content, model: state.selectedModel,
        images: images.length ? images : undefined,
        documents: documents.length ? documents : undefined,
        web_search: state.webSearch || needsWebSearch(content) || undefined,
        client_time: clientTime() },
      userWrapper,
      assistantWrapper
    );
  }

  endStreaming();
  updateSendBtn();
  messageInput.focus();
  await loadChats();
}

export function confirmDialog(message, okText = 'Delete', okBtnClass = 'btn-danger') {
  return new Promise((resolve) => {
    $('confirmMessage').textContent = message;
    const okBtn = $('confirmOkBtn');
    okBtn.textContent = okText;
    okBtn.className = okBtnClass;
    
    $('confirmBackdrop').style.display = 'flex';

    const cleanup = (result) => {
      $('confirmBackdrop').style.display = 'none';
      resolve(result);
    };

    $('confirmOkBtn').onclick     = () => cleanup(true);
    $('confirmCancelBtn').onclick = () => cleanup(false);
    $('confirmBackdrop').onclick  = (e) => { if (e.target === $('confirmBackdrop')) cleanup(false); };
  });
}

// Inline rename: edit title in place. Enter/blur saves, Escape cancels.
export function startInlineRename(el, chatId, currentTitle) {
  el.setAttribute('contenteditable', 'true');
  el.classList.add('editing');
  el.textContent = currentTitle;
  el.focus();
  // Select the whole title so typing replaces it.
  const range = document.createRange();
  range.selectNodeContents(el);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);

  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    el.removeAttribute('contenteditable');
    el.classList.remove('editing');
    const title = el.textContent.trim();
    if (save && title && title !== currentTitle) {
      await api(`/chats/${chatId}`, { method: 'PATCH', body: { title } });
      if (chatId === state.activeChatId) chatTitleDisplay.textContent = title;
      await loadChats();
    } else {
      el.textContent = currentTitle;  // restore on cancel / empty
    }
  };

  el.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
  });
  el.addEventListener('blur', () => finish(true), { once: true });
}

export function toggleSidebar() { 
  sidebar.classList.toggle('collapsed');
  localStorage.setItem('sidebarCollapsed', sidebar.classList.contains('collapsed') ? '1' : '0');
}

export function toggleDuo() {
  state.duoMode = !state.duoMode;
  const main = document.querySelector('.main');
  main.classList.toggle('duo-mode', state.duoMode);

  // Show/hide second model selector in input bar
  duoModelSep.style.display          = state.duoMode ? '' : 'none';
  duoModelSelectorBtn.style.display  = state.duoMode ? '' : 'none';

  duoToggleBtn.classList.toggle('active', state.duoMode);

  if (state.activeChatId) {
    api(`/chats/${state.activeChatId}`, { 
      method: 'PATCH', 
      body: { duo_mode: state.duoMode } 
    }).catch(() => {});
  }

  // Seed model2 if not set
  if (state.duoMode && !state.selectedModel2) {
    state.selectedModel2 = state.selectedModel;
    updateDuoModelLabel();
  }
}

