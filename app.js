const MAX_FILE_SIZE = 100 * 1024 * 1024;

const createView = document.getElementById('createView');
const viewView = document.getElementById('viewView');
const notFound = document.getElementById('notFound');
const subtitle = document.getElementById('subtitle');

const textArea = document.getElementById('textArea');
const charCount = document.getElementById('charCount');
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const pendingList = document.getElementById('pendingList');
const btnCreate = document.getElementById('btnCreate');
const resultBox = document.getElementById('resultBox');
const resultUrl = document.getElementById('resultUrl');
const btnCopyLink = document.getElementById('btnCopyLink');

const viewText = document.getElementById('viewText');
const btnCopyText = document.getElementById('btnCopyText');
const viewFileList = document.getElementById('viewFileList');
const viewFileCount = document.getElementById('viewFileCount');
const btnClear = document.getElementById('btnClear');

const toastEl = document.getElementById('toast');

let pendingFiles = [];
let currentCode = null;

/* ---------------- 工具 ---------------- */

let toastTimer = null;
function showToast(msg, isError) {
  toastEl.textContent = msg;
  toastEl.className = 'toast show' + (isError ? ' error' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.className = 'toast'; }, 2600);
}

function formatSize(bytes) {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const v = bytes / Math.pow(1024, i);
  return (i === 0 ? v : v.toFixed(1)) + ' ' + units[i];
}

function formatTime(s) {
  const d = new Date(s);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit'
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function isImage(name) {
  return /\.(png|jpe?g|gif|webp|svg|bmp|avif|ico)$/i.test(name);
}

function extOf(name) {
  const m = name.match(/\.([^.]+)$/);
  return m ? m[1].toUpperCase().slice(0, 5) : '';
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
  }
}

function fileUrl(name) {
  return location.origin + '/api/' + currentCode + '/files/' + encodeURIComponent(name);
}

function getCodeFromPath() {
  const m = location.pathname.match(/^\/([a-z0-9]{2})\/?$/);
  return m ? m[1] : null;
}

/* ---------------- 视图切换 ---------------- */

function showCreate() {
  createView.hidden = false;
  viewView.hidden = true;
  notFound.hidden = true;
  subtitle.textContent = '跨设备复制粘贴 · 文本 / 图片 / 文件';
}

function showViewMode() {
  createView.hidden = true;
  viewView.hidden = false;
  notFound.hidden = true;
  subtitle.textContent = '查看剪贴板 · 只读';
}

function showNotFound() {
  createView.hidden = true;
  viewView.hidden = true;
  notFound.hidden = false;
  subtitle.textContent = '链接不存在或已过期';
}

/* ---------------- 创建页 ---------------- */

function updateCount() {
  charCount.textContent = textArea.value.length.toLocaleString() + ' 字';
}

function addFiles(files) {
  for (const f of Array.from(files)) {
    if (f.size > MAX_FILE_SIZE) {
      showToast('「' + f.name + '」超过 100MB，已跳过', true);
      continue;
    }
    pendingFiles.push(f);
  }
  renderPending();
}

function renderPending() {
  if (!pendingFiles.length) {
    pendingList.innerHTML = '<li class="empty">尚未添加文件（可选）</li>';
    return;
  }
  pendingList.innerHTML = pendingFiles.map((f, i) =>
    '<li class="file-item">' +
      '<div class="thumb generic"><span>' + escapeHtml(extOf(f.name) || 'FILE') + '</span></div>' +
      '<div class="info">' +
        '<span class="name">' + escapeHtml(f.name) + '</span>' +
        '<div class="meta">' + formatSize(f.size) + '</div>' +
      '</div>' +
      '<div class="actions"><button class="btn sm danger" data-remove="' + i + '">移除</button></div>' +
    '</li>'
  ).join('');
}

function setCreateBusy(busy) {
  btnCreate.disabled = busy;
  btnCreate.textContent = busy ? '创建中…' : '创建剪贴板';
}

