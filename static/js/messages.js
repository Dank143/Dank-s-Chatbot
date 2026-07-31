import { state, $, messagesEl, escHtml, escAttr, scrollToBottom, updateSendBtn, needsWebSearch, clientTime, beginStreaming, endStreaming } from './state.js';
import { api } from './api.js';
import { renderMarkdown } from './markdown.js';
import { DOC_ICON, _docStore, nextDocKey, openDocViewer } from './files.js';
import { badgeHtml, findModelById } from './models.js';
import { streamAssistant, getSearchPanelHtml } from './stream.js';
import { ICON, getAssistantActions } from './icons.js';

// Extract <think>...</think> from persisted message content.
function extractThink(content) {
  const match = content.match(/^<think>([\s\S]*?)<\/think>\n?/);
  if (!match) return { think: '', visible: content };
  return { think: match[1], visible: content.slice(match[0].length) };
}

// Thinking indicator: hourglass + random phrase with cycling dots.
const THINKING_PHRASES = ['Brainstorming', 'Pondering', 'Thinking'];
export function thinkingIndicator() {
  const phrase = THINKING_PHRASES[Math.floor(Math.random() * THINKING_PHRASES.length)];
  return `
  <div class="thinking-indicator">
    <svg class="thinking-hourglass" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M5 22h14"/><path d="M5 2h14"/>
      <path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22"/>
      <path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"/>
    </svg>
    <span class="thinking-label">${phrase}<span class="thinking-dots"></span></span>
  </div>`;
}

// Inner content for the .search-indicator: scanning magnifying glass + query + cycling dots.
export function searchIndicatorHtml(query) {
  return `
    <svg class="search-glass" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
    </svg>
    <span class="search-label">Searching for your query<span class="thinking-dots"></span></span>`;
}

// Render a user or assistant message bubble (streaming=true adds cursor placeholder).
export function appendMessage(msg, streaming = false, container = null, duoSide = null) {
  const target = container || messagesEl;
  const wrapper = document.createElement('div');
  wrapper.className = `message-wrapper ${msg.role}`;
  if (msg.id) wrapper.dataset.msgId = msg.id;
  if (msg.model) wrapper.dataset.model = msg.model;
  if (duoSide !== null) wrapper.dataset.duoSide = duoSide;
  else if (msg.duo_side !== undefined) wrapper.dataset.duoSide = msg.duo_side;

  if (msg.role === 'user') {
    if (msg.attachments) wrapper.dataset.attachments = typeof msg.attachments === 'string' ? msg.attachments : JSON.stringify(msg.attachments);

    const att = msg.attachments ? JSON.parse(msg.attachments) : {};
    const imgs = Array.isArray(att) ? att : (att.images || []);
    const docs = Array.isArray(att) ? [] : (att.documents || []);
    const imagesHtml = imgs.length
      ? `<div class="msg-images">${imgs.map(img => {
          const src = typeof img === 'object' ? img.dataUrl : img;
          return `<img class="msg-image" src="${src}" alt="attachment">`;
        }).join('')}</div>`
      : '';
    const docsHtml = docs.length
      ? `<div class="msg-docs">${docs.map(d => {
        if (d.text) {
          const k = nextDocKey();
          _docStore.set(k, { name: d.name, text: d.text });
          return `<span class="msg-doc-chip" data-doc-key="${k}">${DOC_ICON}<span>${escHtml(d.name)}</span></span>`;
        }
        return `<span class="msg-doc-chip">${DOC_ICON}<span>${escHtml(d.name)}</span></span>`;
      }).join('')}</div>`
      : '';
    wrapper.innerHTML = `
      <div class="bubble">${imagesHtml}${docsHtml}${escHtml(msg.content)}</div>
      <div class="message-actions">
        <button class="msg-action-btn" title="Copy" onclick="copyMessage(this)">${ICON.copy}</button>
        <button class="msg-action-btn" title="Edit" onclick="editMessage(this)">${ICON.edit}</button>
      </div>
    `;
  } else {
    const { think, visible } = extractThink(msg.content);
    const msgModel = msg.model || state.selectedModel;
    const modelObj  = findModelById(msgModel);
    const modelName = modelObj?.name || '';
    let searchPanelHtml = '';
    if (msg.search_data) {
      try {
        const parsed = typeof msg.search_data === 'string' ? JSON.parse(msg.search_data) : msg.search_data;
        searchPanelHtml = getSearchPanelHtml(parsed);
      } catch (e) {
        console.error('Failed to parse search_data', e);
      }
    }

    let ttfsMs = null;
    let totalMs = null;
    let thoughtSecs = null;
    if (msg.timing_data) {
      try {
        const parsed = typeof msg.timing_data === 'string' ? JSON.parse(msg.timing_data) : msg.timing_data;
        ttfsMs = parsed.ttfs_ms;
        totalMs = parsed.total_ms;
        if (parsed.thought_time_ms !== undefined) thoughtSecs = Math.round(parsed.thought_time_ms / 1000);
      } catch (e) {
        console.error('Failed to parse timing_data', e);
      }
    }

    let thinkBlockHtml = '';
    if (think && !streaming) {
      const durationStr = thoughtSecs !== null ? `Thought for ${thoughtSecs}s` : `Thought process`;
      thinkBlockHtml = `
        <div class="think-block">
          <div class="think-toggle">
            <svg class="think-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
            <span class="think-label">${durationStr}</span>
          </div>
          <div class="think-content">${renderMarkdown(think)}</div>
        </div>`;
    }

    wrapper.innerHTML = `
      <div class="assistant-header">
        ${badgeHtml(msgModel, 26)}
        ${modelName ? `<span class="model-tag">${escHtml(modelName)}</span>` : ''}
      </div>
      <div class="message-body">
        ${thinkBlockHtml}
        <div class="bubble" data-raw="${escAttr(visible)}">
          ${streaming ? thinkingIndicator() : renderMarkdown(visible)}
        </div>
        ${searchPanelHtml}
      </div>
      ${!streaming ? getAssistantActions(ttfsMs, totalMs) : ''}
    `;
    // Attach click handler for think-toggle
    const toggle = wrapper.querySelector('.think-toggle');
    if (toggle) toggle.addEventListener('click', () => toggle.closest('.think-block').classList.toggle('expanded'));
  }

  target.appendChild(wrapper);
  scrollToBottom();
  return wrapper;
}

