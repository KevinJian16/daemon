const API = '';
let cLang = 'zh';
const SHARED_LANG_KEY = 'd_lang';
const LEGACY_KEY = 'c_lang';
const VIEW_STATE_KEY = 'd_console_view_state';
const PANELS = {};
let _currentPanel = '';
let _detailOpen = false;
let _detailContext = null;

// ── Utility ──
function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function tx(zh, en) { return cLang === 'zh' ? zh : en; }
function humanize(s) { return String(s || '').replace(/_/g, ' ').replace(/\b[a-z]/g, c => c.toUpperCase()); }
function fmtTime(utcStr) {
  if (!utcStr) return '\u2014';
  const d = new Date(utcStr);
  if (isNaN(d)) return String(utcStr).replace('T', ' ').replace('Z', '');
  return d.toLocaleString([], { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// ── API ──
async function api(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}
async function apiWrite(path, method, body) {
  const hasBody = body !== null && body !== undefined;
  const r = await fetch(API + path, {
    method,
    headers: hasBody ? { 'Content-Type': 'application/json' } : {},
    body: hasBody ? JSON.stringify(body) : undefined,
  });
  const text = await r.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch (_) { data = { detail: text || r.status }; }
  if (!r.ok) throw new Error(data.error || data.detail || r.status);
  return data;
}

// ── i18n ──
function _normLang(v) { return String(v || '').toLowerCase() === 'en' ? 'en' : 'zh'; }
function _readLang() { return _normLang(localStorage.getItem(SHARED_LANG_KEY) || localStorage.getItem(LEGACY_KEY) || 'zh'); }
function _writeLang(v) {
  const n = _normLang(v);
  localStorage.setItem(SHARED_LANG_KEY, n);
  localStorage.setItem(LEGACY_KEY, n);
  return n;
}
cLang = _readLang();
_writeLang(cLang);

function applyConsoleLang() {
  const zh = cLang === 'zh';
  document.documentElement.lang = zh ? 'zh' : 'en';
  document.title = 'Daemon Console';
  document.getElementById('h-title').textContent = 'Daemon Console';
  document.getElementById('c-lang-btn').textContent = zh ? 'EN' : '\u4e2d';
  const noBtn = document.getElementById('confirm-no');
  const yesBtn = document.getElementById('confirm-yes');
  if (noBtn) noBtn.textContent = tx('\u53d6\u6d88', 'Cancel');
  if (yesBtn) yesBtn.textContent = tx('\u786e\u8ba4', 'Confirm');
  _renderNav();
}
function toggleConsoleLang() {
  cLang = _writeLang(cLang === 'zh' ? 'en' : 'zh');
  applyConsoleLang();
  _rerenderInPlace();
}
window.addEventListener('storage', e => {
  if (e.key !== SHARED_LANG_KEY && e.key !== LEGACY_KEY) return;
  const next = _readLang();
  if (next === cLang) return;
  cLang = next;
  applyConsoleLang();
  _rerenderInPlace();
});

function _rerenderInPlace() {
  const panel = PANELS[_currentPanel];
  if (!panel) return;
  document.getElementById('list-view').innerHTML = panel.render();
  if (_lastWard) updateWard(_lastWard);
  updateSummary(_lastSummary[0], _lastSummary[1]);
  if (_detailOpen && _detailContext != null && panel.openDetail) {
    panel.openDetail(_detailContext);
  }
}

// ── Panel registration & navigation ──
const NAV_ORDER = ['overview', 'routines', 'trails', 'model', 'agents', 'evolution', 'norm', 'endeavors', 'lexicon', 'system'];
const NAV_LABELS = {
  overview:  { zh: 'Overview',   en: 'Overview' },
  routines:  { zh: 'Routines',   en: 'Routines' },
  trails:    { zh: 'Trails',     en: 'Trails' },
  model:     { zh: 'Model',      en: 'Model' },
  agents:    { zh: 'Agents',     en: 'Agents' },
  evolution: { zh: 'Evolution',  en: 'Evolution' },
  norm:      { zh: 'Norm',       en: 'Norm' },
  endeavors: { zh: 'Endeavors',  en: 'Endeavors' },
  lexicon:   { zh: 'Lexicon',    en: 'Lexicon' },
  system:    { zh: 'System',     en: 'System' },
};

function registerPanel(name, panel) {
  if (panel.openDetail) {
    const orig = panel.openDetail;
    panel.openDetail = function(key) {
      _detailContext = key;
      return orig.call(this, key);
    };
  }
  PANELS[name] = panel;
}

function _renderNav() {
  const nav = document.getElementById('nav');
  nav.innerHTML = NAV_ORDER.map(name => {
    const lbl = NAV_LABELS[name] || { zh: name, en: name };
    return `<button class="nav-item${name === _currentPanel ? ' active' : ''}" data-panel="${name}" onclick="showPanel('${name}')">${tx(lbl.zh, lbl.en)}</button>`;
  }).join('');
}

function showPanel(name, force) {
  const panel = PANELS[name];
  if (!panel) return;
  _currentPanel = name;
  _writeState(name);
  popDetail();
  document.getElementById('list-view').scrollTop = 0;
  _renderNav();
  refreshHeader();
  const lv = document.getElementById('list-view');
  lv.innerHTML = '<div class="loading">\u2026</div>';
  panel.load(force).then(() => {
    lv.innerHTML = panel.render();
  }).catch(e => {
    lv.innerHTML = `<div class="empty">${tx('\u52a0\u8f7d\u5931\u8d25\uff1a', 'Error: ')}${esc(e.message)}</div>`;
  });
}

function refreshAll() {
  if (_currentPanel && !_detailOpen) showPanel(_currentPanel, true);
}

function refreshPanel(name) {
  const panel = PANELS[name || _currentPanel];
  if (!panel) return;
  refreshHeader();
  panel.load(true).then(() => {
    document.getElementById('list-view').innerHTML = panel.render();
    if (_detailOpen && _detailContext != null && panel.openDetail) {
      panel.openDetail(_detailContext);
    }
  }).catch(() => {});
}

// ── Detail push/pop ──
function pushDetail(title, html) {
  document.getElementById('detail-title').textContent = title;
  document.getElementById('detail-body').innerHTML = html;
  const dv = document.getElementById('detail-view');
  dv.classList.remove('detail-hidden');
  dv.classList.add('detail-visible');
  document.getElementById('list-view').classList.add('pushed');
  _detailOpen = true;
  dv.scrollTop = 0;
}
function popDetail() {
  document.getElementById('detail-view').classList.remove('detail-visible');
  document.getElementById('detail-view').classList.add('detail-hidden');
  document.getElementById('list-view').classList.remove('pushed');
  _detailOpen = false;
  _detailContext = null;
}

// ── HTML helpers ──
function field(label, value, opts) {
  const cls = opts?.mono ? ' mono' : '';
  return `<div class="field"><div class="field-label">${esc(label)}</div><div class="field-value${cls}">${value}</div></div>`;
}
function fieldText(label, value, opts) {
  return field(label, esc(value || '\u2014'), opts);
}
function statusDot(status) {
  const map = { ok: 'green', green: 'green', running: 'blue', error: 'red', degraded: 'amber', amber: 'amber', enabled: 'green', disabled: 'muted', true: 'green', false: 'muted', blue: 'blue', red: 'red', muted: 'muted' };
  return `<span class="dot ${map[String(status).toLowerCase()] || 'muted'}"></span>`;
}
function tag(text, type) { return `<span class="tag ${type || 'dim'}">${esc(text)}</span>`; }
function actions() { return `<div class="detail-actions">${Array.from(arguments).join('')}</div>`; }
function btn(label, onclick, cls) { return `<button class="btn ${cls || 'primary'}" onclick="${esc(onclick)}">${esc(label)}</button>`; }

// ── Confirm dialog ──
function confirmAction(title, message) {
  return new Promise(resolve => {
    const overlay = document.getElementById('confirm-overlay');
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-msg').textContent = message;
    overlay.classList.remove('hidden');
    function done(v) { overlay.classList.add('hidden'); resolve(v); }
    document.getElementById('confirm-yes').onclick = () => done(true);
    document.getElementById('confirm-no').onclick = () => done(false);
  });
}

// ── State persistence ──
function _readState() {
  try {
    const raw = localStorage.getItem(VIEW_STATE_KEY);
    if (!raw) return 'overview';
    const p = JSON.parse(raw)?.panel || '';
    return NAV_ORDER.includes(p) ? p : 'overview';
  } catch (_) { return 'overview'; }
}
function _writeState(panel) {
  try { localStorage.setItem(VIEW_STATE_KEY, JSON.stringify({ panel })); } catch (_) {}
}

// ── Ward + summary ──
let _lastWard = null;
let _lastSummary = [0, 0];

function updateWard(status) {
  _lastWard = status;
  const badge = document.getElementById('ward-badge');
  const cls = String(status || 'GREEN').toLowerCase();
  badge.textContent = status || 'GREEN';
  badge.className = 'ward ' + cls;
}
function updateSummary(running, awaiting) {
  _lastSummary = [running, awaiting];
  const el = document.getElementById('header-summary');
  const parts = [];
  if (running > 0) parts.push(`${running} ${tx('\u8fd0\u884c\u4e2d', 'running')}`);
  if (awaiting > 0) parts.push(`${awaiting} ${tx('\u5f85\u8bc4\u4ef7', 'awaiting')}`);
  el.textContent = parts.join(' \u00b7 ') || '';
}
async function refreshHeader() {
  try {
    const d = await api('/console/dashboard');
    updateWard(d.ward?.status);
    updateSummary(d.running_deeds || 0, d.awaiting_eval || 0);
  } catch (_) {}
}

// ── Startup panel from query ──
function _readPanelFromQuery() {
  try {
    const p = new URLSearchParams(window.location.search).get('panel') || '';
    return NAV_ORDER.includes(p) ? p : '';
  } catch (_) { return ''; }
}
