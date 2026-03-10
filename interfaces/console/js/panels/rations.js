registerPanel('rations', {
  _data: [],
  async load() {
    const rows = await api('/console/rations');
    this._data = Array.isArray(rows) ? rows : [];
  },
  render() {
    if (!this._data.length) return `<div class="empty">${tx('暂无配给。', 'No rations yet.')}</div>`;
    return this._data.map(row => `
      <div class="list-item" onclick="PANELS.rations.openDetail('${esc(row.resource_type || '')}')">
        <div class="item-main">
          <div class="item-title">${esc(row.resource_type || '')}</div>
          <div class="item-sub">${esc(String(row.daily_limit ?? '\u2014'))} / ${tx('日', 'day')}</div>
        </div>
        ${statusDot('green')}
      </div>
    `).join('');
  },
  async openDetail(resourceType) {
    if (!resourceType) return;
    pushDetail(resourceType, '<div class="loading">\u2026</div>');
    const [ration, versions] = await Promise.all([
      api('/console/rations/' + encodeURIComponent(resourceType)),
      api('/console/rations/' + encodeURIComponent(resourceType) + '/versions').catch(() => []),
    ]);
    let html = '';
    html += fieldText(tx('\u8d44\u6e90', 'Resource'), ration.resource_type || resourceType);
    html += field(tx('\u65e5\u9650\u989d', 'Daily Limit'), `<input class="inline-input" id="ration-limit" value="${esc(String(ration.daily_limit ?? ''))}" style="width:180px">`);
    html += actions(btn(tx('\u4fdd\u5b58', 'Save'), `_saveRation('${esc(resourceType)}')`, 'success'));
    if (Array.isArray(versions) && versions.length) {
      html += `<div class="section-heading">${tx('\u7248\u672c', 'Versions')}</div>`;
      html += versions.slice(0, 12).map(version => `
        <div class="sub-item">
          <div class="item-main">
            <div class="item-title">v${version.version || 0}</div>
            <div class="item-sub">${fmtTime(version.changed_utc)} \u00b7 ${esc(version.changed_by || '')}</div>
          </div>
          <button class="btn danger" style="padding:4px 10px;font-size:11px" onclick="_rollbackRation('${esc(resourceType)}',${version.version || 0})">${tx('\u56de\u6eda', 'Rollback')}</button>
        </div>
      `).join('');
    }
    pushDetail(resourceType, html);
  }
});

async function _saveRation(resourceType) {
  const input = document.getElementById('ration-limit');
  if (!input) return;
  const daily_limit = String(input.value || '').trim();
  const ok = await confirmAction(
    tx('保存配给', 'Save Ration'),
    tx(`\u786e\u8ba4\u5c06 ${resourceType} \u66f4\u65b0\u4e3a ${daily_limit}\uff1f`, `Set ${resourceType} to ${daily_limit}?`)
  );
  if (!ok) return;
  try {
    await apiWrite('/console/rations/' + encodeURIComponent(resourceType), 'PUT', { daily_limit });
    refreshPanel('rations');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}

async function _rollbackRation(resourceType, version) {
  const ok = await confirmAction(
    tx('回滚配给', 'Rollback Ration'),
    tx(`\u786e\u8ba4\u56de\u6eda ${resourceType} \u5230 v${version}\uff1f`, `Rollback ${resourceType} to v${version}?`)
  );
  if (!ok) return;
  try {
    await apiWrite('/console/rations/' + encodeURIComponent(resourceType) + '/rollback/' + version, 'POST', {});
    refreshPanel('rations');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}