// Render a new prompt and stream either one reply or a duo pair.
export async function streamNewMessage(content, images = [], documents = []) {
  const attachments = images.length || documents.length
    ? JSON.stringify({ images, documents })
    : null;
  const userWrapper = appendMessage({ role: 'user', content, attachments });
  const body = {
    content,
    images: images.length ? images : undefined,
    documents: documents.length ? documents : undefined,
    web_search: state.webSearch || needsWebSearch(content) || undefined,
    client_time: clientTime(),
    persona: state.selectedPersona,
  };
  const endpoint = `/api/chats/${state.activeChatId}/messages`;

  if (!state.duoMode || !state.selectedModel2) {
    const assistantWrapper = appendMessage(
      { role: 'assistant', content: '', model: state.selectedModel },
      true,
    );
    await streamAssistant(
      endpoint,
      { ...body, model: state.selectedModel },
      userWrapper,
      assistantWrapper,
    );
    return;
  }

  userWrapper.classList.add('duo');
  const row = document.createElement('div');
  row.className = 'duo-message-row';
  messagesEl.appendChild(row);
  const left = appendMessage(
    { role: 'assistant', content: '', model: state.selectedModel },
    true, row, 0,
  );
  const right = appendMessage(
    { role: 'assistant', content: '', model: state.selectedModel2 },
    true, row, 1,
  );

  await Promise.allSettled([
    streamAssistant(endpoint, { ...body, model: state.selectedModel, duo_side: 0 }, userWrapper, left),
    streamAssistant(endpoint, {
      ...body,
      model: state.selectedModel2,
      skip_user_save: true,
      duo_side: 1,
    }, null, right),
  ]);
  injectRetryDuoButton(row);
}

export function finalizeStreamingMessage(wrapper, ttfsMs = null, totalMs = null) {
  const bubble = wrapper.querySelector('.bubble');
  const raw = bubble.dataset.raw || '';
  if (raw) bubble.innerHTML = renderMarkdown(raw);
  else { bubble.querySelector('.streaming-cursor')?.remove(); bubble.querySelector('.thinking-indicator')?.remove(); }
  wrapper.insertAdjacentHTML('beforeend', getAssistantActions(ttfsMs, totalMs));
  // Attach click handler to think-toggle if present
  const toggle = wrapper.querySelector('.think-toggle');
  if (toggle && !toggle.dataset.bound) {
    toggle.dataset.bound = '1';
    toggle.addEventListener('click', () => toggle.closest('.think-block').classList.toggle('expanded'));
  }
  if (state.autoScroll) scrollToBottom();
}

