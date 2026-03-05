function refreshAll() {
  const active = document.querySelector('.panel.active');
  if (active?.id === 'panel-overview') loadOverview();
  else if (active?.id === 'panel-spine') loadSpine();
  else if (active?.id === 'panel-fabric') showFabric(currentFabricView || 'memory');
  else if (active?.id === 'panel-policy') loadPolicy();
  else if (active?.id === 'panel-traces') loadTraces();
  else if (active?.id === 'panel-strategies') { loadStrategies(); loadSemantics(); }
  else if (active?.id === 'panel-model') loadModelControl();
  else if (active?.id === 'panel-agents') loadAgents();
  else if (active?.id === 'panel-skill-evolution') loadSkillEvolution();
  else if (active?.id === 'panel-schedules') loadSchedules();
  else if (active?.id === 'panel-campaigns') loadCampaigns();
  else if (active?.id === 'panel-system') loadSystemResetPanel();
}

const CONSOLE_SERVER_BOOT_KEY = 'd_console_server_boot_marker';

async function resolveStartupPanel() {
  const fallback = _readConsolePanelState();
  try {
    const resp = await fetch(`${API}/health`);
    if (!resp.ok) return fallback;
    const data = await resp.json();
    const boot = String(data?.app_started_utc || '').trim();
    if (!boot) return fallback;
    const prev = String(localStorage.getItem(CONSOLE_SERVER_BOOT_KEY) || '').trim();
    if (prev !== boot) {
      localStorage.setItem(CONSOLE_SERVER_BOOT_KEY, boot);
      _writeConsolePanelState('overview');
      return 'overview';
    }
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
  setInterval(refreshAll, 30000);
})();
