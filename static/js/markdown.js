import { escHtml } from './state.js';

marked.setOptions({ breaks: true, gfm: true });

let _highlight = true;
export function setHighlight(on) { _highlight = on; }


const renderer = new marked.Renderer();

renderer.code = (token) => {
  const code = typeof token === 'object' ? (token.text || '') : token;
  const lang = typeof token === 'object' ? (token.lang || '') : (arguments[1] || '');
  const highlighted = _highlight
    ? (lang && hljs.getLanguage(lang)
        ? hljs.highlight(code, { language: lang }).value
        : hljs.highlightAuto(code).value)
    : escHtml(code);
  const langLabel = lang || 'code';
  return `
<div class="code-block-wrap">
  <div class="code-block-header">
    <span class="code-lang">${langLabel}</span>
    <div class="code-header-actions">
      <button class="copy-code-btn" onclick="copyCode(this)">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="9" y="9" width="13" height="13" rx="2"/>
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
        </svg>
        Copy
      </button>
      <button class="copy-code-btn" onclick="downloadCode(this)">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        Download
      </button>
    </div>
  </div>
  <pre><code class="hljs language-${langLabel}">${highlighted}</code></pre>
</div>`;
};

renderer.link = (token) => {
  const href  = typeof token === 'object' ? token.href  : token;
  const title = typeof token === 'object' ? token.title : arguments[2];
  const text  = typeof token === 'object' ? token.text  : arguments[1];
  const t = title ? ` title="${title}"` : '';
  return `<a href="${href}" target="_blank" rel="noopener noreferrer"${t}>${text}</a>`;
};

marked.use({ renderer });

function _mathBlockRenderer(t) {
  try { return '<div class="math-block">' + katex.renderToString(t.text, { displayMode: true, throwOnError: false }) + '</div>'; }
  catch { return `<div class="math-block">${t.text}</div>`; }
}
function _mathInlineRenderer(t) {
  try { return '<span class="math-inline">' + katex.renderToString(t.text, { throwOnError: false }) + '</span>'; }
  catch { return `<span class="math-inline">${t.text}</span>`; }
}

marked.use({
  extensions: [
    {
      name: 'blockMath',
      level: 'block',
      start(src) { return Math.min(...['$$', '\\['].map(d => { const i = src.indexOf(d); return i === -1 ? Infinity : i; })); },
      tokenizer(src) {
        const m = src.match(/^\$\$([\s\S]+?)\$\$/) || src.match(/^\\\[([\s\S]+?)\\\]/);
        if (m) return { type: 'blockMath', raw: m[0], text: m[1].trim() };
      },
      renderer: _mathBlockRenderer,
    },
    {
      name: 'inlineMath',
      level: 'inline',
      start(src) { return Math.min(...['$', '\\('].map(d => { const i = src.indexOf(d); return i === -1 ? Infinity : i; })); },
      tokenizer(src) {
        const m = src.match(/^\$([^\$\n]+?)\$/) || src.match(/^\\\(([^\n]+?)\\\)/);
        if (m) return { type: 'inlineMath', raw: m[0], text: m[1].trim() };
      },
      renderer: _mathInlineRenderer,
    },
  ],
});

export function renderMarkdown(text) { return marked.parse(text || ''); }
