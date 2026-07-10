import { state } from './state.js';
import { api } from './api.js';
import { openChat, loadChats, confirmDialog, showWelcome } from './chat.js';

export class ChatSearchModal {
  constructor() {
    this.selectionMode = false;
    this.selectedChatIds = new Set();
    this._cachedSortedChats = [];

    // DOM Elements
    this.backdrop = document.getElementById('chatSearchBackdrop');
    this.modalInput = document.getElementById('chatSearchModalInput');
    this.list = document.getElementById('chatSearchList');
    this.normalHeader = document.getElementById('chatSearchNormalHeader');
    this.selectionHeader = document.getElementById('chatSearchSelectionHeader');
    this.selectionCount = document.getElementById('chatSearchSelectionCount');
    this.normalActions = document.getElementById('chatSearchNormalActions');
    this.selectionActions = document.getElementById('chatSearchSelectionActions');
    this.closeBtn = document.getElementById('chatSearchCloseBtn');
    this.selectionCloseBtn = document.getElementById('chatSearchSelectionCloseBtn');
    this.selectBtn = document.getElementById('chatSearchSelectBtn');
    this.newBtn = document.getElementById('chatSearchNewBtn');
    this.selectAllBtn = document.getElementById('chatSearchSelectAllBtn');
    this.starBtn = document.getElementById('chatSearchStarBtn');
    this.deleteBtn = document.getElementById('chatSearchDeleteBtn');
    this.cancelBtn = document.getElementById('chatSearchCancelBtn');

    // Trigger Elements (external buttons that open the modal)
    this.searchChatBtn = document.getElementById('searchChatBtn');
    this.collapsedSearchBtn = document.getElementById('collapsedSearchBtn');
  }

  init() {
    this.bindEvents();
  }

  bindEvents() {
    // Open triggers
    if (this.searchChatBtn) this.searchChatBtn.addEventListener('click', () => this.open());
    if (this.collapsedSearchBtn) this.collapsedSearchBtn.addEventListener('click', () => this.open());

    // Close triggers
    this.closeBtn.addEventListener('click', () => this.close());
    this.selectionCloseBtn.addEventListener('click', () => this.close());
    this.backdrop.addEventListener('click', (e) => {
      if (e.target === this.backdrop) this.close();
    });

    // Input & Actions
    this.modalInput.addEventListener('input', () => this.render());

    this.selectBtn.addEventListener('click', () => {
      this.selectionMode = true;
      this.render();
    });

    this.newBtn.addEventListener('click', () => {
      this.close();
      showWelcome();
    });

    this.cancelBtn.addEventListener('click', () => {
      this.selectionMode = false;
      this.selectedChatIds.clear();
      this.render();
    });

    this.selectAllBtn.addEventListener('click', () => this.handleSelectAll());
    this.starBtn.addEventListener('click', () => this.handleStarSelected());
    this.deleteBtn.addEventListener('click', () => this.handleDeleteSelected());
  }

  open() {
    this.backdrop.style.display = '';
    this.modalInput.value = '';
    this.selectionMode = false;
    this.selectedChatIds.clear();
    this._cachedSortedChats = [...state.chats].sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
    this.render();
    this.modalInput.focus();
  }

  close() {
    this.backdrop.style.display = 'none';
    this.selectionMode = false;
    this.selectedChatIds.clear();
  }

  formatRelativeDate(isoString) {
    const date = new Date(isoString);
    const now = new Date();
    const diff = (now - date) / 1000;
    
    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    
    const options = { month: 'short', day: 'numeric' };
    if (date.getFullYear() !== now.getFullYear()) {
      options.year = 'numeric';
    }
    return date.toLocaleDateString('en-US', options);
  }

