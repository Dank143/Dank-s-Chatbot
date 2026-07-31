import { state, $, updateSendBtn } from './state.js';

export const DOC_ICON = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`;

export const _docStore = new Map();
let _docKey = 0;
export function nextDocKey() { return _docKey++; }

export function openDocViewer(name, text) {
  $('docViewerName').textContent = name;
  $('docViewerContent').textContent = text;
  $('docViewerBackdrop').style.display = 'flex';
}
export function closeDocViewer() {
  $('docViewerBackdrop').style.display = 'none';
}

function readFile(file, method) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.onerror = rej;
    r[method](file);
  });
}

export const readFileAsDataUrl = (file) => readFile(file, 'readAsDataURL');
export const readFileAsText = (file) => readFile(file, 'readAsText');

const TEXT_EXTENSIONS = new Set([
  'txt','md','markdown','csv','tsv','log','sql','xml','html','htm','css',
  'yaml','yml','json','toml','ini','env','cfg','conf',
  'py','pyw','js','mjs','cjs','ts','jsx','tsx','vue','svelte',
  'c','h','cpp','cc','cxx','hpp','java','kt','kts','scala','groovy',
  'cs','vb','go','rs','swift','rb','php','r',
  'sh','bash','zsh','fish','ps1','bat','cmd',
]);

export function isImageFile(file) { return file.type.startsWith('image/'); }
export function isTextFile(file) {
  return TEXT_EXTENSIONS.has(file.name.split('.').pop().toLowerCase());
}

export function renderPendingFiles() {
  const previews = $('attachmentPreviews');
  previews.innerHTML = '';
  state.pendingFiles.forEach((f, i) => {
    const rm = document.createElement('button');
    rm.className = 'attachment-remove';
    rm.title = 'Remove';
    rm.textContent = '×';
    rm.onclick = () => { state.pendingFiles.splice(i, 1); renderPendingFiles(); updateSendBtn(); };

    if (f.kind === 'image') {
      const div = document.createElement('div');
      div.className = 'attachment-thumb';
      const img = document.createElement('img');
      img.src = f.dataUrl;
      img.alt = f.name;
      img.title = 'Click to view';
      div.appendChild(img);
      div.appendChild(rm);
      previews.appendChild(div);
    } else {
      const div = document.createElement('div');
      div.className = 'attachment-doc' + (f.text ? ' viewable' : '');
      div.innerHTML = DOC_ICON;
      const span = document.createElement('span');
      span.className = 'attachment-doc-name';
      span.textContent = f.name;
      div.appendChild(span);
      div.appendChild(rm);
      if (f.text) {
        div.title = 'Click to view';
        div.addEventListener('click', (e) => {
          if (!e.target.closest('.attachment-remove')) openDocViewer(f.name, f.text);
        });
      }
      previews.appendChild(div);
    }
  });
  updateSendBtn();
}

export function clearPendingFiles() {
  state.pendingFiles = [];
  $('attachmentPreviews').innerHTML = '';
}
