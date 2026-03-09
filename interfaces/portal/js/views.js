// ── Views: unified chat paradigm ──────────────────────────
// Every Deed = Chat Session. One main view with contextual header.

let currentDeedId = null;    // null = new conversation
let currentDeedData = null;  // full deed record when viewing a deed

function showNewChat() {
  clearActive();
  currentDeedId = null;
  currentDeedData = null;
  sessId = null;
  detPlan = null;

  // Hide header + feedback + offering
  document.getElementById('chat-header').classList.add('hidden');
  document.getElementById('plan-card').style.display = 'none';
  document.getElementById('fb-inline').classList.add('hidden');
  document.getElementById('offering-card').classList.add('hidden');

  // Clear messages, show empty state
  document.getElementById('chat-messages').innerHTML = '';
  document.getElementById('chat-empty').style.display = '';

  // Enable input, reset placeholder
  _setChatInputEnabled(true);
  const ta = document.getElementById('compose-textarea');
  ta.placeholder = lang === 'zh' ? ta.dataset.phZh : ta.dataset.phEn;
  ta.value = '';
  ta.style.height = 'auto';
  setTimeout(() => ta.focus(), 50);
}

function showDeedChat(deed, messages) {
  currentDeedId = deed.deed_id;
  currentDeedData = deed;

  const deedStatus = _deedStatus(deed);
  const isRunning = ['running', 'queued', 'cancelling'].includes(deedStatus);
  const isPaused = deedStatus === 'paused';
  const isFailed = deedStatus === 'failed';
  const isAwaiting = deedStatus === 'awaiting_eval' || deedStatus === 'pending_review';
  const isComplete = ['completed', 'done'].includes(deedStatus);
  const isCancelled = deedStatus === 'cancelled';

  // Show header
  const hdr = document.getElementById('chat-header');
  hdr.classList.remove('hidden');
  document.getElementById('ch-title').textContent = deed.deed_title || deed.title || deed.deed_type || deed.deed_id;
  _setChatBadge(deedStatus);
  document.getElementById('ch-time').textContent = relTime(deed.created_utc);

  // §2.1: Endeavor passage progress (e.g. "2/5")
  _loadPassageProgress(deed);

  // Controls
  document.getElementById('btn-resume').style.display = isPaused ? '' : 'none';
  document.getElementById('btn-pause').style.display = isRunning ? '' : 'none';
  document.getElementById('btn-redirect').style.display = isRunning ? '' : 'none';
  document.getElementById('btn-retry').style.display = isFailed ? '' : 'none';
  document.getElementById('btn-cancel').style.display = (isRunning || isPaused) ? '' : 'none';
  const ctrl = document.getElementById('ch-controls');
  ctrl.style.display = (isRunning || isPaused || isFailed) ? '' : 'none';

  // Hide empty state, plan card
  document.getElementById('chat-empty').style.display = 'none';
  document.getElementById('plan-card').style.display = 'none';

  // Render messages
  const container = document.getElementById('chat-messages');
  container.innerHTML = '';

  // Render plan progress component for running/completed deeds
  if (typeof showDeedPlan === 'function') showDeedPlan(deed);

  if (messages && messages.length) {
    messages.forEach(m => _renderMessage(container, m));
  }

  // Offering preview for completed/awaiting deeds
  if (isComplete || isAwaiting || isCancelled) {
    _loadOfferingPreview(deed);
  } else {
    document.getElementById('offering-card').classList.add('hidden');
  }

  // Feedback for awaiting_eval
  if (isAwaiting) {
    showFeedbackInline(deed.deed_id);
  } else {
    document.getElementById('fb-inline').classList.add('hidden');
  }

  // Input state
  const expired = isComplete || isCancelled;
  _setChatInputEnabled(!expired);
  const ta = document.getElementById('compose-textarea');
  if (!expired) {
    ta.placeholder = t('chatPlaceholder');
  }
  ta.value = '';
  ta.style.height = 'auto';

  // Scroll to bottom
  const scroll = document.getElementById('chat-scroll');
  setTimeout(() => { scroll.scrollTop = scroll.scrollHeight; }, 50);
}

