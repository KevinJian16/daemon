// ── Sync ──────────────────────────────────────────────────
async function checkGate() {
  try {
    const d = await api('/health');
    const g = (d.gate || 'GREEN').toUpperCase();
    const dot = document.getElementById('gate-dot');
    dot.className = g === 'RED' ? 'red' : g === 'YELLOW' ? 'yellow' : '';
    dot.title = 'Gate: ' + g;
  } catch (_) {
    const dot = document.getElementById('gate-dot');
    if (dot) dot.className = 'red';
  }
}
