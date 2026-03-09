registerPanel('model', {
  _agents: [],
  _usage: null,
  _versions: [],
  _policy: {},
  _canonModels: [],
  async load() {
    const [policy, registry, usage, policyV, registryV] = await Promise.all([
      api('/console/model-policy'),
      api('/console/model-canon'),
      api('/console/model-usage?limit=1000').catch(() => null),
      api('/console/model-policy/versions?limit=30').catch(() => []),
      api('/console/model-canon/versions?limit=30').catch(() => []),
    ]);
    this._policy = policy || {};
    this._canonModels = [];
    if (Array.isArray(registry?.models)) {
      this._canonModels = registry.models
        .filter(m => m && typeof m === 'object' && m.alias)
        .map(m => ({ alias: m.alias, model_id: m.model_id || m.alias, provider: m.provider || '' }));
    }
    const agentMap = this._policy.agent_model_map || {};
    const ROLES = ['counsel', 'scout', 'sage', 'artificer', 'arbiter', 'scribe', 'envoy'];
    this._agents = ROLES.map(a => ({ agent: a, model: agentMap[a] || '' }));
    this._usage = usage?.summary || {};
    const vRows = [];
    for (const v of (policyV || [])) vRows.push({ target: 'model_policy', ...v });
    for (const v of (registryV || [])) vRows.push({ target: 'canon', ...v });
    vRows.sort((a, b) => String(b.changed_utc || '').localeCompare(String(a.changed_utc || '')));
    this._versions = vRows;
  },
  _modelName(alias) {
    if (!alias) return '\u2014';
    const m = this._canonModels.find(x => x.alias === alias);
    return m ? m.model_id : alias;
  },
  render() {
    let html = this._agents.map(a => `
      <div class="list-item" onclick="PANELS.model.openDetail('${esc(a.agent)}')">
        <div class="item-main">
          <div class="item-title">${esc(a.agent)}</div>
          <div class="item-sub">${esc(this._modelName(a.model))}</div>
        </div>
        ${statusDot(a.model ? 'green' : 'muted')}
      </div>
    `).join('');

    const byProvider = this._usage?.by_provider || {};
    const providers = Object.entries(byProvider);
    if (providers.length) {
      const totalCalls = providers.reduce((s, [, v]) => s + (v.calls || 0), 0);
      html += `
        <div class="list-item" onclick="PANELS.model.openDetail('_usage')">
          <div class="item-main">
            <div class="item-title">Usage Summary</div>
            <div class="item-sub">${totalCalls} ${tx('\u8c03\u7528', 'calls')} \u00b7 ${providers.length} ${tx('\u63d0\u4f9b\u65b9', 'providers')}</div>
          </div>
        </div>`;
    }

    if (this._versions.length) {
      html += `
        <div class="list-item" onclick="PANELS.model.openDetail('_versions')">
          <div class="item-main">
            <div class="item-title">Config History</div>
            <div class="item-sub">${this._versions.length} ${tx('\u6761\u8bb0\u5f55', 'versions')}</div>
          </div>
        </div>`;
    }
    return html;
  },
  openDetail(key) {
    if (key === '_usage') return this._renderUsage();
    if (key === '_versions') return this._renderVersions();
    this._renderAgent(key);
  },
  _renderAgent(agent) {
    const a = this._agents.find(x => x.agent === agent);
    if (!a) return;
    const knownAliases = new Set(this._canonModels.map(m => m.alias));
    const extras = Object.values(this._policy.agent_model_map || {}).filter(v => v && !knownAliases.has(v));
    const allOptions = [
      ...this._canonModels,
      ...extras.map(alias => ({ alias, model_id: alias, provider: '' })),
    ];
    const options = allOptions.map(m => `<option value="${esc(m.alias)}"${m.alias === a.model ? ' selected' : ''}>${esc(m.model_id)}</option>`).join('');
    let html = '';
    html += fieldText(tx('\u5f53\u524d\u6a21\u578b', 'Current Model'), this._modelName(a.model));
    html += field(tx('\u66f4\u6362\u6a21\u578b', 'Change Model'),
      `<select class="inline-select" id="model-sel-${esc(a.agent)}"><option value="">\u2014</option>${options}</select>`);
    html += actions(
      btn(tx('\u4fdd\u5b58', 'Save'), `_saveAgentModel('${esc(a.agent)}')`, 'success')
    );
    pushDetail(a.agent, html);
  },
  _renderUsage() {
    const byProvider = this._usage?.by_provider || {};
    const providers = Object.entries(byProvider).sort((a, b) => (b[1]?.calls || 0) - (a[1]?.calls || 0));
    let html = '';
    if (!providers.length) {
      html = `<div class="empty">No usage data</div>`;
    } else {
      html += providers.map(([p, v]) => `
        <div class="sub-item">
          <div class="item-main">
            <div class="item-title">${esc(p)}</div>
            <div class="item-sub">${v.calls || 0} ${tx('\u8c03\u7528', 'calls')} \u00b7 ${(v.in_tokens || 0).toLocaleString()} in \u00b7 ${(v.out_tokens || 0).toLocaleString()} out</div>
          </div>
        </div>
      `).join('');
    }
    pushDetail('Usage Summary', html);
  },
  _renderVersions() {
    let html = '';
    if (!this._versions.length) {
      html = `<div class="empty">No versions</div>`;
    } else {
      html += this._versions.slice(0, 20).map(v => `
        <div class="sub-item">
          <div class="item-main">
            <div class="item-title">${esc(v.target || '')} v${v.version || 0}</div>
            <div class="item-sub">${fmtTime(v.changed_utc)} \u00b7 ${esc(v.changed_by || '')}${v.reason ? ' \u00b7 ' + esc(v.reason) : ''}</div>
          </div>
          <button class="btn danger" style="padding:4px 10px;font-size:11px" onclick="_rollbackModelVersion('${esc(v.target || '')}', ${v.version || 0})">Rollback</button>
        </div>
      `).join('');
    }
    pushDetail('Config History', html);
  }
});

async function _saveAgentModel(agent) {
  const sel = document.getElementById('model-sel-' + agent);
  if (!sel) return;
  const model = sel.value.trim();
  if (!model) return;
  const displayName = PANELS.model._modelName(model);
  const ok = await confirmAction(
    tx('\u66f4\u65b0\u6a21\u578b\u5206\u914d', 'Update Model Assignment'),
    tx(`\u786e\u8ba4\u5c06 ${agent} \u7684\u6a21\u578b\u6539\u4e3a ${displayName}\uff1f`, `Set model for ${agent} to ${displayName}?`)
  );
  if (!ok) return;
  try {
    const p = PANELS.model._policy;
    const newMap = { ...(p.agent_model_map || {}), [agent]: model };
    await apiWrite('/console/model-policy', 'PUT', { ...p, agent_model_map: newMap });
    refreshPanel('model');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}

async function _rollbackModelVersion(target, version) {
  const ok = await confirmAction(
    tx('\u56de\u6eda\u6a21\u578b\u914d\u7f6e', 'Rollback Model Config'),
    tx(`\u786e\u8ba4\u5c06 ${target} \u56de\u6eda\u5230\u7248\u672c ${version}\uff1f`, `Rollback ${target} to version ${version}?`)
  );
  if (!ok) return;
  const endpoint = target === 'canon'
    ? '/console/model-canon/rollback/' + version
    : '/console/model-policy/rollback/' + version;
  try {
    await apiWrite(endpoint, 'POST', {});
    refreshPanel('model');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}