// ── Helpers ──────────────────────────────────────────────

function _deedStatus(deed) {
  return String(deed.deed_status || '').toLowerCase();
}

function _setChatBadge(s) {
  const b = document.getElementById('ch-status');
  b.textContent = sLabel(s);
  b.className = 'sbadge s-' + s;
}

function _setChatInputEnabled(enabled) {
  const ta = document.getElementById('compose-textarea');
  const btn = document.getElementById('compose-send-btn');
  ta.disabled = !enabled;
  btn.disabled = !enabled;
  if (!enabled) {
    ta.placeholder = t('fbExpired');
  }
}

// §2.1: "Endeavor 额外显示 Passage 进度（如 '2/5'）"
async function _loadPassageProgress(deed) {
  const el = document.getElementById('ch-passage');
  if (!el) return;
  el.textContent = '';
  const mode = (deed.plan && (deed.plan.work_scale || (deed.plan.brief && deed.plan.brief.complexity))) || '';
  if (mode !== 'endeavor') return;
  try {
    const data = await api('/endeavors/' + encodeURIComponent(deed.deed_id));
    if (data && data.manifest) {
      const cur = (data.manifest.current_passage_index || 0) + 1;
      const total = data.manifest.total_passages || data.manifest.passages.length || 0;
      if (total > 0) el.textContent = cur + '/' + total;
    }
  } catch (_) {}
}

function _renderMessage(container, msg) {
  const role = msg.role || 'system';
  const content = msg.content || '';
  const event = msg.event || '';

  const div = document.createElement('div');

  if (role === 'user') {
    div.className = 'cmsg user';
    div.textContent = content;
  } else if (role === 'assistant') {
    div.className = 'cmsg assistant';
    if (event === 'deed_progress') {
      div.classList.add('progress-msg');
    }
    div.innerHTML = md(content);
    // §1.3: Passage completion messages get 👍/👎 buttons
    if (event === 'passage_completed') {
      _appendPassageFeedback(div, msg);
    }
  } else {
    div.className = 'cmsg system';
    div.textContent = content;
  }

  container.appendChild(div);
  return div;
}

function addChatMsg(role, text, event) {
  document.getElementById('chat-empty').style.display = 'none';
  const container = document.getElementById('chat-messages');
  const msg = { role, content: text, event: event || '' };
  const div = _renderMessage(container, msg);
  // T1/T4: message entering animation
  div.classList.add('entering');
  setTimeout(() => div.classList.remove('entering'), 400);
  div.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return div;
}

// §1.3: Passage-level 👍/👎 feedback (inline, not a separate component)
function _appendPassageFeedback(div, msg) {
  const meta = msg.meta || {};
  const passageIdx = meta.passage_index;
  if (passageIdx == null || !currentDeedId) return;
  const wrap = document.createElement('div');
  wrap.className = 'passage-fb';
  wrap.innerHTML = `<button class="pfb-btn" data-v="up" onclick="_submitPassageFb(this,${passageIdx},true)">\uD83D\uDC4D</button>
    <button class="pfb-btn" data-v="down" onclick="_submitPassageFb(this,${passageIdx},false)">\uD83D\uDC4E</button>`;
  div.appendChild(wrap);
}

async function _submitPassageFb(btn, passageIdx, satisfied) {
  const wrap = btn.parentElement;
  wrap.querySelectorAll('.pfb-btn').forEach(b => { b.disabled = true; b.classList.remove('sel'); });
  btn.classList.add('sel');
  try {
    await api('/endeavors/' + encodeURIComponent(currentDeedId) + '/passages/' + passageIdx + '/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ feedback: { satisfied }, source: 'portal' }),
    });
  } catch (_) {}
}

// ── Offering preview: type-differentiated + bilingual (§1.4) ──

