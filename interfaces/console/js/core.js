const API = '';

// Convert UTC ISO string to local time display
function fmtTime(utcStr) {
  if (!utcStr) return '—';
  const d = new Date(utcStr);
  if (isNaN(d)) return String(utcStr).replace('T',' ').replace('Z','');
  return d.toLocaleString([], {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'});
}

let activeAgentId = '';
let activeAgentSkills = [];
let activeLoreMethod = null;
let currentNormScope = 'quality';
let currentNormType = 'default';
let currentNormVersions = [];
let currentNormKeys = [];
let currentModelVersions = [];
let currentModelPolicy = {};
let resetChallenge = null;
let runningDeedsCount = 0;
let unifiedEditorState = {
  open: false,
  dirty: false,
  key: '',
  title: '',
  subtitle: '',
  baseText: '',
  saveText: null,
  onSaved: null,
  mode: 'edit',
};
const listUiState = {};
const CONSOLE_VIEW_STATE_KEY = 'd_console_view_state';
const PANEL_CACHE_TTL_MS = 60 * 1000;
const panelLoadState = {};

function _readConsolePanelState() {
  try {
    const raw = localStorage.getItem(CONSOLE_VIEW_STATE_KEY);
    if (!raw) return 'overview';
    const parsed = JSON.parse(raw);
    const panel = String(parsed?.panel || '').trim();
    const allow = new Set(['overview', 'lexicon', 'spine', 'psyche', 'norm', 'trails', 'model', 'agents', 'skill-evolution', 'schedules', 'endeavors', 'system']);
    return allow.has(panel) ? panel : 'overview';
  } catch (_) {
    return 'overview';
  }
}

function _writeConsolePanelState(panel) {
  try {
    localStorage.setItem(CONSOLE_VIEW_STATE_KEY, JSON.stringify({panel: String(panel || 'overview')}));
  } catch (_) {}
}

function _navButtonForPanel(panel) {
  return Array.from(document.querySelectorAll('nav button')).find((b) =>
    String(b.getAttribute('onclick') || '').includes(`show('${panel}'`)
  ) || null;
}

// ── Console i18n ──────────────────────────────────────────
const SHARED_LANG_KEY = 'd_lang';
const LEGACY_CONSOLE_LANG_KEY = 'c_lang';
function _normLang(v) { return String(v || '').toLowerCase() === 'en' ? 'en' : 'zh'; }
function _readLang() {
  return _normLang(localStorage.getItem(SHARED_LANG_KEY) || localStorage.getItem(LEGACY_CONSOLE_LANG_KEY) || 'zh');
}
function _writeLang(v) {
  const n = _normLang(v);
  localStorage.setItem(SHARED_LANG_KEY, n);
  localStorage.setItem(LEGACY_CONSOLE_LANG_KEY, n);
  return n;
}
let cLang = _readLang();
_writeLang(cLang);
function tx(zh, en) { return cLang === 'zh' ? zh : en; }
let currentPsycheView = 'memory';
const CONSOLE_STATIC_TEXT = [
  {sel:'#panel-overview .stat:nth-child(1) .lbl', zh:'Memory 单元', en:'Memory Units'},
  {sel:'#panel-overview .stat:nth-child(2) .lbl', zh:'活跃 Recipes', en:'Active Recipes'},
  {sel:'#panel-overview .stat:nth-child(3) .lbl', zh:'Attention 信号', en:'Attention Signals'},
  {sel:'#panel-overview .stat:nth-child(4) .lbl', zh:'运行中 Deeds', en:'Running Deeds'},
  {sel:'#panel-overview .card h3', zh:'今日 Cortex 用量', en:'Cortex Usage Today'},
  {sel:'#panel-spine .card:nth-of-type(1) h3', zh:'Spine 运行态', en:'Spine Runtime'},
  {sel:'#panel-spine .card:nth-of-type(2) h3', zh:'Nerve 事件流', en:'Nerve Event Feed'},
  {sel:'#panel-spine .card:nth-of-type(3) h3', zh:'依赖图', en:'Dependency Graph'},
  {sel:'#norm-heading-priorities', zh:'领域优先级', en:'Domain Priorities'},
  {sel:'#norm-heading-editor', zh:'Norm 编辑器', en:'Norm Editor'},
  {sel:'#norm-heading-quality', zh:'Norm 质量键', en:'Norm Quality Keys'},
  {sel:'#norm-heading-preferences', zh:'Norm 偏好', en:'Norm Preferences'},
  {sel:'#norm-heading-rations', zh:'Norm 配额', en:'Norm Rations'},
  {sel:'#norm-heading-versions', zh:'Norm 版本', en:'Norm Versions'},
  {sel:'#panel-trails .card h3', zh:'Trail 详情', en:'Trail Detail'},
  {sel:'#panel-model .card:nth-of-type(2) h3', zh:'模型调用明细（Cortex）', en:'Model Usage Detail (Cortex)'},
  {sel:'#panel-model .card:nth-of-type(3) h3', zh:'模型调用汇总（Cortex）', en:'Model Usage Summary (Cortex)'},
  {sel:'#panel-model .card:nth-of-type(4) h3', zh:'模型用量（聚合）', en:'Model Usage (Aggregated)'},
  {sel:'#panel-model .card:nth-of-type(5) h3', zh:'模型配置版本', en:'Model Config Versions'},
  {sel:'#panel-agents .card:nth-of-type(1) h3', zh:'OpenClaw 代理', en:'OpenClaw Agents'},
  {sel:'#panel-agents .card:nth-of-type(2) h3', zh:'Agent 技能', en:'Agent Skills'},
  {sel:'#panel-skill-evolution .card:nth-of-type(1) h3', zh:'Skill 进化提案', en:'Skill Evolution Proposals'},
  {sel:'#panel-skill-evolution .card:nth-of-type(2) h3', zh:'提案详情', en:'Proposal Detail'},
  {sel:'#panel-schedules .card:nth-of-type(1) h3', zh:'Spine 节律', en:'Spine Cadence'},
  {sel:'#panel-schedules .card:nth-of-type(2) h3', zh:'节律历史', en:'Cadence History'},
  {sel:'#panel-endeavors .card:nth-of-type(1) h3', zh:'Endeavor 列表', en:'Endeavor List'},
  {sel:'#panel-endeavors .card:nth-of-type(2) h3', zh:'Endeavor 详情', en:'Endeavor Detail'},
  {sel:'#panel-system .card:nth-of-type(1) h3', zh:'托管 Drive 存储', en:'Managed Drive Storage'},
  {sel:'#panel-system .card:nth-of-type(2) h3', zh:'系统重置（challenge/confirm 仅本机）', en:'System Reset (Challenge/Confirm = Localhost Only)'},
  {sel:'#panel-system .card:nth-of-type(3) h3', zh:'最近重置报告', en:'Last Reset Report'},
  {sel:'#norm-editor-meta', zh:'编辑器空闲', en:'Editor idle'},
];
const CONSOLE_INPUT_PLACEHOLDERS = [
  {sel:'#lexicon-q', zh:'term / definition', en:'term / definition'},
  {sel:'#trail-since', zh:'起始 UTC（可选）', en:'since UTC (optional)'},
  {sel:'#trail-q', zh:'trail_id / routine', en:'trail_id / routine'},
  {sel:'#cortex-q', zh:'provider / model / trail', en:'provider / model / trail'},
  {sel:'#sev-q', zh:'proposal / skill / status', en:'proposal / skill / status'},
  {sel:'#schedules-q', zh:'routine / mode / schedule', en:'routine / mode / schedule'},
  {sel:'#schedule-history-q', zh:'routine / status / detail', en:'routine / status / detail'},
  {sel:'#endeavor-q', zh:'endeavor / deed / endeavor_status / endeavor_phase', en:'endeavor / deed / endeavor_status / endeavor_phase'},
  {sel:'#agents-q', zh:'agent / workspace status', en:'agent / workspace status'},
  {sel:'#agent-skills-q', zh:'skill / path / status', en:'skill / path / status'},
  {sel:'#storage-daemon-dir-name', zh:'daemon 目录名（例：daemon）', en:'daemon directory name (e.g. daemon)'},
];
function applyConsoleLang() {
  const zh = cLang === 'zh';
  document.documentElement.lang = zh ? 'zh' : 'en';
  document.title = zh ? 'Daemon 控制台' : 'Daemon Console';
  document.getElementById('c-lang-btn').textContent = zh ? 'EN' : '中';
  document.getElementById('h-title').textContent = zh ? 'Daemon 控制台' : 'Daemon Console';
  document.getElementById('ward-label').textContent = zh ? '接单中' : 'Accepting';
  document.querySelectorAll('[data-zh][data-en]').forEach(b => {
    b.textContent = zh ? b.dataset.zh : b.dataset.en;
  });
  CONSOLE_STATIC_TEXT.forEach(row => {
    const el = document.querySelector(row.sel);
    if (el) el.textContent = zh ? row.zh : row.en;
  });
  CONSOLE_INPUT_PLACEHOLDERS.forEach(row => {
    const el = document.querySelector(row.sel);
    if (el) el.placeholder = zh ? row.zh : row.en;
  });
  document.getElementById('running-deeds').textContent = tx(`${runningDeedsCount} 运行中`, `${runningDeedsCount} running`);
  const storageNote = document.getElementById('system-storage-note');
  if (storageNote) {
    storageNote.innerHTML = zh
      ? '托管结构：<code>My Drive/&lt;daemon_dir_name&gt;/{vault,offerings}</code>。'
      : 'Managed structure: <code>My Drive/&lt;daemon_dir_name&gt;/{vault,offerings}</code>.';
  }
  const resetNote = document.getElementById('system-reset-note');
  if (resetNote) {
    resetNote.textContent = zh
      ? '重置需要 challenge + confirm；confirm 为一次性动作，过期后自动失效。'
      : 'Reset requires challenge + confirm. Confirm action is one-time and expires automatically.';
  }
  _translateDefaultText('#norm-version-preview', '请选择一个版本进行预览。', 'Select one version to preview.');
  _translateDefaultText('#trail-detail', '请选择一条 Trail 记录查看详情。', 'Select a trail row to inspect details.');
  _translateDefaultText('#model-usage-summary', '加载中…', 'Loading…');
  _translateDefaultText('#sev-detail', '请选择一个提案查看详情。', 'Select a proposal to inspect details.');
  _translateDefaultText('#endeavor-detail', '请选择一条 Endeavor 记录查看 manifest/passages。', 'Select an endeavor row to inspect manifest/passages.');
  _translateDefaultText('#storage-status-body', '加载中…', 'Loading…');
  _translateDefaultText('#system-reset-state', '尚未生成重置挑战码。', 'No reset challenge issued.');
  _translateDefaultText('#system-reset-report', '暂无报告。', 'No report.');
  const normScope = document.getElementById('norm-scope');
  if (normScope && normScope.options.length >= 3) {
    normScope.options[0].text = 'quality';
    normScope.options[1].text = 'preference';
    normScope.options[2].text = 'ration';
  }
  const trailRoutine = document.getElementById('trail-routine');
  if (trailRoutine && trailRoutine.options.length > 0) {
    trailRoutine.options[0].text = zh ? '全部 routines' : 'All routines';
  }
  const trailStatus = document.getElementById('trail-status');
  if (trailStatus && trailStatus.options.length > 0) {
    trailStatus.options[0].text = zh ? '任意状态' : 'Any status';
  }
  const sev = document.getElementById('sev-status');
  if (sev && sev.options.length > 0) {
    sev.options[0].text = zh ? '全部状态' : 'All status';
  }
  const normVersionSel = document.getElementById('norm-version-select');
  if (normVersionSel && normVersionSel.options.length > 0 && normVersionSel.options[0].value === '') {
    normVersionSel.options[0].text = zh ? '选择版本' : 'Select version';
  }
  const modelVersionSel = document.getElementById('model-version-select');
  if (modelVersionSel && modelVersionSel.options.length > 0 && modelVersionSel.options[0].value === '') {
    modelVersionSel.options[0].text = zh ? '选择版本' : 'Select version';
  }
  const loreVersionSel = document.getElementById('lore-version-select');
  if (loreVersionSel && loreVersionSel.options.length > 0 && loreVersionSel.options[0].value === '') {
    loreVersionSel.options[0].text = zh ? '选择版本' : 'Select version';
  }
  const hrt = document.getElementById('schedule-history-routine');
  if (hrt && hrt.options.length > 0) {
    hrt.options[0].text = zh ? '全部 routines' : 'All routines';
  }
  const trailPreset = document.getElementById('trail-date-preset');
  if (trailPreset && trailPreset.options.length >= 5) {
    trailPreset.options[0].text = zh ? '手动' : 'Manual';
    trailPreset.options[1].text = zh ? '今天' : 'Today';
    trailPreset.options[2].text = zh ? '近24小时' : 'Last 24h';
    trailPreset.options[3].text = zh ? '近7天' : 'Last 7d';
    trailPreset.options[4].text = zh ? '近30天' : 'Last 30d';
  }
  const cortexPreset = document.getElementById('cortex-date-preset');
  if (cortexPreset && cortexPreset.options.length >= 4) {
    cortexPreset.options[0].text = zh ? '近1小时' : 'Last 1h';
    cortexPreset.options[1].text = zh ? '近6小时' : 'Last 6h';
    cortexPreset.options[2].text = zh ? '近24小时' : 'Last 24h';
    cortexPreset.options[3].text = zh ? '近7天' : 'Last 7d';
  }
  const schedulePreset = document.getElementById('schedule-history-date-preset');
  if (schedulePreset && schedulePreset.options.length >= 4) {
    schedulePreset.options[0].text = zh ? '全部时间' : 'All time';
    schedulePreset.options[1].text = zh ? '今天' : 'Today';
    schedulePreset.options[2].text = zh ? '近24小时' : 'Last 24h';
    schedulePreset.options[3].text = zh ? '近7天' : 'Last 7d';
  }
}

function _translateDefaultText(selector, zhText, enText) {
  const el = document.querySelector(selector);
  if (!el) return;
  const current = String(el.textContent || '').trim();
  if (current === String(zhText).trim() || current === String(enText).trim()) {
    el.textContent = tx(zhText, enText);
  }
}
function toggleConsoleLang() {
  cLang = _writeLang(cLang === 'zh' ? 'en' : 'zh');
  applyConsoleLang();
  refreshAll();
}
window.addEventListener('storage', (event) => {
  if (event.key !== SHARED_LANG_KEY && event.key !== LEGACY_CONSOLE_LANG_KEY) return;
  const next = _readLang();
  if (next === cLang) return;
  cLang = next;
  applyConsoleLang();
  refreshAll();
});
// Ward label reflects status.
function updateWardLabel(status) {
  const labels = {zh:{GREEN:'接单中',YELLOW:'降级运行',RED:'暂停接单'}, en:{GREEN:'Accepting',YELLOW:'Degraded',RED:'Blocked'}};
  const lbl = (labels[cLang]||labels.zh)[status] || status;
  document.getElementById('ward-label').textContent = lbl;
}

function _setUnifiedEditorStatus(text) {
  const node = document.getElementById('unified-editor-notice');
  if (node) node.textContent = text || '';
}

function _syncUnifiedEditorDirty() {
  const editor = document.getElementById('unified-editor-text');
  const tag = document.getElementById('unified-editor-mode');
  if (!editor || !tag) return;
  unifiedEditorState.dirty = editor.value !== (unifiedEditorState.baseText || '');
  tag.textContent = unifiedEditorState.mode + (unifiedEditorState.dirty ? ' • dirty' : ' • clean');
}

function closeUnifiedEditor(force = false) {
  const drawer = document.getElementById('editor-drawer');
  const backdrop = document.getElementById('editor-backdrop');
  const editor = document.getElementById('unified-editor-text');
  if (!force && unifiedEditorState.open && unifiedEditorState.dirty) {
    const ok = confirm(tx('当前编辑尚未保存，确认丢弃修改？', 'Discard unsaved changes?'));
    if (!ok) return false;
  }
  unifiedEditorState.open = false;
  unifiedEditorState.dirty = false;
  unifiedEditorState.key = '';
  unifiedEditorState.title = '';
  unifiedEditorState.subtitle = '';
  unifiedEditorState.baseText = '';
  unifiedEditorState.saveText = null;
  unifiedEditorState.onSaved = null;
  unifiedEditorState.mode = 'idle';
  if (editor) editor.value = '';
  if (drawer) {
    drawer.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
  }
  if (backdrop) backdrop.classList.remove('open');
  _setUnifiedEditorStatus(tx('Cmd/Ctrl+S 保存 · Esc 取消', 'Cmd/Ctrl+S save · Esc cancel'));
  return true;
}

function resetUnifiedEditor() {
  const editor = document.getElementById('unified-editor-text');
  if (!editor) return;
  editor.value = unifiedEditorState.baseText || '';
  _syncUnifiedEditorDirty();
}

async function saveUnifiedEditor() {
  const saver = unifiedEditorState.saveText;
  const editor = document.getElementById('unified-editor-text');
  if (!editor || typeof saver !== 'function') return;
  const btn = document.getElementById('unified-editor-save');
  try {
    if (btn) btn.disabled = true;
    _setUnifiedEditorStatus(tx('保存中…', 'Saving...'));
    await saver(editor.value || '');
    if (typeof unifiedEditorState.onSaved === 'function') {
      await unifiedEditorState.onSaved();
    }
    closeUnifiedEditor(true);
  } catch (e) {
    _setUnifiedEditorStatus(tx('保存失败：', 'Save failed: ') + e.message);
    alert(tx('保存失败：', 'Save failed: ') + e.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function openUnifiedEditor(opts) {
  const drawer = document.getElementById('editor-drawer');
  const backdrop = document.getElementById('editor-backdrop');
  const title = document.getElementById('unified-editor-title');
  const subtitle = document.getElementById('unified-editor-subtitle');
  const modeTag = document.getElementById('unified-editor-mode');
  const editor = document.getElementById('unified-editor-text');
  const saveBtn = document.getElementById('unified-editor-save');
  if (!drawer || !backdrop || !title || !subtitle || !modeTag || !editor || !saveBtn) return false;
  if (unifiedEditorState.open && unifiedEditorState.dirty) {
    const ok = confirm(tx('当前编辑尚未保存，确认切换到新的编辑对象？', 'Switch editor target and discard unsaved changes?'));
    if (!ok) return false;
  }
  unifiedEditorState.open = true;
  unifiedEditorState.dirty = false;
  unifiedEditorState.key = String(opts?.key || '');
  unifiedEditorState.title = String(opts?.title || 'Editor');
  unifiedEditorState.subtitle = String(opts?.subtitle || '—');
  unifiedEditorState.saveText = typeof opts?.saveText === 'function' ? opts.saveText : null;
  unifiedEditorState.onSaved = typeof opts?.onSaved === 'function' ? opts.onSaved : null;
  unifiedEditorState.mode = opts?.readOnly ? 'read-only' : 'edit';
  title.textContent = unifiedEditorState.title;
  subtitle.textContent = unifiedEditorState.subtitle;
  modeTag.textContent = unifiedEditorState.mode;
  saveBtn.disabled = !!opts?.readOnly;
  drawer.classList.add('open');
  drawer.setAttribute('aria-hidden', 'false');
  backdrop.classList.add('open');
  editor.value = '';
  _setUnifiedEditorStatus(opts?.hint || tx('加载中…', 'Loading...'));
  try {
    const text = typeof opts?.loadText === 'function' ? await opts.loadText() : '';
    unifiedEditorState.baseText = String(text ?? '');
    editor.value = unifiedEditorState.baseText;
    _syncUnifiedEditorDirty();
    _setUnifiedEditorStatus(opts?.hint || tx('已进入编辑态。', 'Editing mode enabled.'));
    editor.focus();
    return true;
  } catch (e) {
    _setUnifiedEditorStatus(tx('加载失败：', 'Load failed: ') + e.message);
    alert(tx('加载失败：', 'Load failed: ') + e.message);
    return false;
  }
}

function clearTransientUi(_nextPanel) {
  if (unifiedEditorState.open && !closeUnifiedEditor(false)) return false;
  return true;
}

function _panelState(panel) {
  if (!panelLoadState[panel]) {
    panelLoadState[panel] = {loaded: false, loadedAt: 0, loading: null};
  }
  return panelLoadState[panel];
}

async function _runPanelLoader(panel, opts = {}) {
  const force = !!opts.force;
  const st = _panelState(panel);
  if (st.loading) return st.loading;
  if (!force && st.loaded) return;
  let loader = null;
  if (panel === 'overview') loader = loadOverview;
  else if (panel === 'lexicon') loader = loadLexicon;
  else if (panel === 'spine') loader = loadSpine;
  else if (panel === 'psyche') loader = () => showPsyche(currentPsycheView || 'memory');
  else if (panel === 'norm') loader = loadNorm;
  else if (panel === 'trails') loader = loadTrails;
  else if (panel === 'model') loader = loadModelControl;
  else if (panel === 'agents') loader = loadAgents;
  else if (panel === 'skill-evolution') loader = loadSkillEvolution;
  else if (panel === 'schedules') loader = loadSchedules;
  else if (panel === 'endeavors') loader = loadEndeavors;
  else if (panel === 'system') loader = loadSystemResetPanel;
  if (!loader) return;
  st.loading = Promise.resolve()
    .then(() => loader())
    .then(() => {
      st.loaded = true;
      st.loadedAt = Date.now();
    })
    .catch((err) => {
      console.error('[console] panel load failed:', panel, err);
      throw err;
    })
    .finally(() => {
      st.loading = null;
    });
  return st.loading;
}

function _scheduleSoftRefresh(panel) {
  const st = _panelState(panel);
  if (!st.loaded) return;
  if ((Date.now() - Number(st.loadedAt || 0)) < PANEL_CACHE_TTL_MS) return;
  setTimeout(() => { _runPanelLoader(panel, {force: true}).catch(() => {}); }, 0);
}

function show(panel, el) {
  if (!clearTransientUi(panel)) return;
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.getElementById('panel-' + panel).classList.add('active');
  const navBtn = el || _navButtonForPanel(panel);
  if (navBtn) navBtn.classList.add('active');
  _writeConsolePanelState(panel);
  const st = _panelState(panel);
  if (!st.loaded) {
    _runPanelLoader(panel, {force: true}).catch(() => {});
  } else {
    _scheduleSoftRefresh(panel);
  }
}

function _listState(key, defaults = {page: 1, size: 20}) {
  if (!listUiState[key]) {
    listUiState[key] = {page: defaults.page || 1, size: defaults.size || 20};
  }
  return listUiState[key];
}

function setPageSizeAndReload(key, sizeValue, reloadFn) {
  const st = _listState(key);
  st.size = Math.max(1, Number(sizeValue || st.size || 20));
  st.page = 1;
  if (typeof reloadFn === 'function') reloadFn();
}

function _applyListQuery(rows, query, fields = []) {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return rows;
  return rows.filter((row) => {
    const text = fields.map((f) => String(row?.[f] ?? '')).join(' ').toLowerCase();
    return text.includes(q);
  });
}

function _paginate(rows, key, pagerId, reloadFn) {
  const st = _listState(key);
  const total = rows.length;
  const size = Math.max(1, Number(st.size || 20));
  const totalPages = Math.max(1, Math.ceil(total / size));
  st.page = Math.min(Math.max(1, Number(st.page || 1)), totalPages);
  const start = (st.page - 1) * size;
  const pageRows = rows.slice(start, start + size);
  const pager = document.getElementById(pagerId);
  if (pager) {
    pager.innerHTML = `
      <button ${st.page <= 1 ? 'disabled' : ''} onclick="setListPage('${key}', ${st.page - 1}, '${reloadFn}')">◀</button>
      <span>${st.page} / ${totalPages} · ${total}</span>
      <button ${st.page >= totalPages ? 'disabled' : ''} onclick="setListPage('${key}', ${st.page + 1}, '${reloadFn}')">▶</button>
    `;
  }
  return pageRows;
}

function setListPage(key, page, reloadFnName) {
  const st = _listState(key);
  st.page = Math.max(1, Number(page || 1));
  const fn = typeof reloadFnName === 'function' ? reloadFnName : window[String(reloadFnName || '')];
  if (typeof fn === 'function') fn();
}

function applyDatePreset(target) {
  if (target === 'cortex') { loadCortexUsage(); return; }
  if (target === 'trail') { loadTrails(); return; }
}

async function api(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

async function apiWrite(path, method, body) {
  const hasBody = body !== null && body !== undefined;
  const r = await fetch(API + path, {
    method,
    headers: hasBody ? {'Content-Type': 'application/json'} : {},
    body: hasBody ? JSON.stringify(body) : undefined,
  });
  const text = await r.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch (_) { data = {"detail": text || r.status}; }
  if (!r.ok) throw new Error(data.error || data.detail || r.status);
  return data;
}
