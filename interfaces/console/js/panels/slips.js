registerPanel('slips', {
  _rows: [],
  _filters: { status: '', standing: '' },
  async load() {
    this._rows = await api('/console/slips?limit=400');
  },
  render() {
    const rows = this._filtered();
    let html = `<div class="filter-bar">
      <select onchange="PANELS.slips._filters.status=this.value;refreshPanel('slips')">
        <option value="">${tx('全部状态', 'All status')}</option>
        ${['active', 'parked', 'settled', 'archived', 'absorbed'].map((value) => `<option value="${value}"${this._filters.status === value ? ' selected' : ''}>${esc(slipStatusLabel(value))}</option>`).join('')}
      </select>
      <select onchange="PANELS.slips._filters.standing=this.value;refreshPanel('slips')">
        <option value="">${tx('全部形态', 'All kinds')}</option>
        <option value="standing"${this._filters.standing === 'standing' ? ' selected' : ''}>${tx('常札', 'Standing')}</option>
        <option value="ordinary"${this._filters.standing === 'ordinary' ? ' selected' : ''}>${tx('普通签札', 'Ordinary')}</option>
      </select>
    </div>`;
    if (!rows.length) return html + `<div class="empty">${tx('暂无签札。', 'No slips yet.')}</div>`;
    html += rows.map((row) => renderSubItem(
      row.title || row.slip_id || '',
      [
        slipStatusLabel(row.status),
        row.folio_id || tx('未入卷', 'Loose'),
        row.deed_count ? `${row.deed_count} ${tx('次行事', 'deeds')}` : '',
      ].filter(Boolean).join(' · '),
      statusDot(row.status || 'muted'),
      `PANELS.slips.openDetail('${esc(row.slip_id || '')}')`
    )).join('');
    return html;
  },
  _filtered() {
    return (this._rows || []).filter((row) => {
      if (this._filters.status && String(row.status || '') !== this._filters.status) return false;
      if (this._filters.standing === 'standing' && !row.standing) return false;
      if (this._filters.standing === 'ordinary' && row.standing) return false;
      return true;
    });
  },
  async openDetail(slipId) {
    if (!slipId) return;
    pushDetail(tx('签札', 'Slip'), '<div class="loading">…</div>');
    const row = await api('/console/slips/' + encodeURIComponent(slipId));
    const moves = Array.isArray(row.design?.moves) ? row.design.moves : [];
    const timeline = moves.map((move, index) => ({
      label: String(move.instruction || move.message || move.title || `${tx('步骤', 'Step')} ${index + 1}`),
      state: 'pending',
      agent: String(move.agent || ''),
    }));
    let html = '';
    html += fieldText(tx('签札 ID', 'Slip ID'), row.slip_id, { mono: true });
    html += field(tx('状态', 'Status'), tag(slipStatusLabel(row.status), toneForSlip(row.status)));
    html += fieldText(tx('卷', 'Folio'), row.folio_id || '—', { mono: true });
    html += fieldText(tx('姿态', 'Posture'), row.standing ? tx('常札', 'Standing') : tx('普通签札', 'Ordinary'));
    html += fieldText(tx('步数预算', 'Step budget'), String(row.dag_budget || 0));
    html += fieldText(tx('结构步数', 'Move count'), String(row.move_count || 0));
    html += fieldText(tx('最近一回行事', 'Latest deed'), row.latest_deed_id || '—', { mono: true });
    html += fieldText(tx('创建', 'Created'), fmtTime(row.created_utc));
    html += fieldText(tx('更新', 'Updated'), fmtTime(row.updated_utc));
    html += fieldText(tx('目标', 'Objective'), row.objective || '—');
    html += actions(..._slipActionButtons(row));
    html += sectionHeading(tx('结构', 'Structure'));
    html += renderTimeline(timeline);
    html += sectionHeading(tx('历次行事', 'Deed history'));
    const deeds = Array.isArray(row.deeds) ? row.deeds : [];
    html += deeds.length
      ? deeds.map((deed) => renderSubItem(
          deed.title || deed.deed_id || '',
          [deedStatusLabel(deed.deed_status), deed.updated_utc ? fmtTime(deed.updated_utc) : ''].filter(Boolean).join(' · '),
          statusDot(deed.deed_status || 'muted'),
          `openPanelDetail('deeds','${esc(deed.deed_id || '')}',true)`
        )).join('')
      : `<div class="empty">${tx('这张签札还没有行事记录。', 'No deed has arisen from this slip yet.')}</div>`;
    pushDetail(row.title || row.slip_id || tx('签札', 'Slip'), html);
  },
});

function _slipActionButtons(row) {
  const slipId = row.slip_id || '';
  const status = String(row.status || '').toLowerCase();
  const buttons = [];
  if (status !== 'active') buttons.push(btn(tx('续办', 'Activate'), `_mutateSlip('${esc(slipId)}','activate')`, 'success'));
  if (status !== 'parked') buttons.push(btn(tx('搁置', 'Park'), `_mutateSlip('${esc(slipId)}','park')`, 'ghost'));
  if (status !== 'archived') buttons.push(btn(tx('收起', 'Archive'), `_mutateSlip('${esc(slipId)}','archive')`, 'danger'));
  if (row.folio_id) buttons.push(btn(tx('开卷', 'Open Folio'), `openPanelDetail('folios','${esc(row.folio_id)}',true)`, 'ghost'));
  return buttons;
}

async function _mutateSlip(slipId, action) {
  const ok = await confirmAction(
    tx('签札操作', 'Slip Action'),
    tx(`确认对这张签札执行“${action}”？`, `Run "${action}" on this slip?`)
  );
  if (!ok) return;
  try {
    await apiWrite('/console/slips/' + encodeURIComponent(slipId) + '/' + encodeURIComponent(action), 'POST', {});
    refreshPanel('slips');
  } catch (error) {
    pushDetail(tx('错误', 'Error'), `<div class="empty">${esc(error.message)}</div>`);
  }
}