async function _loadOfferingPreview(deed) {
  const card = document.getElementById('offering-card');
  const body = document.getElementById('offering-body');

  let files = [];
  try { files = await api('/offerings/' + encodeURIComponent(deed.deed_id) + '/files'); } catch (_) {}

  if (!files || !files.length) {
    // Legacy fallback
    const match = (typeof offerings !== 'undefined' ? offerings : []).find(o => o.deed_id === deed.deed_id);
    if (match) {
      const path = (match.path || '').replace(/^\/|\/+$/g, '');
      try {
        const hr = await fetch(API + '/offerings/' + path + '/report.html');
        if (hr.ok) {
          body.innerHTML = '';
          const fr = document.createElement('iframe');
          fr.style.cssText = 'width:100%;min-height:480px;border:1px solid var(--border);border-radius:var(--r);display:block;background:white';
          fr.srcdoc = await hr.text();
          body.appendChild(fr);
          card.classList.remove('hidden');
          return;
        }
      } catch (_) {}
    }
    card.classList.add('hidden');
    return;
  }

  body.innerHTML = '';
  const deedLang = _getDeedLanguage(deed);
  const isBilingual = deedLang === 'bilingual';

  if (isBilingual) {
    // §1.4: bilingual side-by-side
    const { pairs, unpaired } = _pairBilingualFiles(files);
    for (const pair of pairs) {
      const row = document.createElement('div');
      row.className = 'offering-bi-row';
      if (pair.zh) row.appendChild(_renderFilePreview(deed.deed_id, pair.zh));
      if (pair.en) row.appendChild(_renderFilePreview(deed.deed_id, pair.en));
      body.appendChild(row);
    }
    unpaired.forEach(f => body.appendChild(_renderFilePreview(deed.deed_id, f)));
  } else {
    // Single language: inline report + file list
    const report = files.find(f => {
      const n = _fname(f);
      return /report\.(html|md)$/i.test(n);
    });
    if (report) await _inlineReport(body, deed.deed_id, report);

    const list = document.createElement('div');
    list.className = 'offering-files';
    files.forEach(f => {
      const name = _fname(f);
      if (!name) return;
      list.appendChild(_renderFileLink(deed.deed_id, f));
    });
    body.appendChild(list);
  }

  // "View full result" link
  const vl = document.createElement('a');
  vl.className = 'offering-view-full';
  vl.textContent = t('viewResult');
  vl.href = '#';
  vl.onclick = (e) => { e.preventDefault(); _expandOfferingFull(deed.deed_id, files); };
  body.appendChild(vl);

  card.classList.remove('hidden');
  // T5: slide up
  card.classList.add('entering');
  setTimeout(() => card.classList.remove('entering'), 400);
}

function _fname(f) {
  return typeof f === 'string' ? f : (f.name || f.filename || '');
}

function _ftype(f) {
  if (typeof f === 'object' && f.preview_type) return f.preview_type;
  const n = _fname(f).toLowerCase();
  if (/\.pdf$/i.test(n)) return 'pdf';
  if (/\.(md|txt|csv)$/i.test(n)) return 'text';
  if (/\.html?$/i.test(n)) return 'html';
  if (/\.(js|ts|py|go|rs|java|c|cpp|sh|sql)$/i.test(n)) return 'code';
  if (/\.(png|jpg|jpeg|gif|svg|webp)$/i.test(n)) return 'image';
  return 'binary';
}

function _fileIcon(type) {
  const m = { pdf: '\uD83D\uDCC4', text: '\uD83D\uDCC3', html: '\uD83C\uDF10', code: '\uD83D\uDCBB', image: '\uD83D\uDDBC\uFE0F', binary: '\uD83D\uDCE6' };
  return m[type] || m.binary;
}

function _getDeedLanguage(deed) {
  const plan = deed.plan || {};
  const brief = plan.brief || {};
  return brief.language || plan.language || '';
}

function _pairBilingualFiles(files) {
  const zhRe = /[（(]中文[）)]/;
  const enRe = /[（(]English[）)]/i;
  const pairs = {};
  const unpaired = [];
  files.forEach(f => {
    const name = _fname(f);
    if (zhRe.test(name) || enRe.test(name)) {
      const base = name.replace(zhRe, '').replace(enRe, '').trim();
      if (!pairs[base]) pairs[base] = {};
      if (zhRe.test(name)) pairs[base].zh = f;
      else pairs[base].en = f;
    } else {
      unpaired.push(f);
    }
  });
  return { pairs: Object.values(pairs), unpaired };
}