async function create() {
  const text = textArea.value;
  if (!text && !pendingFiles.length) {
    showToast('请先输入文本或添加文件', true);
    return;
  }
  setCreateBusy(true);
  try {
    const r = await fetch('/api/new', { method: 'POST' });
    if (!r.ok) throw new Error('创建失败');
    const code = (await r.json()).code;
    if (text) {
      const tr = await fetch('/api/' + code + '/text', { method: 'PUT', body: text });
      if (!tr.ok) throw new Error('文本上传失败');
    }
    for (const f of pendingFiles) {
      const fr = await fetch('/api/' + code + '/files/' + encodeURIComponent(f.name), { method: 'PUT', body: f });
      if (!fr.ok) throw new Error('「' + f.name + '」上传失败');
    }
    const url = location.origin + '/' + code;
    resultUrl.textContent = url;
    resultUrl.href = url;
    resultBox.hidden = false;
    await copyToClipboard(url);
    showToast('创建成功，链接已复制');
    resultBox.scrollIntoView({ behavior: 'smooth' });
  } catch (e) {
    showToast(e.message || '创建失败', true);
  } finally {
    setCreateBusy(false);
  }
}

/* ---------------- 查看页 ---------------- */

async function loadView(code) {
  currentCode = code;
  showViewMode();
  try {
    const r = await fetch('/api/' + code);
    if (!r.ok) return showNotFound();
    const data = await r.json();
    viewText.textContent = data.text || '';
    renderViewFiles(data.files || []);
  } catch (e) {
    showNotFound();
  }
}

function renderViewFiles(files) {
  viewFileCount.textContent = files.length ? files.length + ' 个文件' : '';
  if (!files.length) {
    viewFileList.innerHTML = '<li class="empty">暂无文件</li>';
    return;
  }
  viewFileList.innerHTML = files.map(f => {
    const name = escapeHtml(f.name);
    const url = fileUrl(f.name);
    const thumb = isImage(f.name)
      ? '<img src="' + url + '" loading="lazy" alt="">'
      : '<span>' + escapeHtml(extOf(f.name) || 'FILE') + '</span>';
    return '<li class="file-item">' +
      '<div class="thumb' + (isImage(f.name) ? '' : ' generic') + '">' + thumb + '</div>' +
      '<div class="info">' +
        '<a class="name" href="' + url + '" target="_blank" rel="noopener">' + name + '</a>' +
        '<div class="meta">' + formatSize(f.size) + ' · ' + formatTime(f.mtime) + '</div>' +
      '</div>' +
      '<div class="actions">' +
        '<button class="btn sm" data-action="copy" data-name="' + name + '">复制链接</button>' +
        '<button class="btn sm" data-action="download" data-name="' + name + '">下载</button>' +
      '</div>' +
    '</li>';
  }).join('');
}

function downloadFile(name) {
  const a = document.createElement('a');
  a.href = fileUrl(name);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function clearClip() {
  if (!confirm('清空后将无法恢复，确定？')) return;
  try {
    const r = await fetch('/api/' + currentCode, { method: 'DELETE' });
    if (r.ok) {
      showToast('已清空');
      location.href = '/';
    } else {
      showToast('清空失败', true);
    }
  } catch (e) {
    showToast('清空失败', true);
  }
}

/* ---------------- 事件绑定 ---------------- */

btnCreate.addEventListener('click', create);
btnCopyLink.addEventListener('click', async () => {
  await copyToClipboard(resultUrl.textContent);
  showToast('链接已复制');
});
btnCopyText.addEventListener('click', async () => {
  if (viewText.textContent) {
    await copyToClipboard(viewText.textContent);
    showToast('已复制到剪贴板');
  }
});
btnClear.addEventListener('click', clearClip);

textArea.addEventListener('input', updateCount);

dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('over'));
dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.classList.remove('over');
  if (e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
});
fileInput.addEventListener('change', () => { addFiles(fileInput.files); fileInput.value = ''; });

pendingList.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-remove]');
  if (!btn) return;
  pendingFiles.splice(Number(btn.dataset.remove), 1);
  renderPending();
});

viewFileList.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const name = btn.dataset.name;
  if (btn.dataset.action === 'copy') {
    copyToClipboard(fileUrl(name));
    showToast('链接已复制');
  } else if (btn.dataset.action === 'download') {
    downloadFile(name);
  }
});

document.addEventListener('paste', (e) => {
  if (createView.hidden) return;
  const items = e.clipboardData && e.clipboardData.items;
  if (!items) return;
  const files = [];
  for (const it of items) {
    if (it.kind === 'file') {
      const f = it.getAsFile();
      if (f) files.push(f);
    }
  }
  if (files.length) {
    e.preventDefault();
    addFiles(files);
  }
});

/* ---------------- 初始化 ---------------- */

renderPending();
const code = getCodeFromPath();
if (code) loadView(code);
else showCreate();
