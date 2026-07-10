import { state, escHtml, scrollToBottom, chatTitleDisplay } from './state.js';
import { renderMarkdown, setHighlight } from './markdown.js';
import { finalizeStreamingMessage, showMessageError, showTruncationNotice, showStoppedNotice, searchIndicatorHtml, thinkingIndicator } from './messages.js';

export function getSearchPanelHtml(evt) {
  const methodIcon = (m) => m === 'failed' ? '✗' : '✓';
  const methodClass = (m) => m === 'failed' ? 'debug-src-fail' : m === 'snippet' ? 'debug-src-snippet' : 'debug-src-ok';
  const sourcesHtml = (evt.sources || []).map(s => `
    <div class="debug-source ${methodClass(s.method)}">
      <span class="debug-src-icon">${methodIcon(s.method)}</span>
      <span class="debug-src-method">${escHtml(s.method)}</span>
      <span class="debug-src-score">${s.score ? s.score.toFixed(3) : '—'}</span>
      <span class="debug-src-chars">${s.chars > 0 ? s.chars + ' chars' : '—'}</span>
      <a class="debug-src-url" href="${escHtml(s.url)}" target="_blank" rel="noopener noreferrer">${escHtml(s.url)}</a>
    </div>`).join('');

  return `
    <div class="search-debug-panel">
      <div class="debug-header" onclick="this.parentElement.classList.toggle('expanded')">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
        <span>Search status:</span>
        <span class="debug-got-ctx ${evt.got_context ? 'ok' : 'fail'}">${evt.got_context ? 'context injected' : 'no context'}</span>
        <span class="debug-chevron">▸</span>
      </div>
      <div class="debug-body">
        <div class="debug-row"><span class="debug-key">Query</span><span class="debug-val">${escHtml(evt.query || '—')}</span></div>
        <div class="debug-row"><span class="debug-key">Engine</span><span class="debug-val">${escHtml(evt.engine || '—')}</span></div>
        <div class="debug-row"><span class="debug-key">Rerank</span><span class="debug-val ${evt.rerank === 'embed' ? '' : 'warn'}">${evt.rerank === 'embed' ? 'Score (higher = more relevant)' : 'keyword'}${evt.degraded ? ' · ' + escHtml(evt.degraded) : ''}</span></div>
        <div class="debug-sources">${sourcesHtml || '<div class="debug-source debug-src-fail"><span class="debug-src-icon">✗</span><span>No URLs found</span></div>'}</div>
      </div>
    </div>`;
}

function renderDebugPanel(wrapper, evt) {
  const body = wrapper.querySelector('.message-body') || wrapper;
  body.insertAdjacentHTML('beforeend', getSearchPanelHtml(evt));
}

