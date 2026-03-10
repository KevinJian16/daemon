registerPanel('overview', {
  _dashboard: null,
  _retinue: null,
  _drafts: [],
  _slips: [],
  _folios: [],
  _writs: [],
  _deeds: [],
  _routines: [],
  async load() {
    const [dashboard, retinue, drafts, slips, folios, writs, deeds, routines] = await Promise.all([
      api('/console/dashboard'),
      api('/console/retinue').catch(() => null),
      api('/console/drafts?limit=6').catch(() => []),
      api('/console/slips?limit=6').catch(() => []),
      api('/console/folios?limit=6').catch(() => []),
      api('/console/writs?limit=6').catch(() => []),
      api('/console/deeds?limit=8').catch(() => []),
      api('/console/routines').catch(() => []),
    ]);
    this._dashboard = dashboard || {};
    this._retinue = retinue || {};
    this._drafts = Array.isArray(drafts) ? drafts : [];
    this._slips = Array.isArray(slips) ? slips : [];
    this._folios = Array.isArray(folios) ? folios : [];
    this._writs = Array.isArray(writs) ? writs : [];
    this._deeds = Array.isArray(deeds) ? deeds : [];
    this._routines = Array.isArray(routines) ? routines : [];
    updateWard(this._dashboard.ward?.status || 'GREEN');
    updateSummary(this._dashboard.running_deeds || 0, this._dashboard.awaiting_eval || 0, this._dashboard.system_status || '');
  },
  render() {
    const dashboard = this._dashboard || {};
    const retinue = this._retinue || {};
    const faultedRoutines = (this._routines || []).filter((row) => row.enabled !== false && String(row.last_status || '').toLowerCase() === 'error');
    const liveDeeds = (this._deeds || []).filter((row) => ['running', 'queued', 'paused', 'cancelling', 'awaiting_eval'].includes(String(row.deed_status || '')));

    let html = '<div class="summary-row">';
    html += _overviewCard(dashboard.ward?.status || 'GREEN', tx('结界', 'Ward'));
    html += _overviewCard(dashboard.running_deeds || 0, tx('行事中', 'Running'));
    html += _overviewCard(dashboard.awaiting_eval || 0, tx('待阅看', 'Awaiting Review'));
    html += _overviewCard(dashboard.active_folios || 0, tx('活跃卷', 'Active Folios'));
    html += _overviewCard(dashboard.active_slips || 0, tx('活跃签札', 'Active Slips'));
    html += _overviewCard(dashboard.active_writs || 0, tx('生效成文', 'Active Writs'));
    html += _overviewCard(`${retinue.occupied || 0}/${retinue.total || 0}`, tx('随从占用', 'Retinue Load'));
    html += _overviewCard(dashboard.storage_ready ? tx('就绪', 'Ready') : tx('缺失', 'Missing'), tx('存储', 'Storage'));
    html += '</div>';

    html += sectionHeading(tx('先看哪里', 'What needs attention first'));
    html += '<div class="overview-grid">';
    html += _overviewTile(
      tx('未落札草稿', 'Open drafts'),
      String(dashboard.open_drafts || 0),
      tx('先看哪些意图还在收敛。', 'Check which intentions are still converging.'),
      "showPanel('drafts', true)",
      dashboard.open_drafts ? 'warn' : 'dim'
    );
    html += _overviewTile(
      tx('未做成行事', 'Failed deeds'),
      String(dashboard.failed_24h || 0),
      tx('先看最近一日里哪几回行事没有做成。', 'Inspect deeds that failed in the last day.'),
      "showPanel('deeds', true)",
      dashboard.failed_24h ? 'error' : 'dim'
    );
    html += _overviewTile(
      tx('搁置中的卷', 'Parked folios'),
      String(dashboard.parked_folios || 0),
      tx('看哪些卷被先搁在一旁。', 'Review folios currently set aside.'),
      "showPanel('folios', true)",
      dashboard.parked_folios ? 'warn' : 'dim'
    );
    html += _overviewTile(
      tx('失衡例行', 'Faulted routines'),
      String(faultedRoutines.length),
      tx('检查例行和节律是否偏离。', 'Inspect routines that drifted out of line.'),
      "showPanel('routines', true)",
      faultedRoutines.length ? 'error' : 'dim'
    );
    html += '</div>';

    html += sectionHeading(tx('正在行事', 'Live deeds'));
    if (!liveDeeds.length) {
      html += `<div class="empty">${tx('眼下没有需要盯住的行事。', 'No live deed needs attention right now.')}</div>`;
    } else {
      html += liveDeeds.slice(0, 6).map((row) => renderSubItem(
        row.title || row.deed_id || '',
        [deedStatusLabel(row.deed_status), row.slip_id, row.folio_id].filter(Boolean).join(' · '),
        statusDot(row.deed_status || 'muted'),
        `openPanelDetail('deeds','${esc(row.deed_id || '')}',true)`
      )).join('');
    }

    html += sectionHeading(tx('近来的卷', 'Recent folios'));
    if (!this._folios.length) {
      html += `<div class="empty">${tx('眼下还没有卷。', 'No folios yet.')}</div>`;
    } else {
      html += this._folios.slice(0, 6).map((row) => renderSubItem(
        row.title || row.folio_id || '',
        `${row.slip_count || 0} ${tx('签札', 'slips')} · ${row.writ_count || 0} ${tx('成文', 'writs')}`,
        statusDot(row.status || 'muted'),
        `openPanelDetail('folios','${esc(row.folio_id || '')}',true)`
      )).join('');
    }

    html += sectionHeading(tx('近来的草稿', 'Recent drafts'));
    if (!this._drafts.length) {
      html += `<div class="empty">${tx('眼下还没有草稿。', 'No drafts yet.')}</div>`;
    } else {
      html += this._drafts.slice(0, 6).map((row) => renderSubItem(
        row.intent_snapshot || row.draft_id || '',
        [draftStatusLabel(row.status), row.source || 'manual'].filter(Boolean).join(' · '),
        statusDot(row.status || 'muted'),
        `openPanelDetail('drafts','${esc(row.draft_id || '')}',true)`
      )).join('');
    }

    return html;
  },
});

function _overviewCard(value, label) {
  return `<div class="summary-card"><div class="summary-val">${esc(String(value))}</div><div class="summary-label">${esc(label)}</div></div>`;
}

function _overviewTile(title, value, copy, onclick, tone) {
  return `
    <button class="overview-tile ${tone || 'dim'}" onclick="${esc(onclick)}">
      <div class="overview-tile-top">
        <div class="overview-tile-title">${esc(title)}</div>
        <div class="overview-tile-value">${esc(value)}</div>
      </div>
      <div class="overview-tile-sub">${esc(copy)}</div>
    </button>
  `;
}
