const API = '';
let cLang = 'zh';
const SHARED_LANG_KEY = 'd_lang';
const LEGACY_KEY = 'c_lang';
const VIEW_STATE_KEY = 'd_console_view_state';
const PANELS = {};
let _currentPanel = '';
let _detailOpen = false;
let _detailContext = null;

function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function tx(zh, en) {
  return cLang === 'zh' ? zh : en;
}

function humanize(value) {
  return String(value || '')
    .replace(/_/g, ' ')
    .replace(/\b[a-z]/g, (char) => char.toUpperCase());
}

function fmtTime(utcStr) {
  if (!utcStr) return '—';
  const dt = new Date(utcStr);
  if (Number.isNaN(dt.getTime())) return String(utcStr).replace('T', ' ').replace('Z', '');
  return dt.toLocaleString([], {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

async function api(path) {
  const response = await fetch(API + path);
  if (!response.ok) throw new Error(`${response.status} ${path}`);
  return response.json();
}

async function apiWrite(path, method, body) {
  const hasBody = body !== null && body !== undefined;
  const response = await fetch(API + path, {
    method,
    headers: hasBody ? { 'Content-Type': 'application/json' } : {},
    body: hasBody ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch (_) {
    data = { detail: text || response.status };
  }
  if (!response.ok) throw new Error(data.error || data.detail || response.status);
  return data;
}

function _normLang(value) {
  return String(value || '').toLowerCase() === 'en' ? 'en' : 'zh';
}

function _readLang() {
  return _normLang(localStorage.getItem(SHARED_LANG_KEY) || localStorage.getItem(LEGACY_KEY) || 'zh');
}

function _writeLang(value) {
  const next = _normLang(value);
  localStorage.setItem(SHARED_LANG_KEY, next);
  localStorage.setItem(LEGACY_KEY, next);
  return next;
}

cLang = _readLang();
_writeLang(cLang);

const NAV_ORDER = ['overview', 'lexicon', 'drafts', 'slips', 'folios', 'writs', 'deeds', 'routines', 'trails', 'models', 'agents', 'skills', 'rations', 'system'];
const NAV_LABELS = {
  overview: { zh: '概览', en: 'Overview' },
  lexicon: { zh: '词典', en: 'Lexicon' },
  drafts: { zh: '草稿', en: 'Drafts' },
  slips: { zh: '签札', en: 'Slips' },
  folios: { zh: '卷', en: 'Folios' },
  writs: { zh: '成文', en: 'Writs' },
  deeds: { zh: '行事', en: 'Deeds' },
  routines: { zh: '例行', en: 'Routines' },
  trails: { zh: '踪迹', en: 'Trails' },
  models: { zh: '模型', en: 'Models' },
  agents: { zh: '代理', en: 'Agents' },
  skills: { zh: '技能', en: 'Skills' },
  rations: { zh: '配给', en: 'Rations' },
  system: { zh: '系统', en: 'System' },
};

function applyConsoleLang() {
  const zh = cLang === 'zh';
  document.documentElement.lang = zh ? 'zh' : 'en';
  document.title = zh ? 'Daemon 控制台' : 'Daemon Console';
  const title = document.getElementById('h-title');
  const portalLink = document.getElementById('portal-link');
  const langBtn = document.getElementById('c-lang-btn');
  const noBtn = document.getElementById('confirm-no');
  const yesBtn = document.getElementById('confirm-yes');
  if (title) title.textContent = zh ? 'Daemon 控制台' : 'Daemon Console';
  if (portalLink) portalLink.textContent = tx('门户', 'Portal');
  if (langBtn) langBtn.textContent = zh ? 'EN' : '中';
  if (noBtn) noBtn.textContent = tx('取消', 'Cancel');
  if (yesBtn) yesBtn.textContent = tx('确认', 'Confirm');
  _renderNav();
}

function toggleConsoleLang() {
  cLang = _writeLang(cLang === 'zh' ? 'en' : 'zh');
  applyConsoleLang();
  _rerenderInPlace();
}

window.addEventListener('storage', (event) => {
  if (event.key !== SHARED_LANG_KEY && event.key !== LEGACY_KEY) return;
  const next = _readLang();
  if (next === cLang) return;
  cLang = next;
  applyConsoleLang();
  _rerenderInPlace();
});

function registerPanel(name, panel) {
  if (panel.openDetail) {
    const original = panel.openDetail;
    panel.openDetail = function wrappedOpenDetail(key) {
      _detailContext = key;
      return original.call(this, key);
    };
  }
  PANELS[name] = panel;
}

function _renderNav() {
  const nav = document.getElementById('nav');
  nav.innerHTML = NAV_ORDER.map((name) => {
    const label = NAV_LABELS[name] || { zh: name, en: name };
    return `<button class="nav-item${name === _currentPanel ? ' active' : ''}" data-panel="${name}" onclick="showPanel('${name}')">${tx(label.zh, label.en)}</button>`;
  }).join('');
}

function _rerenderInPlace() {
  const panel = PANELS[_currentPanel];
  if (!panel) return;
  const listView = document.getElementById('list-view');
  listView.innerHTML = panel.render();
  if (_lastWard) updateWard(_lastWard);
  updateSummary(_lastSummary.running, _lastSummary.awaiting, _lastSummary.systemStatus);
  if (_detailOpen && _detailContext != null && panel.openDetail) panel.openDetail(_detailContext);
}

function showPanel(name, force) {
  const panel = PANELS[name];
  if (!panel) return Promise.resolve();
  _currentPanel = name;
  _writeState(name);
  popDetail();
  _renderNav();
  refreshHeader();
  const listView = document.getElementById('list-view');
  listView.scrollTop = 0;
  listView.innerHTML = '<div class="loading">…</div>';
  return panel.load(force).then(() => {
    listView.innerHTML = panel.render();
  }).catch((error) => {
    listView.innerHTML = `<div class="empty">${tx('加载失败：', 'Error: ')}${esc(error.message)}</div>`;
  });
}

async function openPanelDetail(name, key, force) {
  await showPanel(name, force);
  const panel = PANELS[name];
  if (panel?.openDetail) panel.openDetail(key);
}

function refreshAll() {
  if (_currentPanel && !_detailOpen) showPanel(_currentPanel, true);
}

function refreshPanel(name) {
  const panelName = name || _currentPanel;
  const panel = PANELS[panelName];
  if (!panel) return;
  refreshHeader();
  panel.load(true).then(() => {
    document.getElementById('list-view').innerHTML = panel.render();
    if (_detailOpen && _detailContext != null && panel.openDetail) panel.openDetail(_detailContext);
  }).catch(() => {});
}

function pushDetail(title, html) {
  document.getElementById('detail-title').textContent = title;
  document.getElementById('detail-body').innerHTML = html;
  const detailView = document.getElementById('detail-view');
  detailView.classList.remove('detail-hidden');
  detailView.classList.add('detail-visible');
  document.getElementById('list-view').classList.add('pushed');
  detailView.scrollTop = 0;
  _detailOpen = true;
}

function popDetail() {
  document.getElementById('detail-view').classList.remove('detail-visible');
  document.getElementById('detail-view').classList.add('detail-hidden');
  document.getElementById('list-view').classList.remove('pushed');
  _detailOpen = false;
  _detailContext = null;
}

function field(label, value, opts) {
  const mono = opts?.mono ? ' mono' : '';
  return `<div class="field"><div class="field-label">${esc(label)}</div><div class="field-value${mono}">${value}</div></div>`;
}

function fieldText(label, value, opts) {
  return field(label, esc(value || '—'), opts);
}

function statusDot(status) {
  const tones = {
    ok: 'green',
    healthy: 'green',
    active: 'green',
    running: 'blue',
    queued: 'blue',
    review: 'amber',
    awaiting_eval: 'amber',
    paused: 'amber',
    parked: 'amber',
    degraded: 'amber',
    error: 'red',
    failed: 'red',
    blocked: 'red',
    archived: 'muted',
    disabled: 'muted',
    completed: 'muted',
    cancelled: 'muted',
    dissolved: 'muted',
    crystallized: 'green',
    open: 'blue',
    refining: 'amber',
  };
  return `<span class="dot ${tones[String(status).toLowerCase()] || 'muted'}"></span>`;
}

function tag(text, tone) {
  return `<span class="tag ${tone || 'dim'}">${esc(text)}</span>`;
}

function btn(label, onclick, cls) {
  return `<button class="btn ${cls || 'primary'}" onclick="${esc(onclick)}">${esc(label)}</button>`;
}

function actions() {
  return `<div class="detail-actions">${Array.from(arguments).join('')}</div>`;
}

function confirmAction(title, message) {
  return new Promise((resolve) => {
    const overlay = document.getElementById('confirm-overlay');
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-msg').textContent = message;
    overlay.classList.remove('hidden');
    function done(value) {
      overlay.classList.add('hidden');
      resolve(value);
    }
    document.getElementById('confirm-yes').onclick = () => done(true);
    document.getElementById('confirm-no').onclick = () => done(false);
  });
}

function toneForSlip(status) {
  const value = String(status || '').toLowerCase();
  if (['active', 'settled'].includes(value)) return 'ok';
  if (['parked'].includes(value)) return 'warn';
  if (['archived', 'absorbed'].includes(value)) return 'dim';
  return 'dim';
}

function toneForFolio(status) {
  const value = String(status || '').toLowerCase();
  if (value === 'active') return 'ok';
  if (value === 'parked') return 'warn';
  if (['archived', 'dissolved'].includes(value)) return 'dim';
  return 'dim';
}

function toneForWrit(status) {
  const value = String(status || '').toLowerCase();
  if (value === 'active') return 'ok';
  if (value === 'paused') return 'warn';
  if (value === 'disabled') return 'dim';
  return 'dim';
}

function toneForDraft(status) {
  const value = String(status || '').toLowerCase();
  if (['open'].includes(value)) return 'info';
  if (['refining'].includes(value)) return 'warn';
  if (['crystallized'].includes(value)) return 'ok';
  if (['superseded', 'abandoned'].includes(value)) return 'dim';
  return 'dim';
}

function toneForDeed(status) {
  const value = String(status || '').toLowerCase();
  if (['running', 'queued'].includes(value)) return 'info';
  if (['paused', 'awaiting_eval', 'cancelling'].includes(value)) return 'warn';
  if (['failed', 'failed_submission', 'replay_exhausted'].includes(value)) return 'error';
  if (['completed', 'cancelled'].includes(value)) return 'dim';
  return 'dim';
}

function slipStatusLabel(status) {
  const map = {
    active: tx('续办中', 'Active'),
    parked: tx('已搁置', 'Parked'),
    settled: tx('已收束', 'Settled'),
    archived: tx('已收起', 'Archived'),
    absorbed: tx('已并入', 'Absorbed'),
  };
  return map[String(status || '').toLowerCase()] || (status || '—');
}

function folioStatusLabel(status) {
  const map = {
    active: tx('展开中', 'Active'),
    parked: tx('暂不翻卷', 'Parked'),
    archived: tx('已收卷', 'Archived'),
    dissolved: tx('已散卷', 'Dissolved'),
  };
  return map[String(status || '').toLowerCase()] || (status || '—');
}

function writStatusLabel(status) {
  const map = {
    active: tx('生效中', 'Active'),
    paused: tx('已暂停', 'Paused'),
    disabled: tx('已停用', 'Disabled'),
  };
  return map[String(status || '').toLowerCase()] || (status || '—');
}

function deedStatusLabel(status) {
  const map = {
    running: tx('正在行事', 'Running'),
    queued: tx('待行', 'Queued'),
    paused: tx('已停驻', 'Paused'),
    cancelling: tx('正在收束', 'Stopping'),
    awaiting_eval: tx('待阅看', 'Needs Review'),
    completed: tx('已做成', 'Completed'),
    cancelled: tx('已止住', 'Cancelled'),
    failed: tx('未做成', 'Failed'),
    failed_submission: tx('未能起行', 'Could Not Start'),
    replay_exhausted: tx('再行用尽', 'Retries Exhausted'),
  };
  return map[String(status || '').toLowerCase()] || (status || '—');
}

function draftStatusLabel(status) {
  const map = {
    open: tx('待收敛', 'Open'),
    refining: tx('收敛中', 'Refining'),
    crystallized: tx('已落札', 'Crystallized'),
    superseded: tx('已被替换', 'Superseded'),
    abandoned: tx('已废弃', 'Abandoned'),
  };
  return map[String(status || '').toLowerCase()] || (status || '—');
}

function shortJsonSummary(value) {
  if (Array.isArray(value)) return value.length ? `${value.length}` : '—';
  if (value && typeof value === 'object') {
    const keys = Object.keys(value);
    return keys.length ? keys.join(' · ') : '—';
  }
  return String(value || '—');
}

function sectionHeading(title, copy) {
  return `<div class="section-heading">${esc(title)}</div>${copy ? `<div class="section-copy">${esc(copy)}</div>` : ''}`;
}

function renderTimeline(steps) {
  const rows = Array.isArray(steps) ? steps : [];
  if (!rows.length) return `<div class="empty">${tx('暂无结构。', 'No structure yet.')}</div>`;
  return `<div class="timeline-stack">${rows.map((row) => `
    <div class="timeline-row ${esc(String(row.state || 'pending'))}">
      <span class="timeline-bullet"></span>
      <div class="timeline-copy">
        <div class="timeline-title">${esc(row.label || row.title || row.id || '')}</div>
        ${row.agent ? `<div class="timeline-sub">${esc(row.agent)}</div>` : ''}
      </div>
    </div>
  `).join('')}</div>`;
}

function renderSubItem(title, sub, trail, onclick) {
  const clickable = onclick ? ` onclick="${esc(onclick)}"` : '';
  const cls = onclick ? 'list-item' : 'sub-item';
  return `<div class="${cls}"${clickable}>
    <div class="item-main">
      <div class="item-title">${esc(title)}</div>
      ${sub ? `<div class="item-sub">${esc(sub)}</div>` : ''}
    </div>
    ${trail || ''}
  </div>`;
}

function _readState() {
  try {
    const raw = localStorage.getItem(VIEW_STATE_KEY);
    if (!raw) return 'overview';
    const panel = JSON.parse(raw)?.panel || '';
    return NAV_ORDER.includes(panel) ? panel : 'overview';
  } catch (_) {
    return 'overview';
  }
}

function _writeState(panel) {
  try {
    localStorage.setItem(VIEW_STATE_KEY, JSON.stringify({ panel }));
  } catch (_) {}
}

let _lastWard = null;
let _lastSummary = { running: 0, awaiting: 0, systemStatus: '' };

function updateWard(status) {
  _lastWard = status;
  const badge = document.getElementById('ward-badge');
  const tone = String(status || 'GREEN').toLowerCase();
  badge.textContent = status || 'GREEN';
  badge.className = 'ward ' + tone;
}

function updateSummary(running, awaiting, systemStatus) {
  _lastSummary = { running: running || 0, awaiting: awaiting || 0, systemStatus: systemStatus || '' };
  const summary = document.getElementById('header-summary');
  const parts = [];
  if (running > 0) parts.push(`${running} ${tx('行事中', 'running')}`);
  if (awaiting > 0) parts.push(`${awaiting} ${tx('待阅看', 'awaiting')}`);
  if (systemStatus) parts.push(`${tx('系统', 'system')} ${String(systemStatus)}`);
  summary.textContent = parts.join(' · ');
}

async function refreshHeader() {
  try {
    const dashboard = await api('/console/dashboard');
    updateWard(dashboard.ward?.status);
    updateSummary(dashboard.running_deeds || 0, dashboard.awaiting_eval || 0, dashboard.system_status || '');
  } catch (_) {}
}

function _readPanelFromQuery() {
  try {
    const panel = new URLSearchParams(window.location.search).get('panel') || '';
    return NAV_ORDER.includes(panel) ? panel : '';
  } catch (_) {
    return '';
  }
}