export function showTruncationNotice(wrapper) {
  const notice = document.createElement('div');
  notice.className = 'truncation-notice';
  notice.innerHTML = `
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
      <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
    </svg>
    Response cut off — token limit reached. Ask it to continue.`;
  wrapper.appendChild(notice);
}

export function showStoppedNotice(wrapper) {
  const notice = document.createElement('div');
  notice.className = 'truncation-notice stopped-notice';
  notice.innerHTML = `
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="3" y="3" width="18" height="18" rx="2"/>
    </svg>
    Generation Stopped.`;
  wrapper.appendChild(notice);
}

export function showMessageError(wrapper, msg, ttfsMs = null, totalMs = null) {
  const bubble = wrapper.querySelector('.bubble');
  bubble?.querySelector('.streaming-cursor')?.remove();
  if (bubble) bubble.innerHTML = `<div class="error-bubble">Error: ${escHtml(msg)}</div>`;
  if (!wrapper.querySelector('.message-actions')) {
    wrapper.insertAdjacentHTML('beforeend', getAssistantActions(ttfsMs, totalMs));
  }
}

export function copyMessage(btn) {
  const wrapper = btn.closest('.message-wrapper');
  const bubble = wrapper.querySelector('.bubble');
  // Copy only the visible answer, not the thinking content
  const text = bubble.dataset.raw || bubble.textContent;
  navigator.clipboard.writeText(text).then(() => {
    btn.classList.add('copied');
    setTimeout(() => btn.classList.remove('copied'), 1500);
  });
}

const LANG_EXT = {
  python: 'py', py: 'py',
  javascript: 'js', js: 'js',
  typescript: 'ts', ts: 'ts',
  html: 'html', css: 'css',
  java: 'java', kotlin: 'kt',
  c: 'c', cpp: 'cpp', 'c++': 'cpp',
  rust: 'rs', go: 'go',
  bash: 'sh', sh: 'sh', shell: 'sh', zsh: 'sh',
  sql: 'sql', json: 'json',
  yaml: 'yaml', yml: 'yaml',
  markdown: 'md', md: 'md',
  xml: 'xml', toml: 'toml',
  ruby: 'rb', php: 'php', swift: 'swift',
  r: 'r', scala: 'scala', perl: 'pl',
};

