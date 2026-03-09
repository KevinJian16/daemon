function refreshAll(opts = {}) {
  const force = opts.force !== false;
  const active = document.querySelector('.panel.active');
  const id = String(active?.id || '');
  const panel = id.startsWith('panel-') ? id.slice(6) : '';
  if (!panel) return;
  if (force) {
    _runPanelLoader(panel, {force: true}).catch(() => {});
  } else {
    _scheduleSoftRefresh(panel);
  }
}

const CONSOLE_SERVER_BOOT_KEY = 'd_console_server_boot_marker';

function _readPanelFromQuery() {
  try {
    const params = new URLSearchParams(window.location.search || '');
    const panel = String(params.get('panel') || '').trim();
    const allow = new Set(['overview', 'lexicon', 'spine', 'psyche', 'norm', 'trails', 'model', 'agents', 'skill-evolution', 'schedules', 'endeavors', 'system']);
    return allow.has(panel) ? panel : '';
  } catch (_) {
    return '';
  }
}

async function resolveStartupPanel() {
  const fromQuery = _readPanelFromQuery();
  if (fromQuery) {
    _writeConsolePanelState(fromQuery);
    return fromQuery;
  }
  const fallback = _readConsolePanelState();
  try {
    const resp = await fetch(`${API}/health`);
    if (!resp.ok) return fallback;
    const data = await resp.json();
    const boot = String(data?.app_started_utc || '').trim();
    if (!boot) return fallback;
    const prev = String(localStorage.getItem(CONSOLE_SERVER_BOOT_KEY) || '').trim();
    if (prev !== boot) localStorage.setItem(CONSOLE_SERVER_BOOT_KEY, boot);
    return fallback;
  } catch (_) {
    return fallback;
  }
}

const unifiedEditorText = document.getElementById('unified-editor-text');
if (unifiedEditorText) {
  unifiedEditorText.addEventListener('input', _syncUnifiedEditorDirty);
}
document.addEventListener('keydown', (event) => {
  if (!unifiedEditorState.open) return;
  if (event.key === 'Escape') {
    event.preventDefault();
    closeUnifiedEditor(false);
    return;
  }
  if ((event.metaKey || event.ctrlKey) && String(event.key || '').toLowerCase() === 's') {
    event.preventDefault();
    saveUnifiedEditor();
  }
});

// Auto-load on start.
(async () => {
  applyConsoleLang();
  const startupPanel = await resolveStartupPanel();
  show(startupPanel, _navButtonForPanel(startupPanel));
  setInterval(() => refreshAll({force: false}), 30000);
})();
