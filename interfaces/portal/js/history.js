// ── History search/filter ─────────────────────────────────

function filterHistory(q) {
  const query = (q || '').trim().toLowerCase();
  if (!query) {
    // Reset: re-render clustered view
    _renderHistoryClustered(_historyDeeds);
    return;
  }
  const container = document.getElementById('history-groups');
  container.innerHTML = '';
  const filtered = (_historyDeeds || []).filter(d =>
    ((d.deed_title || d.title || d.deed_id || '') + ' ' + (d.group_label || '')).toLowerCase().includes(query)
  );
  if (!filtered.length) {
    container.innerHTML = `<div class="nav-empty" style="padding:6px 14px">${t('none')}</div>`;
    return;
  }
  filtered.forEach(d => {
    const el = makeItem(d.deed_id, d.deed_title || d.title || d.deed_id, '', _deedStatus(d) || 'completed', d.updated_utc || d.created_utc, () => openDeed(d, el));
    container.appendChild(el);
  });
}