// §1.4: type-differentiated preview
function _renderFilePreview(deedId, f) {
  const name = _fname(f);
  const type = _ftype(f);
  const div = document.createElement('div');
  div.className = 'offering-preview of-' + type;

  const url = API + '/offerings/' + encodeURIComponent(deedId) + '/files/' + encodeURIComponent(name);

  if (type === 'text' || type === 'code') {
    // Show first lines as preview
    div.innerHTML = `<div class="of-header"><span class="of-icon">${_fileIcon(type)}</span><a href="${esc(url)}" target="_blank">${esc(name)}</a></div>
      <div class="of-snippet" data-url="${esc(url)}"><span class="of-loading">\u2026</span></div>`;
    _loadSnippet(div.querySelector('.of-snippet'), url, type === 'code');
  } else if (type === 'pdf') {
    div.innerHTML = `<div class="of-header"><span class="of-icon">${_fileIcon(type)}</span><a href="${esc(url)}" target="_blank">${esc(name)}</a></div>
      <div class="of-pdf-placeholder">PDF</div>`;
  } else if (type === 'image') {
    div.innerHTML = `<div class="of-header"><span class="of-icon">${_fileIcon(type)}</span><a href="${esc(url)}" target="_blank">${esc(name)}</a></div>
      <img class="of-img" src="${esc(url)}" alt="${esc(name)}" loading="lazy">`;
  } else if (type === 'html') {
    div.innerHTML = `<div class="of-header"><span class="of-icon">${_fileIcon(type)}</span><a href="${esc(url)}" target="_blank">${esc(name)}</a></div>`;
  } else {
    div.innerHTML = `<div class="of-header"><span class="of-icon">${_fileIcon(type)}</span><a href="${esc(url)}" target="_blank">${esc(name)}</a></div>`;
  }
  return div;
}

async function _loadSnippet(el, url, isCode) {
  try {
    const r = await fetch(url);
    if (!r.ok) { el.textContent = ''; return; }
    const txt = await r.text();
    const lines = txt.split('\n').slice(0, 6).join('\n');
    if (isCode) {
      el.innerHTML = `<pre><code>${esc(lines)}</code></pre>`;
    } else {
      el.textContent = lines + (txt.split('\n').length > 6 ? '\n\u2026' : '');
    }
  } catch (_) { el.textContent = ''; }
}

function _renderFileLink(deedId, f) {
  const name = _fname(f);
  const type = _ftype(f);
  const a = document.createElement('a');
  a.className = 'offering-file';
  a.href = API + '/offerings/' + encodeURIComponent(deedId) + '/files/' + encodeURIComponent(name);
  a.target = '_blank';
  a.innerHTML = `<span class="of-icon">${_fileIcon(type)}</span>${esc(name)}`;
  return a;
}

async function _inlineReport(body, deedId, f) {
  const name = _fname(f);
  const url = API + '/offerings/' + encodeURIComponent(deedId) + '/files/' + encodeURIComponent(name);
  try {
    const r = await fetch(url);
    if (!r.ok) return;
    const txt = await r.text();
    if (name.endsWith('.html')) {
      const fr = document.createElement('iframe');
      fr.style.cssText = 'width:100%;min-height:480px;border:1px solid var(--border);border-radius:var(--r);display:block;background:white';
      fr.srcdoc = txt;
      body.appendChild(fr);
    } else {
      const mdDiv = document.createElement('div');
      mdDiv.className = 'offering-md';
      mdDiv.innerHTML = md(txt);
      body.appendChild(mdDiv);
    }
  } catch (_) {}
}

function _expandOfferingFull(deedId, files) {
  const card = document.getElementById('offering-card');
  const body = document.getElementById('offering-body');
  body.innerHTML = '';
  const list = document.createElement('div');
  list.className = 'offering-files';
  files.forEach(f => {
    list.appendChild(_renderFileLink(deedId, f));
  });
  body.appendChild(list);
  card.classList.remove('hidden');
}

function clearActive() {
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
}
