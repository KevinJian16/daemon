// ── Sync ──────────────────────────────────────────────────
async function checkWard() {
  try {
    const d = await api('/health');
    const w = (d.ward || 'GREEN').toUpperCase();
    const dot = document.getElementById('ward-dot');
    dot.className = w === 'RED' ? 'red' : w === 'YELLOW' ? 'yellow' : '';
    dot.title = 'Ward: ' + w;
  } catch (_) {
    const dot = document.getElementById('ward-dot');
    if (dot) dot.className = 'red';
  }
}
