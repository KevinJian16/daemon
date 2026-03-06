// ── Boot ──────────────────────────────────────────────────
async function boot(){
  bindConsoleLink();
  applyI18n();
  showCompose();
  await Promise.all([checkGate(), renderNav()]);
  // Auto-open first pending if any
  const first=document.querySelector('#pending-list .nav-item');
  if(first) first.click();
  setInterval(()=>{ checkGate(); renderNav(); }, 15000);
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
    const allow = new Set(['overview', 'lexicon', 'spine', 'fabric', 'norm', 'traces', 'strategies', 'model', 'agents', 'skill-evolution', 'schedules', 'campaigns', 'system']);
    panel = allow.has(candidate) ? candidate : '';
  } catch (_) {
    panel = '';
  }
  link.href = panel ? `/console/?panel=${encodeURIComponent(panel)}` : '/console/';
}
