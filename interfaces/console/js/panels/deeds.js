registerPanel('deeds', {
  _rows: [],
  _filters: { status: '' },
  async load() {
    this._rows = await api('/console/deeds?limit=400');
  },
  render() {
    const rows = this._filtered();
    let html = `<div class="filter-bar">
      <select onchange="PANELS.deeds._filters.status=this.value;refreshPanel('deeds')">
        <option value="">${tx('全部状态', 'All status')}</option>
        ${['running', 'queued', 'paused', 'awaiting_eval', 'failed', 'completed', 'cancelled'].map((value) => `<option value="${value}"${this._filters.status === value ? ' selected' : ''}>${esc(deedStatusLabel(value))}</option>`).join('')}
      </select>
    </div>`;
    if (!rows.length) return html + `<div class="empty">${tx('暂无行事。', 'No deeds yet.')}</div>`;
    html += rows.map((row) => renderSubItem(
      row.title || row.deed_id || '',
      [deedStatusLabel(row.deed_status), row.slip_id || '', row.folio_id || ''].filter(Boolean).join(' · '),
      statusDot(row.deed_status || 'muted'),
      `PANELS.deeds.openDetail('${esc(row.deed_id || '')}')`
    )).join('');
    return html;
  },
  _filtered() {
    return (this._rows || []).filter((row) => !this._filters.status || String(row.deed_status || '') === this._filters.status);
  },
  async openDetail(deedId) {
    if (!deedId) return;
    pushDetail(tx('行事', 'Deed'), '<div class="loading">…</div>');
    const row = await api('/console/deeds/' + encodeURIComponent(deedId));
    let html = '';
    html += fieldText(tx('行事 ID', 'Deed ID'), row.deed_id, { mono: true });
    html += field(tx('状态', 'Status'), tag(deedStatusLabel(row.deed_status), toneForDeed(row.deed_status)));
    html += fieldText(tx('阶段', 'Phase'), row.phase || '—');
    html += fieldText(tx('签札', 'Slip'), row.slip_id || '—', { mono: true });
    html += fieldText(tx('卷', 'Folio'), row.folio_id || '—', { mono: true });
    html += fieldText(tx('成文', 'Writ'), row.writ_id || '—', { mono: true });
    html += fieldText(tx('步数预算', 'Step budget'), String(row.dag_budget || 0));
    html += fieldText(tx('结构步数', 'Move count'), String(row.move_count || 0));
    html += fieldText(tx('创建', 'Created'), fmtTime(row.created_utc));
    html += fieldText(tx('更新', 'Updated'), fmtTime(row.updated_utc));
    html += actions(..._deedActionButtons(row));
    html += sectionHeading(tx('执行结构', 'Execution structure'));
    html += renderTimeline(row.timeline || []);
    html += sectionHeading(tx('近来消息', 'Recent messages'));
    const messages = Array.isArray(row.messages) ? row.messages : [];
    html += messages.length
      ? messages.slice(-8).map((message) => `
        <div class="field">
          <div class="field-label">${esc(String(message.role || 'system'))}${message.created_utc ? ` · ${esc(fmtTime(message.created_utc))}` : ''}</div>
          <div class="field-value">${esc(tx(`第 ${Number(message.index || 0)} 条 · ${Number(message.char_count || 0)} 字`, `Message ${Number(message.index || 0)} · ${Number(message.char_count || 0)} chars`))}</div>
        </div>
      `).join('')
      : `<div class="empty">${tx('这回行事还没有消息。', 'No messages for this deed yet.')}</div>`;
    pushDetail(row.title || row.deed_id || tx('行事', 'Deed'), html);
  },
});

function _deedActionButtons(row) {
  const deedId = row.deed_id || '';
  const status = String(row.deed_status || '').toLowerCase();
  const buttons = [];
  if (status === 'paused') buttons.push(btn(tx('续行', 'Resume'), `_deedCommand('${esc(deedId)}','resume')`, 'success'));
  if (['running', 'queued'].includes(status)) buttons.push(btn(tx('停驻', 'Pause'), `_deedCommand('${esc(deedId)}','pause')`, 'ghost'));
  if (['running', 'queued', 'paused', 'cancelling'].includes(status)) buttons.push(btn(tx('止住', 'Cancel'), `_deedCommand('${esc(deedId)}','cancel')`, 'danger'));
  if (['failed', 'failed_submission', 'replay_exhausted'].includes(status)) buttons.push(btn(tx('再行一次', 'Run again'), `_deedCommand('${esc(deedId)}','retry')`, 'primary'));
  if (row.slip_id) buttons.push(btn(tx('开札', 'Open Slip'), `openPanelDetail('slips','${esc(row.slip_id)}',true)`, 'ghost'));
  if (row.folio_id) buttons.push(btn(tx('开卷', 'Open Folio'), `openPanelDetail('folios','${esc(row.folio_id)}',true)`, 'ghost'));
  return buttons;
}

async function _deedCommand(deedId, action) {
  const mapping = {
    pause: '/deeds/' + encodeURIComponent(deedId) + '/pause',
    resume: '/deeds/' + encodeURIComponent(deedId) + '/resume',
    cancel: '/deeds/' + encodeURIComponent(deedId) + '/cancel',
    retry: '/deeds/' + encodeURIComponent(deedId) + '/retry',
  };
  const endpoint = mapping[action];
  if (!endpoint) return;
  const ok = await confirmAction(
    tx('行事操作', 'Deed Action'),
    tx(`确认对这回行事执行“${action}”？`, `Run "${action}" on this deed?`)
  );
  if (!ok) return;
  try {
    await apiWrite(endpoint, 'POST', {});
    refreshPanel('deeds');
  } catch (error) {
    pushDetail(tx('错误', 'Error'), `<div class="empty">${esc(error.message)}</div>`);
  }
}