export function downloadCode(btn) {
  const wrap = btn.closest('.code-block-wrap');
  const code = wrap.querySelector('code').textContent;
  const lang = wrap.querySelector('.code-lang')?.textContent?.toLowerCase().trim() || '';
  const ext = LANG_EXT[lang] || 'txt';
  const filename = `code.${ext}`;
  const blob = new Blob([code], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function copyCode(btn) {
  const code = btn.closest('.code-block-wrap').querySelector('code').textContent;
  navigator.clipboard.writeText(code).then(() => {
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => {
      btn.classList.remove('copied');
      btn.innerHTML = `
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="9" y="9" width="13" height="13" rx="2"/>
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
        </svg>
        Copy`;
    }, 1500);
  });
}

// Delete this message and everything after it.
async function deleteFrom(wrapper, msgId) {
  await api(`/chats/${state.activeChatId}/messages/from/${msgId}`, { method: 'DELETE' });
  const wrappers = [...messagesEl.querySelectorAll('.message-wrapper')];
  wrappers.slice(wrappers.indexOf(wrapper)).forEach((w) => {
    const parent = w.parentElement;
    w.remove();
    // Clean up empty duo rows to prevent floating buttons and lines
    if (parent && parent.classList.contains('duo-message-row')) {
      if (!parent.querySelector('.message-wrapper')) {
        parent.remove();
      }
    }
  });
}

async function deleteFollowingTurn(wrapper) {
  const next = wrapper.nextElementSibling;
  const target = next?.classList.contains('message-wrapper')
    ? next
    : next?.querySelector('.message-wrapper');
  if (target?.dataset.msgId) await deleteFrom(target, target.dataset.msgId);
}

function latestUserText() {
  const bubbles = messagesEl.querySelectorAll('.message-wrapper.user .bubble');
  const bubble = bubbles[bubbles.length - 1];
  return bubble?.dataset.raw || bubble?.textContent.trim() || '';
}

function resetForStreaming(wrapper) {
  const bubble = wrapper.querySelector('.bubble');
  bubble.innerHTML = '<div class="streaming-cursor"></div>';
  bubble.dataset.raw = '';
  wrapper.querySelector('.message-actions')?.remove();
  wrapper.querySelectorAll(
    '.generation-stopped, .error-box, .truncation-notice, .think-block',
  ).forEach((element) => element.remove());
}

export async function editMessage(btn) {
  if (state.streaming) return;
  const wrapper = btn.closest('.message-wrapper');
  const msgId = wrapper.dataset.msgId;
  if (!msgId) {
    await (await import('./chat.js')).openChat(state.activeChatId);
    return;
  }

  const bubble = wrapper.querySelector('.bubble');
  const originalHTML = wrapper.innerHTML;
  const bubbleClone = bubble.cloneNode(true);
  bubbleClone.querySelector('.msg-images')?.remove();
  bubbleClone.querySelector('.msg-docs')?.remove();
  const originalText = bubbleClone.textContent.trim();

  // Recover full image objects (with names) from the original message attachments
  let origAtt = {};
  try {
    const rawAtt = wrapper.dataset.attachments;
    if (rawAtt) origAtt = JSON.parse(rawAtt);
  } catch (e) {}
  const origImages = Array.isArray(origAtt) ? origAtt : (origAtt.images || []);
  const images = origImages.map(img => {
    if (typeof img === 'object' && img.dataUrl) return { name: img.name || 'image', dataUrl: img.dataUrl };
    if (typeof img === 'string') return { name: 'image', dataUrl: img };
    return null;
  }).filter(Boolean);
  const docs = [...bubble.querySelectorAll('.msg-doc-chip[data-doc-key]')].map(chip => {
    const entry = _docStore.get(+chip.dataset.docKey);
    return entry ? { name: entry.name, text: entry.text } : null;
  }).filter(Boolean);

  const hasAttachments = images.length || docs.length;

  wrapper.innerHTML = `
    <div class="edit-box">
      <div class="edit-content-wrapper">
        ${hasAttachments ? '<div class="attachment-previews edit-attachment-preview"></div>' : ''}
        <textarea class="edit-textarea">${escHtml(originalText)}</textarea>
      </div>
      <div class="edit-actions">
        <button class="btn-secondary edit-cancel-btn">Cancel</button>
        <button class="btn-primary edit-submit-btn">Submit</button>
      </div>
    </div>
  `;

  // Render attachment chips with remove buttons; splicing keeps indices in sync.
  const previewEl = wrapper.querySelector('.edit-attachment-preview');
  function renderEditAttachments() {
    if (!previewEl) return;
    previewEl.innerHTML = '';
    images.forEach((imgObj, i) => {
      const div = document.createElement('div');
      div.className = 'attachment-thumb';
      const img = document.createElement('img');
      img.src = imgObj.dataUrl; img.alt = imgObj.name || '';
      const rm = document.createElement('button');
      rm.className = 'attachment-remove'; rm.title = 'Remove'; rm.textContent = '×';
      rm.onclick = () => { images.splice(i, 1); renderEditAttachments(); };
      div.append(img, rm);
      previewEl.appendChild(div);
    });
    docs.forEach((d, i) => {
      const div = document.createElement('div');
      div.className = 'attachment-doc' + (d.text ? ' viewable' : '');
      div.innerHTML = DOC_ICON;
      const span = document.createElement('span');
      span.className = 'attachment-doc-name'; span.textContent = d.name;
      const rm = document.createElement('button');
      rm.className = 'attachment-remove'; rm.title = 'Remove'; rm.textContent = '×';
      rm.onclick = (e) => { e.stopPropagation(); docs.splice(i, 1); renderEditAttachments(); };
      div.append(span, rm);
      if (d.text) {
        div.title = 'Click to view';
        div.addEventListener('click', (e) => { if (!e.target.closest('.attachment-remove')) openDocViewer(d.name, d.text); });
      }
      previewEl.appendChild(div);
    });
  }
  renderEditAttachments();

  const ta = wrapper.querySelector('.edit-textarea');
  ta.style.height = 'auto';
  ta.style.height = ta.scrollHeight + 'px';
  ta.addEventListener('input', () => {
    const messagesScroll = messagesEl.scrollTop;
    const scrollY = window.scrollY;
    ta.style.height = 'auto';
    ta.style.height = ta.scrollHeight + 'px';
    messagesEl.scrollTop = messagesScroll;
    if (window.scrollY !== scrollY) window.scrollTo(window.scrollX, scrollY);
  });
  ta.focus();
  ta.setSelectionRange(ta.value.length, ta.value.length);

  wrapper.querySelector('.edit-cancel-btn').onclick = () => { wrapper.innerHTML = originalHTML; };

  wrapper.querySelector('.edit-submit-btn').onclick = async () => {
    const newContent = ta.value.trim();
    if (!newContent && images.length === 0 && docs.length === 0) return;
    if (state.streaming) return;

    await deleteFrom(wrapper, msgId);

    beginStreaming();

    await streamNewMessage(newContent, images, docs);

    endStreaming();
    updateSendBtn();
    await (await import('./chat.js')).loadChats();
  };
}

export async function retryMessage(btn) {
  if (state.streaming) return;
  const wrapper = btn.closest('.message-wrapper');
  const msgId = wrapper.dataset.msgId;
  const model = wrapper.dataset.model || state.selectedModel;

  if (!msgId) {
    const row = wrapper.closest('.duo-message-row');
    if (row) {
      return retryDuoMessage(row);
    } else {
      await (await import('./chat.js')).openChat(state.activeChatId);
      return;
    }
  }

  // Delete future turns (but keep current turn intact to preserve siblings in duo mode)
  const row = wrapper.closest('.duo-message-row');
  if (row) {
    row.querySelector('.retry-duo-btn')?.remove();
  }
  await deleteFollowingTurn(row || wrapper);

  // Mirror send/edit: honor web-search toggle or auto-detect.
  const lastUserText = latestUserText();

  beginStreaming();
  resetForStreaming(wrapper);
  
  // Notice we use overwrite_message_id instead of deleting the message entirely
  await streamAssistant(
    `/api/chats/${state.activeChatId}/regenerate`,
    {
      model,
      web_search: state.webSearch || needsWebSearch(lastUserText) || undefined,
      client_time: clientTime(),
      overwrite_message_id: msgId,
      duo_side: parseInt(wrapper.dataset.duoSide || 0),
      persona: state.selectedPersona
    },
    null, wrapper
  );

  endStreaming();
  updateSendBtn();
  $('messageInput').focus();
  await (await import('./chat.js')).loadChats();
  
  if (row && row.classList.contains('duo-message-row')) {
    injectRetryDuoButton(row);
  }
}

export function injectRetryDuoButton(row) {
  if (!row || row.querySelector('.retry-duo-btn')) return;
  const btnHtml = `<button class="retry-duo-btn" title="Retry Both" onclick="retryDuoMessage(this)">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
  </button>`;
  row.insertAdjacentHTML('beforeend', btnHtml);
}

export async function retryDuoMessage(btnOrRow) {
  if (state.streaming) return;
  const row = btnOrRow.classList?.contains('duo-message-row') ? btnOrRow : btnOrRow.closest('.duo-message-row');
  if (!row) return;
  
  const wrappers = Array.from(row.querySelectorAll('.message-wrapper'));
  if (wrappers.length !== 2) return;
  
  row.querySelector('.retry-duo-btn')?.remove();
  await deleteFollowingTurn(row);

  const lastUserText = latestUserText();
  const webSearch = state.webSearch || needsWebSearch(lastUserText) || undefined;
  const cTime = clientTime();

  beginStreaming();

  const validMsgId = wrappers[0].dataset.msgId || wrappers[1].dataset.msgId;

  const promises = wrappers.map(wrapper => {
    const msgId = wrapper.dataset.msgId || validMsgId;
    resetForStreaming(wrapper);

    return streamAssistant(
      `/api/chats/${state.activeChatId}/regenerate`,
      {
        model: wrapper.dataset.model,
        web_search: webSearch,
        client_time: cTime,
        overwrite_message_id: msgId,
        duo_side: parseInt(wrapper.dataset.duoSide || 0),
        persona: state.selectedPersona
      },
      null, wrapper
    );
  });

  await Promise.allSettled(promises);

  endStreaming();
  updateSendBtn();
  $('messageInput').focus();
  await (await import('./chat.js')).loadChats();
  
  injectRetryDuoButton(row);
}
