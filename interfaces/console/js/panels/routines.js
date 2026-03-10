registerPanel('routines', {
  _data: [],
  async load() {
    this._data = await api('/console/routines');
  },
  render() {
    if (!this._data.length) return `<div class="empty">${tx('暂无例行。', 'No routines yet.')}</div>`;
    return this._data.map(r => `
      <div class="list-item" onclick="PANELS.routines.openDetail('${esc(r.routine)}')">
        <div class="item-main">
          <div class="item-title">${esc(r.routine)}</div>
          <div class="item-sub">${esc(r.schedule || '\u2014')} \u00b7 ${esc(r.mode || '')}${r.last_run_utc ? ' \u00b7 ' + fmtTime(r.last_run_utc) : ''}</div>
        </div>
        ${statusDot(r.enabled !== false ? 'enabled' : 'disabled')}
      </div>
    `).join('');
  },
  async openDetail(routine) {
    const r = this._data.find(x => x.routine === routine);
    if (!r) return;
    pushDetail(r.routine, '<div class="loading">\u2026</div>');
    const enabled = r.enabled !== false;
    const shortName = r.routine.replace('spine.', '');
    let html = '';
    html += field('Mode', tag(r.mode || '\u2014', r.mode === 'hybrid' ? 'info' : 'dim'));
    html += field('Schedule', esc(r.schedule || '\u2014'), { mono: true });
    html += field(tx('\u72b6\u6001', 'Status'), enabled ? tag(tx('\u542f\u7528', 'Enabled'), 'ok') : tag(tx('\u7981\u7528', 'Disabled'), 'dim'));
    html += fieldText('Last Run', fmtTime(r.last_run_utc));
    html += fieldText('Next Run', fmtTime(r.next_run_utc));
    html += actions(
      btn(tx('\u7acb\u5373\u89e6\u53d1', 'Trigger Now'), `_triggerRoutine('${esc(shortName)}')`, 'primary'),
      btn(enabled ? tx('\u7981\u7528', 'Disable') : tx('\u542f\u7528', 'Enable'),
        `_toggleRoutine('${esc(r.routine)}')`,
        enabled ? 'danger' : 'success')
    );

    // Load and append history
    try {
      const history = await api('/console/routines/history?limit=20&routine=' + encodeURIComponent(r.routine));
      if (history && history.length) {
        html += `<div class="section-heading">${tx('执行记录', 'Execution History')}</div>`;
        html += history.slice(0, 10).map(h => `
          <div class="sub-item">
            <div class="item-main">
              <div class="item-title">${fmtTime(h.run_utc)}</div>
              <div class="item-sub">${esc(h.trigger || '')} \u00b7 ${esc(h.status || '')}</div>
            </div>
            ${statusDot(h.status === 'ok' ? 'ok' : 'error')}
          </div>
        `).join('');
      }
    } catch (_) {}

    pushDetail(r.routine, html);
  }
});

async function _triggerRoutine(name) {
  const ok = await confirmAction(
    tx('触发例行', 'Trigger Routine'),
    tx(`\u786e\u8ba4\u7acb\u5373\u89e6\u53d1 ${name}\uff1f`, `Trigger ${name} now?`)
  );
  if (!ok) return;
  try {
    await apiWrite('/console/routines/' + encodeURIComponent(name) + '/trigger', 'POST', null);
    refreshPanel('routines');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}

async function _toggleRoutine(routine) {
  const row = PANELS.routines._data.find(r => r.routine === routine);
  if (!row) return;
  const currentEnabled = row.enabled !== false;
  const action = currentEnabled ? tx('\u7981\u7528', 'Disable') : tx('\u542f\u7528', 'Enable');
  const ok = await confirmAction(
    tx('切换例行', 'Toggle Routine'),
    tx(`${action} ${routine}\uff1f`, `${action} ${routine}?`)
  );
  if (!ok) return;
  try {
    await apiWrite('/console/routines/' + encodeURIComponent(routine), 'PUT', { enabled: !currentEnabled });
    refreshPanel('routines');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}
