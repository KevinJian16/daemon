registerPanel('norm', {
  _data: [],
  async load() {
    this._data = await api('/console/norm/rations');
  },
  render() {
    if (!this._data || !this._data.length) return `<div class="empty">No Rations</div>`;
    return this._data.map(b => {
      const usage = Number(b.current_usage || 0);
      const limit = Number(b.daily_limit || 0);
      const pct = limit > 0 ? Math.round(usage / limit * 100) : 0;
      return `
        <div class="list-item" onclick="PANELS.norm.openDetail('${esc(b.resource_type || '')}')">
          <div class="item-main">
            <div class="item-title">${esc(humanize(b.resource_type))}</div>
            <div class="item-sub">${usage.toLocaleString()} / ${limit.toLocaleString()} (${pct}%)</div>
          </div>
          ${statusDot(pct >= 90 ? 'red' : pct >= 70 ? 'amber' : 'green')}
        </div>
      `;
    }).join('');
  },
  openDetail(key) {
    const b = this._data.find(x => x.resource_type === key);
    if (!b) return;
    const usage = Number(b.current_usage || 0);
    const limit = Number(b.daily_limit || 0);
    let html = '';
    html += fieldText(tx('\u5f53\u524d\u7528\u91cf', 'Current Usage'), usage.toLocaleString());
    html += field(tx('\u65e5\u9650\u989d', 'Daily Limit'),
      `<input type="number" class="inline-input" id="ration-limit" value="${limit}" min="0" style="width:140px">`);
    html += actions(
      btn(tx('\u4fdd\u5b58', 'Save'), `_saveRation('${esc(key)}')`, 'success')
    );
    pushDetail(humanize(b.resource_type), html);
  }
});

async function _saveRation(key) {
  const input = document.getElementById('ration-limit');
  if (!input) return;
  const dailyLimit = Number(input.value);
  if (!Number.isFinite(dailyLimit) || dailyLimit < 0) return;
  const ok = await confirmAction(
    'Update Ration',
    tx(`\u786e\u8ba4\u5c06 ${humanize(key)} \u7684\u65e5\u9650\u989d\u4fee\u6539\u4e3a ${dailyLimit.toLocaleString()}\uff1f`, `Set daily limit for ${humanize(key)} to ${dailyLimit.toLocaleString()}?`)
  );
  if (!ok) return;
  try {
    await apiWrite('/console/norm/rations/' + encodeURIComponent(key), 'PUT', { daily_limit: dailyLimit });
    refreshPanel('norm');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}

