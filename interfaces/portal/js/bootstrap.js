// ── Boot ──────────────────────────────────────────────────
async function boot(){
  bindConsoleLink();
  applyI18n();
  showNewChat();

  // Connect WebSocket for real-time updates
  wsConnect();

  await Promise.all([checkWard(), renderNav()]);

  // Auto-open first pending if any
  const first=document.querySelector('#pending-list .nav-item');
  if(first) first.click();

  // Fallback polling (nav refresh every 30s, ward already via WS)
  setInterval(renderNav, 30000);
}
document.addEventListener('DOMContentLoaded', boot);

function bindConsoleLink() {
  const link = document.getElementById('console-link');
  if (!link) return;
  let panel = '';
  try {
    const raw = localStorage.getItem('d_console_view_state');
    const parsed = raw ? JSON.parse(raw) : {};
    const candidate = String(parsed?.panel || '').trim();
    const allow = new Set(['overview', 'lexicon', 'spine', 'psyche', 'norm', 'trails', 'model', 'agents', 'skill-evolution', 'schedules', 'endeavors', 'system']);
    panel = allow.has(candidate) ? candidate : '';
  } catch (_) {
    panel = '';
  }
  link.href = panel ? `/console/?panel=${encodeURIComponent(panel)}` : '/console/';
}
