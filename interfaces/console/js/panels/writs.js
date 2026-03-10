registerPanel('writs', {
  _rows: [],
  _filters: { status: '' },
  async load() {
    this._rows = await api('/console/writs?limit=400');
  },
  render() {
    const rows = this._filtered();
    let html = `<div class="filter-bar">
      <select onchange="PANELS.writs._filters.status=this.value;refreshPanel('writs')">
        <option value="">${tx('全部状态', 'All status')}</option>
        ${['active', 'paused', 'disabled'].map((value) => `<option value="${value}"${this._filters.status === value ? ' selected' : ''}>${esc(writStatusLabel(value))}</option>`).join('')}
      </select>
    </div>`;
    if (!rows.length) return html + `<div class="empty">${tx('暂无成文。', 'No writs yet.')}</div>`;
    html += rows.map((row) => renderSubItem(
      row.title || row.writ_id || '',
      [_writMatchSummary(row.match || {}), row.folio_id || ''].filter(Boolean).join(' · '),
      statusDot(row.status || 'muted'),
      `PANELS.writs.openDetail('${esc(row.writ_id || '')}')`
    )).join('');
    return html;
  },
  _filtered() {
    return (this._rows || []).filter((row) => !this._filters.status || String(row.status || '') === this._filters.status);
  },
  async openDetail(writId) {
    if (!writId) return;
    pushDetail(tx('成文', 'Writ'), '<div class="loading">…</div>');
    const row = await api('/console/writs/' + encodeURIComponent(writId));
    let html = '';
    html += fieldText(tx('成文 ID', 'Writ ID'), row.writ_id, { mono: true });
    html += field(tx('状态', 'Status'), tag(writStatusLabel(row.status), toneForWrit(row.status)));
    html += fieldText(tx('所属卷', 'Folio'), row.folio_id || '—', { mono: true });
    html += fieldText(tx('优先级', 'Priority'), String(row.priority ?? '—'));
    html += fieldText(tx('版本', 'Version'), String(row.version ?? '—'));
    html += fieldText(tx('最近触发', 'Last triggered'), row.last_triggered_utc ? fmtTime(row.last_triggered_utc) : '—');
    html += fieldText(tx('触发句式', 'Trigger'), _writMatchSummary(row.match || {}));
    html += fieldText(tx('应事动作', 'Action'), _writActionSummary(row.action || {}));
    if (row.suppression && Object.keys(row.suppression).length) {
      html += fieldText(tx('抑制条件', 'Suppression'), shortJsonSummary(row.suppression));
    }
    html += actions(..._writActionButtons(row));
    html += sectionHeading(tx('最近行事', 'Recent deeds'));
    const recent = Array.isArray(row.recent_deeds) ? row.recent_deeds : [];
    html += recent.length
      ? recent.map((deed) => renderSubItem(
          deed.title || deed.deed_id || '',
          [deedStatusLabel(deed.deed_status), deed.updated_utc ? fmtTime(deed.updated_utc) : ''].filter(Boolean).join(' · '),
          statusDot(deed.deed_status || 'muted'),
          `openPanelDetail('deeds','${esc(deed.deed_id || '')}',true)`
        )).join('')
      : `<div class="empty">${tx('这条成文还没有催生新的行事。', 'This writ has not produced a recent deed yet.')}</div>`;
    pushDetail(row.title || row.writ_id || tx('成文', 'Writ'), html);
  },
});

function _writMatchSummary(match) {
  const eventName = String(match.event || '').trim();
  const schedule = String(match.schedule || '').trim();
  const filters = match.filter && typeof match.filter === 'object' ? Object.keys(match.filter) : [];
  const parts = [];
  if (eventName) parts.push(eventName);
  if (schedule) parts.push(schedule);
  if (filters.length) parts.push(`${filters.length} ${tx('个过滤键', 'filters')}`);
  return parts.join(' · ') || '—';
}

function _writActionSummary(action) {
  const type = String(action.type || '').trim();
  const slipId = String(action.slip_id || '').trim();
  const template = action.brief_template && typeof action.brief_template === 'object' ? Object.keys(action.brief_template) : [];
  const parts = [];
  if (type) parts.push(type);
  if (slipId) parts.push(slipId);
  if (template.length) parts.push(`${template.length} ${tx('个模板键', 'template keys')}`);
  return parts.join(' · ') || '—';
}

function _writActionButtons(row) {
  const writId = row.writ_id || '';
  const status = String(row.status || '').toLowerCase();
  const buttons = [];
  if (status !== 'active') buttons.push(btn(tx('启用', 'Activate'), `_mutateWrit('${esc(writId)}','activate')`, 'success'));
  if (status !== 'paused') buttons.push(btn(tx('暂停', 'Pause'), `_mutateWrit('${esc(writId)}','pause')`, 'ghost'));
  if (status !== 'disabled') buttons.push(btn(tx('停用', 'Disable'), `_mutateWrit('${esc(writId)}','disable')`, 'danger'));
  buttons.push(btn(tx('删除', 'Delete'), `_mutateWrit('${esc(writId)}','delete')`, 'danger'));
  if (row.folio_id) buttons.push(btn(tx('开卷', 'Open Folio'), `openPanelDetail('folios','${esc(row.folio_id)}',true)`, 'ghost'));
  return buttons;
}

async function _mutateWrit(writId, action) {
  const ok = await confirmAction(
    tx('成文操作', 'Writ Action'),
    tx(`确认对这条成文执行“${action}”？`, `Run "${action}" on this writ?`)
  );
  if (!ok) return;
  try {
    await apiWrite('/console/writs/' + encodeURIComponent(writId) + '/' + encodeURIComponent(action), 'POST', {});
    refreshPanel('writs');
  } catch (error) {
    pushDetail(tx('错误', 'Error'), `<div class="empty">${esc(error.message)}</div>`);
  }
}