// Stream SSE reply into assistant bubble: parse events, throttle markdown, handle abort.
export async function streamAssistant(endpoint, body, userWrapper, assistantWrapper, onMeta = null) {
  if (!state.abortController) state.abortController = new AbortController();
  const signal = state.abortController.signal;
  // Track raw text and finalization state for abort/error handling.
  let raw = '';
  let thinkRaw = '';
  let finished = false;
  let finalized = false;
  let streamFinished = false;
  let thinkStartTime = null;
  let t0 = performance.now();
  let ttfsMs = null;
  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Server error');
    }

    const reader = res.body.getReader();
    const abortPromise = new Promise((_, rej) =>
      signal.addEventListener('abort', () => {
        reader.cancel();
        rej(Object.assign(new DOMException('Aborted', 'AbortError')));
      }, { once: true })
    );

    setHighlight(false);
    const decoder = new TextDecoder();
    let buf = '';
    const streamBubble = assistantWrapper.querySelector('.bubble');
    let thinkRenderScheduled = false, lastThinkRender = 0;
    let deltaRenderScheduled = false, lastDeltaRender = 0;
    const RENDER_INTERVAL = 200;  // ms between re-parses; final full render at 'done'

    while (!finished) {
      const { done: streamDone, value } = await Promise.race([reader.read(), abortPromise]);
      if (streamDone) {
        // Drain any data buffered in the final chunk before exiting.
        if (buf.trim()) {
          for (const line of buf.split('\n')) {
            if (!line.startsWith('data: ')) continue;
            try {
              const evt = JSON.parse(line.slice(6));
              if (evt.type === 'error') { showMessageError(assistantWrapper, evt.message, ttfsMs, performance.now() - t0); finalized = true; }
              else if (evt.type === 'done') { setHighlight(true); finalizeStreamingMessage(assistantWrapper, ttfsMs, performance.now() - t0); finalized = true; }
            } catch {
              // ignore
            }
          }
          buf = '';
        }
        break;
      }
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const evt = JSON.parse(line.slice(6));
        if (evt.type === 'meta') {
          if (userWrapper && evt.user_msg_id) userWrapper.dataset.msgId = evt.user_msg_id;
          if (onMeta) onMeta(evt.user_msg_id);
        } else if (evt.type === 'searching') {
          if (streamBubble) {
            streamBubble.querySelector('.thinking-indicator')?.remove();
            let ind = streamBubble.querySelector('.search-indicator');
            if (!ind) { ind = document.createElement('div'); ind.className = 'search-indicator'; streamBubble.prepend(ind); }
            ind.innerHTML = searchIndicatorHtml(evt.query);
          }
        } else if (evt.type === 'search_debug') {
          renderDebugPanel(assistantWrapper, evt);
          if (streamBubble) {
            streamBubble.querySelector('.search-indicator')?.remove();
            streamBubble.querySelector('.thinking-indicator')?.remove();
            streamBubble.insertAdjacentHTML('afterbegin', thinkingIndicator());
          }
        } else if (evt.type === 'title') {
          chatTitleDisplay.textContent = evt.title;
          const chat = state.chats.find(c => c.id === state.activeChatId);
          if (chat) chat.title = evt.title;
        } else if (evt.type === 'thinking') {
          if (ttfsMs === null) ttfsMs = performance.now() - t0;
          streamBubble?.querySelector('.search-indicator')?.remove();
          streamBubble?.querySelector('.thinking-indicator')?.remove();
          if (!thinkStartTime) thinkStartTime = performance.now();
          thinkRaw += evt.content;
          if (streamBubble) {
            let block = assistantWrapper.querySelector('.think-block');
            if (!block) {
              block = document.createElement('div');
              block.className = 'think-block streaming expanded';
              block.innerHTML = `
                <div class="think-toggle">
                  <svg class="think-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
                  <span class="think-label">Thinking<span class="thinking-dots"></span></span>
                </div>
                <div class="think-content"></div>`;
              streamBubble.parentNode.insertBefore(block, streamBubble);
              
              const toggle = block.querySelector('.think-toggle');
              toggle.dataset.bound = '1';
              toggle.addEventListener('click', () => block.classList.toggle('expanded'));
            }
            block.dataset.think = thinkRaw;
            
            // Throttle markdown re-parsing for the thinking block.
            if (!thinkRenderScheduled) {
              thinkRenderScheduled = true;
              const delay = Math.max(0, RENDER_INTERVAL - (performance.now() - lastThinkRender));
              setTimeout(() => {
                requestAnimationFrame(() => {
                  thinkRenderScheduled = false;
                  lastThinkRender = performance.now();
                  if (!streamFinished) {
                    const activeBlock = assistantWrapper.querySelector('.think-block.streaming .think-content');
                    if (activeBlock) {
                      activeBlock.innerHTML = renderMarkdown(thinkRaw);
                      if (state.autoScroll) scrollToBottom();
                    }
                  }
                });
              }, delay);
            }
          }
        } else if (evt.type === 'thinking_done') {
          const block = assistantWrapper.querySelector('.think-block');
          if (block) {
            block.classList.remove('streaming');
            block.classList.remove('expanded'); // Collapse when thinking finishes
            const secs = evt.duration !== undefined ? evt.duration : Math.round((performance.now() - (thinkStartTime || performance.now())) / 1000);
            const label = block.querySelector('.think-label');
            if (label) label.textContent = `Thought for ${secs}s`;
            // Render thinking content as markdown
            const content = block.querySelector('.think-content');
            if (content) content.innerHTML = renderMarkdown(thinkRaw);
          }
        } else if (evt.type === 'delta') {
          if (ttfsMs === null) ttfsMs = performance.now() - t0;
          streamBubble?.querySelector('.search-indicator')?.remove();
          streamBubble?.querySelector('.thinking-indicator')?.remove();
          raw += evt.content;
          if (streamBubble) {
            streamBubble.dataset.raw = raw;
            // Throttle markdown re-parsing to avoid O(n²) on long replies.
            if (!deltaRenderScheduled) {
              deltaRenderScheduled = true;
              const delay = Math.max(0, RENDER_INTERVAL - (performance.now() - lastDeltaRender));
              setTimeout(() => {
                requestAnimationFrame(() => {
                  deltaRenderScheduled = false;
                  lastDeltaRender = performance.now();
                  if (!streamFinished) {
                    streamBubble.innerHTML = renderMarkdown(streamBubble.dataset.raw) + '<span class="streaming-cursor"></span>';
                    if (state.autoScroll) scrollToBottom();
                  }
                });
              }, delay);
            }
          }
        } else if (evt.type === 'done') {
          if (evt.asst_msg_id) assistantWrapper.dataset.msgId = evt.asst_msg_id;
          streamFinished = true;
          setHighlight(true);
          const finalTtfs = evt.ttfs_ms !== undefined ? evt.ttfs_ms : ttfsMs;
          const finalTotal = evt.total_ms !== undefined ? evt.total_ms : (performance.now() - t0);
          finalizeStreamingMessage(assistantWrapper, finalTtfs, finalTotal);
          finalized = true;
          if (evt.finish_reason === 'length') showTruncationNotice(assistantWrapper);
          // Keep reading after 'done' — title event may follow.
        } else if (evt.type === 'error') {
          streamFinished = true;
          showMessageError(assistantWrapper, evt.message, ttfsMs, performance.now() - t0);
          finished = true;
          finalized = true;
          break;
        }
      }
    }

    if (!finalized) {
      streamFinished = true;
      setHighlight(true);
      const rawSoFar = assistantWrapper.querySelector('.bubble')?.dataset.raw || '';
      if (signal.aborted) {
        // User pressed stop — not an error
        if (rawSoFar.trim() || thinkRaw.trim()) {
          // Finalize any in-progress thinking block
          const block = assistantWrapper.querySelector('.think-block.streaming');
          if (block) {
            block.classList.remove('streaming');
            block.classList.remove('expanded');
            const secs = thinkStartTime ? Math.round((performance.now() - thinkStartTime) / 1000) : 0;
            const label = block.querySelector('.think-label');
            if (label) label.textContent = `Thought for ${secs}s`;
            const content = block.querySelector('.think-content');
            if (content) content.innerHTML = renderMarkdown(thinkRaw);
          }
        }
        finalizeStreamingMessage(assistantWrapper, ttfsMs, performance.now() - t0);
        showStoppedNotice(assistantWrapper);
      } else if (!rawSoFar.trim()) {
        showMessageError(assistantWrapper, 'Model returned an empty response. Try again or switch models.', ttfsMs, performance.now() - t0);
      } else {
        finalizeStreamingMessage(assistantWrapper, ttfsMs, performance.now() - t0);
      }
    }

  } catch (err) {
    if (err.name === 'AbortError') {
      // Only finalize if message hadn't already finished.
      if (!finalized) {
        setHighlight(true);
        finalizeStreamingMessage(assistantWrapper, ttfsMs, performance.now() - t0);
        showStoppedNotice(assistantWrapper);
      }
    } else {
      showMessageError(assistantWrapper, err.message, ttfsMs, performance.now() - t0);
    }
  }
}
