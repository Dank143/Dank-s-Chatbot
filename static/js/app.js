import './speech.js';
import { loadTheme } from './theme.js';
import { loadModels, loadPersonas } from './models.js';
import { loadChats, showWelcome, openChat } from './chat.js';
import { setupEventListeners } from './events.js';
import { copyCode, copyMessage, editMessage, retryMessage, retryDuoMessage, downloadCode } from './messages.js';
import { ChatSearchModal } from './search.js';
import { state } from './state.js';

// Expose handlers for inline onclick= attributes
window.copyCode     = copyCode;
window.copyMessage  = copyMessage;
window.editMessage  = editMessage;
window.retryMessage = retryMessage;
window.retryDuoMessage = retryDuoMessage;
window.downloadCode = downloadCode;

async function init() {
  loadTheme();
  fetch('/api/warmup', { method: 'POST' }).catch(() => {});
  const [, , , bootRes] = await Promise.all([loadModels(), loadPersonas(), loadChats(), fetch('/api/boot-id').then(r => r.json())]);
  setupEventListeners();

  const chatSearch = new ChatSearchModal();
  chatSearch.init();

  const storedBootId = sessionStorage.getItem('boot_id');
  sessionStorage.setItem('boot_id', bootRes.id);

  const isBrowserRefresh = storedBootId === bootRes.id;
  if (!isBrowserRefresh) {
    localStorage.removeItem('sidebarCollapsed');
    document.getElementById('sidebar').classList.remove('collapsed');
  } else if (localStorage.getItem('sidebarCollapsed') === '1') {
    document.getElementById('sidebar').classList.add('collapsed');
  }

  if (isBrowserRefresh) {
    const recent = state.chats.slice().sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
    if (recent) {
      await openChat(recent.id);
      return;
    }
  }
  showWelcome();
  setTimeout(() => {
    const wrap = document.querySelector('.tips-wrap');
    if (!wrap) return;
    wrap.classList.add('tips-show');
    setTimeout(() => wrap.classList.remove('tips-show'), 7000);
  }, 6900);
}

init();

// Keep selected model warm (NIM evicts idle serverless models).
// Skips when tab hidden or streaming (model already warm).
setInterval(() => {
  if (document.hidden || state.streaming || !state.selectedModel) return;
  fetch('/api/warmup', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: state.selectedModel }),
  }).catch(() => {});
}, 240000);  // 4 min — just under the server's 230s warmup TTL
