registerPanel('folios', {
  _rows: [],
  _filters: { status: '' },
  async load() {
    this._rows = await api('/console/folios?limit=300');
  },
  render() {
    const rows = this._filtered();
    let html = `<div class="filter-bar">
      <select onchange="PANELS.folios._filters.status=this.value;refreshPanel('folios')">
        <option value="">${tx('全部状态', 'All status')}</option>
        ${['active', 'parked', 'archived', 'dissolved'].map((value) => `<option value="${value}"${this._filters.status === value ? ' selected' : ''}>${esc(folioStatusLabel(value))}</option>`).join('')}
      </select>
    </div>`;
    if (!rows.length) return html + `<div class="empty">${tx('暂无卷。', 'No folios yet.')}</div>`;
    html += rows.map((row) => renderSubItem(
      row.title || row.folio_id || '',
      `${row.slip_count || 0} ${tx('签札', 'slips')} · ${row.writ_count || 0} ${tx('成文', 'writs')} · ${row.active_deed_count || 0} ${tx('行事中', 'live deeds')}`,
      statusDot(row.status || 'muted'),
      `PANELS.folios.openDetail('${esc(row.folio_id || '')}')`
    )).join('');
    return html;
  },
  _filtered() {
    return (this._rows || []).filter((row) => !this._filters.status || String(row.status || '') === this._filters.status);
  },
  async openDetail(folioId) {
    if (!folioId) return;
    pushDetail(tx('卷', 'Folio'), '<div class="loading">…</div>');
    const row = await api('/console/folios/' + encodeURIComponent(folioId));
    let html = '';
    html += fieldText(tx('卷 ID', 'Folio ID'), row.folio_id, { mono: true });
    html += field(tx('状态', 'Status'), tag(folioStatusLabel(row.status), toneForFolio(row.status)));
    html += fieldText(tx('签札数', 'Slip count'), String(row.slips?.length || row.slip_count || 0));
    html += fieldText(tx('成文数', 'Writ count'), String(row.writs?.length || row.writ_count || 0));
    html += fieldText(tx('行事中', 'Active deeds'), String(row.active_deed_count || 0));
    html += fieldText(tx('更新', 'Updated'), fmtTime(row.updated_utc));
    html += fieldText(tx('摘要', 'Summary'), row.summary || '—');
    html += actions(..._folioActionButtons(row));
    html += sectionHeading(tx('卷中签札', 'Slips in this folio'));
    const slips = Array.isArray(row.slips) ? row.slips : [];
    html += slips.length
      ? slips.map((slip) => renderSubItem(
          slip.title || slip.slip_id || '',
          [slipStatusLabel(slip.status), slip.deed_count ? `${slip.deed_count} ${tx('次行事', 'deeds')}` : ''].filter(Boolean).join(' · '),
          statusDot(slip.status || 'muted'),
          `openPanelDetail('slips','${esc(slip.slip_id || '')}',true)`
        )).join('')
      : `<div class="empty">${tx('这卷里还没有签札。', 'No slips are in this folio yet.')}</div>`;
    html += sectionHeading(tx('卷中成文', 'Writs in this folio'));
    const writs = Array.isArray(row.writs) ? row.writs : [];
    html += writs.length
      ? writs.map((writ) => renderSubItem(
          writ.title || writ.writ_id || '',
          [writStatusLabel(writ.status), writ.last_triggered_utc ? fmtTime(writ.last_triggered_utc) : ''].filter(Boolean).join(' · '),
          statusDot(writ.status || 'muted'),
          `openPanelDetail('writs','${esc(writ.writ_id || '')}',true)`
        )).join('')
      : `<div class="empty">${tx('这卷里还没有成文。', 'No writ is attached to this folio yet.')}</div>`;
    pushDetail(row.title || row.folio_id || tx('卷', 'Folio'), html);
  },
});

function _folioActionButtons(row) {
  const folioId = row.folio_id || '';
  const status = String(row.status || '').toLowerCase();
  const buttons = [];
  if (status !== 'active') buttons.push(btn(tx('展开', 'Activate'), `_mutateFolio('${esc(folioId)}','activate')`, 'success'));
  if (status !== 'parked') buttons.push(btn(tx('搁卷', 'Park'), `_mutateFolio('${esc(folioId)}','park')`, 'ghost'));
  if (status !== 'archived') buttons.push(btn(tx('收卷', 'Archive'), `_mutateFolio('${esc(folioId)}','archive')`, 'ghost'));
  if (status !== 'dissolved') buttons.push(btn(tx('散卷', 'Dissolve'), `_mutateFolio('${esc(folioId)}','dissolve')`, 'danger'));
  buttons.push(btn(tx('删除', 'Delete'), `_mutateFolio('${esc(folioId)}','delete')`, 'danger'));
  return buttons;
}

async function _mutateFolio(folioId, action) {
  const ok = await confirmAction(
    tx('卷操作', 'Folio Action'),
    tx(`确认对这卷执行“${action}”？`, `Run "${action}" on this folio?`)
  );
  if (!ok) return;
  try {
    await apiWrite('/console/folios/' + encodeURIComponent(folioId) + '/' + encodeURIComponent(action), 'POST', {});
    refreshPanel('folios');
  } catch (error) {
    pushDetail(tx('错误', 'Error'), `<div class="empty">${esc(error.message)}</div>`);
  }
}
