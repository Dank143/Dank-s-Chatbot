// Shared SVG icons + action-button markup. No imports — cycle-safe.

export const ICON = {
  copy: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <rect x="9" y="9" width="13" height="13" rx="2"/>
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
  </svg>`,
  retry: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M1 4v6h6"/><path d="M3.51 15a9 9 0 1 0 .49-4.5"/>
  </svg>`,
  edit: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
  </svg>`,
};

// Copy + Retry actions shown under a finished assistant message.
export function getAssistantActions(ttfsMs = null, totalMs = null) {
  let timingHtml = '';
  if (ttfsMs !== null && totalMs !== null) {
    timingHtml = `<span class="gen-timing">TTFS ${(ttfsMs/1000).toFixed(1)}s &middot; Total ${(totalMs/1000).toFixed(1)}s</span>`;
  }
  return `
  <div class="message-actions">
    <button class="msg-action-btn" title="Copy" onclick="copyMessage(this)">${ICON.copy}</button>
    <button class="msg-action-btn" title="Retry" onclick="retryMessage(this)">${ICON.retry}</button>
    ${timingHtml}
  </div>`;
}
