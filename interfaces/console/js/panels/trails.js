registerPanel('trails', {
  _data: [],
  _filters: { routine: '', status: '', range: 'last_24h' },
  _routines: [],
  async load() {
    if (!this._routines.length) {
      try { this._routines = (await api('/console/routines')).map(r => r.routine); } catch (_) {}
    }
    const f = this._filters;
    const now = new Date();
    const toIso = d => d.toISOString().replace(/\.\d{3}Z$/, 'Z');
    let since = '';
    if (f.range === 'last_1h') since = toIso(new Date(now.getTime() - 3600e3));
    else if (f.range === 'last_6h') since = toIso(new Date(now.getTime() - 6 * 3600e3));
    else if (f.range === 'last_24h') since = toIso(new Date(now.getTime() - 24 * 3600e3));
    else if (f.range === 'last_7d') since = toIso(new Date(now.getTime() - 7 * 86400e3));
    let url = '/console/trails?limit=200';
    if (f.routine) url += '&routine=' + encodeURIComponent(f.routine);
    if (f.status) url += '&status=' + f.status;
    if (since) url += '&since=' + encodeURIComponent(since);
    this._data = await api(url);
  },
  render() {
    const f = this._filters;
    let html = `<div class="filter-bar">`;
    html += `<select onchange="PANELS.trails._filters.routine=this.value;showPanel('trails',true)">`;
    html += `<option value="">${tx('全部例行', 'All routines')}</option>`;
    html += this._routines.map(r => `<option value="${esc(r)}"${f.routine === r ? ' selected' : ''}>${esc(r)}</option>`).join('');
    html += `</select>`;
    html += `<select onchange="PANELS.trails._filters.status=this.value;showPanel('trails',true)">`;
    html += `<option value=""${!f.status ? ' selected' : ''}>${tx('\u4efb\u610f\u72b6\u6001', 'Any status')}</option>`;
    html += ['ok', 'error'].map(s => `<option value="${s}"${f.status === s ? ' selected' : ''}>${s}</option>`).join('');
    html += `</select>`;
    html += `<select onchange="PANELS.trails._filters.range=this.value;showPanel('trails',true)">`;
    html += [['last_1h', tx('\u8fd1 1h', 'Last 1h')], ['last_6h', tx('\u8fd1 6h', 'Last 6h')], ['last_24h', tx('\u8fd1 24h', 'Last 24h')], ['last_7d', tx('\u8fd1 7d', 'Last 7d')]]
      .map(([v, l]) => `<option value="${v}"${f.range === v ? ' selected' : ''}>${l}</option>`).join('');
    html += `</select></div>`;

    if (!this._data.length) {
      html += `<div class="empty">${tx('暂无踪迹。', 'No trails yet.')}</div>`;
      return html;
    }
    html += this._data.slice(0, 100).map(t => `
      <div class="list-item" onclick="PANELS.trails.openDetail('${esc(t.trail_id || '')}')">
        <div class="item-main">
          <div class="item-title">${esc(t.routine || '')}</div>
          <div class="item-sub">${fmtTime(t.started_utc)} \u00b7 ${t.elapsed_s || 0}s${t.degraded ? ' \u00b7 ' + tx('降级', 'degraded') : ''}</div>
        </div>
        ${statusDot(t.status || 'muted')}
      </div>
    `).join('');
    if (this._data.length > 100) {
      html += `<div class="empty">${tx('\u663e\u793a\u524d 100 \u6761\uff0c\u5171', 'Showing first 100 of ')}${this._data.length}</div>`;
    }
    return html;
  },
  async openDetail(trailId) {
    pushDetail(tx('\u52a0\u8f7d\u4e2d\u2026', 'Loading\u2026'), '<div class="loading">\u2026</div>');
    try {
      const t = await api('/console/trails/' + encodeURIComponent(trailId));
      let html = '';
      html += fieldText(tx('踪迹 ID', 'Trail ID'), t.trail_id || trailId, { mono: true });
      html += fieldText(tx('例行', 'Routine'), t.routine);
      html += field(tx('\u72b6\u6001', 'Status'), tag(t.status || '', t.status === 'ok' ? 'ok' : 'error') + (t.degraded ? ' ' + tag(tx('降级', 'Degraded'), 'warn') : ''));
      html += fieldText(tx('\u5f00\u59cb\u65f6\u95f4', 'Started'), fmtTime(t.started_utc));
      html += fieldText(tx('\u8017\u65f6', 'Elapsed'), (t.elapsed_s || 0) + 's');
      if (t.error) html += fieldText(tx('\u9519\u8bef', 'Error'), t.error);

      const moves = Array.isArray(t.moves || t.steps) ? (t.moves || t.steps) : [];
      if (moves.length) {
        html += `<div class="section-heading">${tx('步骤', 'Moves')}</div>`;
        html += moves.map(m => `
          <div class="sub-item">
            <div class="item-main">
              <div class="item-title">${esc(m.name || 'move')}</div>
              <div class="item-sub">${m.t ?? 0}s</div>
            </div>
          </div>
        `).join('');
      }

      const cs = t.cortex_summary || {};
      if (cs.total_calls) {
        html += `<div class="section-heading">${tx('Cortex 概览', 'Cortex Summary')}</div>`;
        html += fieldText(tx('\u603b\u8c03\u7528', 'Total Calls'), String(cs.total_calls || 0));
        html += fieldText(tx('输入 Tokens', 'Input Tokens'), (cs.total_in_tokens || 0).toLocaleString());
        html += fieldText(tx('输出 Tokens', 'Output Tokens'), (cs.total_out_tokens || 0).toLocaleString());
        const bp = cs.by_provider || {};
        if (Object.keys(bp).length) {
          html += `<div class="section-heading">${tx('按提供方', 'By Provider')}</div>`;
          html += Object.entries(bp).map(([p, v]) => `
            <div class="sub-item">
              <div class="item-main">
                <div class="item-title">${esc(p)}</div>
                <div class="item-sub">${v.calls || 0} ${tx('\u8c03\u7528', 'calls')} \u00b7 ${(v.in_tokens || 0).toLocaleString()} in \u00b7 ${(v.out_tokens || 0).toLocaleString()} out${v.errors ? ` \u00b7 ${v.errors} ${tx('\u9519\u8bef', 'errors')}` : ''}</div>
              </div>
            </div>
          `).join('');
        }
      }
      pushDetail(t.trail_id || trailId, html);
    } catch (e) {
      pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
    }
  }
});