  render() {
    if (this.selectionMode) {
      this.normalHeader.style.display = 'none';
      this.selectionHeader.style.display = 'flex';
      this.normalActions.style.display = 'none';
      this.selectionActions.style.display = 'flex';
      this.selectionCount.textContent = `${this.selectedChatIds.size} chat(s) selected`;
      
      const hasSelection = this.selectedChatIds.size > 0;
      this.starBtn.disabled = !hasSelection;
      this.deleteBtn.disabled = !hasSelection;
    } else {
      this.normalHeader.style.display = 'flex';
      this.selectionHeader.style.display = 'none';
      this.normalActions.style.display = 'flex';
      this.selectionActions.style.display = 'none';
    }

    const query = (this.modalInput.value || '').toLowerCase();
    const visibleChats = this._cachedSortedChats.filter(c => c.title.toLowerCase().includes(query));

    this.list.innerHTML = '';

    if (visibleChats.length === 0) {
      const emptyMsg = document.createElement('div');
      emptyMsg.style.flex = '1';
      emptyMsg.style.display = 'flex';
      emptyMsg.style.alignItems = 'center';
      emptyMsg.style.justifyContent = 'center';
      emptyMsg.style.color = 'var(--text)';
      emptyMsg.style.fontSize = '16px';
      emptyMsg.style.fontWeight = '1000';
      emptyMsg.textContent = state.chats.length === 0 ? "You don't have any chats yet." : "No chats match your search.";
      this.list.appendChild(emptyMsg);
      return;
    }

    visibleChats.forEach(chat => {
      const el = document.createElement('div');
      el.className = 'chat-search-item' + (this.selectedChatIds.has(chat.id) ? ' selected' : '');

      const leftWrap = document.createElement('div');
      leftWrap.className = 'chat-search-item-left';

      if (this.selectionMode) {
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'chat-select-checkbox';
        checkbox.checked = this.selectedChatIds.has(chat.id);
        checkbox.addEventListener('click', (e) => e.stopPropagation());
        checkbox.addEventListener('change', () => {
          if (checkbox.checked) {
            this.selectedChatIds.add(chat.id);
          } else {
            this.selectedChatIds.delete(chat.id);
          }
          this.render();
        });
        leftWrap.appendChild(checkbox);
      } else {
        const iconWrap = document.createElement('div');
        iconWrap.style.display = 'flex';
        iconWrap.style.alignItems = 'center';
        iconWrap.style.justifyContent = 'center';
        iconWrap.style.color = 'var(--text-sub)';
        iconWrap.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>`;
        leftWrap.appendChild(iconWrap);
      }

      const titleWrap = document.createElement('div');
      titleWrap.style.display = 'flex';
      titleWrap.style.alignItems = 'center';
      titleWrap.style.gap = '8px';
      titleWrap.style.minWidth = '0';

      const titleEl = document.createElement('div');
      titleEl.className = 'chat-search-item-title';
      titleEl.textContent = chat.title;
      titleWrap.appendChild(titleEl);

      if (chat.starred) {
        const starIcon = document.createElement('div');
        starIcon.style.display = 'flex';
        starIcon.style.alignItems = 'center';
        starIcon.style.color = '#f5a623';
        starIcon.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>`;
        titleWrap.appendChild(starIcon);
      }

      leftWrap.appendChild(titleWrap);

      const dateEl = document.createElement('div');
      dateEl.className = 'chat-search-item-date';
      dateEl.textContent = this.formatRelativeDate(chat.updated_at);

      el.appendChild(leftWrap);
      el.appendChild(dateEl);

      el.addEventListener('click', () => {
        if (this.selectionMode) {
          const checkbox = el.querySelector('.chat-select-checkbox');
          if (checkbox) {
            checkbox.checked = !checkbox.checked;
            checkbox.dispatchEvent(new Event('change'));
          }
        } else {
          this.close();
          openChat(chat.id);
        }
      });

      this.list.appendChild(el);
    });
  }

  handleSelectAll() {
    const query = (this.modalInput.value || '').toLowerCase();
    const visibleChats = state.chats.filter(c => c.title.toLowerCase().includes(query));
    
    if (this.selectedChatIds.size === visibleChats.length && visibleChats.length > 0) {
      this.selectedChatIds.clear();
    } else {
      visibleChats.forEach(c => this.selectedChatIds.add(c.id));
    }
    this.render();
  }

  async handleDeleteSelected() {
    if (this.selectedChatIds.size === 0) return;
    const ids = Array.from(this.selectedChatIds);
    if (!await confirmDialog(`Delete ${ids.length} selected chat(s)?`, 'Delete', 'btn-danger')) return;
    
    await Promise.all(ids.map(id => api(`/chats/${id}`, { method: 'DELETE' })));

    if (ids.includes(state.activeChatId)) {
      this.close();
      showWelcome();
    }

    this.selectionMode = false;
    this.selectedChatIds.clear();
    await loadChats();
    this.render();
  }

  async handleStarSelected() {
    if (this.selectedChatIds.size === 0) return;
    const ids = Array.from(this.selectedChatIds);
    
    let anyUnstarred = false;
    for (const id of ids) {
      const chat = state.chats.find(c => c.id === id);
      if (chat && !chat.starred) anyUnstarred = true;
    }
    
    const actionText = anyUnstarred ? 'Star' : 'Unstar';
    if (!await confirmDialog(`${actionText} ${ids.length} selected chat(s)?`, actionText, 'btn-warning')) return;
    
    await Promise.all(ids.map(id => api(`/chats/${id}`, { method: 'PATCH', body: { starred: anyUnstarred } })));
    this.selectionMode = false;
    this.selectedChatIds.clear();
    await loadChats();
    this.render();
  }
}
