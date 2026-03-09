registerPanel('overview', {
  _data: null,
  _retinue: null,
  async load() {
    [this._data, this._retinue] = await Promise.all([
      api('/console/dashboard'),
      api('/console/retinue').catch(() => null),
    ]);
    const d = this._data || {};
    updateWard(d.ward?.status || 'GREEN');
    updateSummary(d.running_deeds || 0, d.awaiting_eval || 0);
  },
  render() {
    const d = this._data || {};
    const r = this._retinue || {};
    const ward = d.ward?.status || 'GREEN';
    const running = d.running_deeds || 0;
    const awaiting = d.awaiting_eval || 0;

    const wardLabel = { GREEN: 'Healthy', YELLOW: 'Degraded', RED: 'Blocked' }[ward] || ward;
    let html = `<div class="summary-row">`;
    html += _card(wardLabel, 'Ward');
    html += _card(running, 'Running Deeds');
    html += _card(awaiting, 'Awaiting Review');
    html += _card(`${r.occupied || 0}/${r.total || 0}`, 'Retinue Occupied');
    html += `</div>`;

    const usage = d.cortex_usage?.by_provider || {};
    html += `<div class="section-heading">Cortex Usage Today</div>`;
    const providers = Object.entries(usage);
    if (!providers.length) {
      html += `<div class="empty">${tx('\u4eca\u5929\u6682\u65e0\u8c03\u7528', 'No calls today')}</div>`;
    } else {
      html += providers.map(([p, u]) => `
        <div class="list-item static">
          <div class="item-main">
            <div class="item-title">${esc(p)}</div>
            <div class="item-sub">${u.calls || 0} ${tx('\u8c03\u7528', 'calls')} \u00b7 ${(u.in_tokens || 0).toLocaleString()} in \u00b7 ${(u.out_tokens || 0).toLocaleString()} out${u.errors ? ` \u00b7 ${u.errors} ${tx('\u9519\u8bef', 'errors')}` : ''}</div>
          </div>
        </div>
      `).join('');
    }
    return html;
  }
});

function _card(val, label) {
  return `<div class="summary-card"><div class="summary-val">${esc(String(val))}</div><div class="summary-label">${esc(label)}</div></div>`;
}
