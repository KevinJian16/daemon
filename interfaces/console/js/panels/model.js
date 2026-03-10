registerPanel('models', {
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
    this._canonModels = Array.isArray(registry?.models)
      ? registry.models.filter(m => m && typeof m === 'object' && m.alias).map(m => ({ alias: m.alias, model_id: m.model_id || m.alias, provider: m.provider || '' }))
      : [];
    const agentMap = this._policy.agent_model_map || {};
    const roles = ['counsel', 'scout', 'sage', 'artificer', 'arbiter', 'scribe', 'envoy'];
    this._agents = roles.map(role => ({ agent: role, model: agentMap[role] || '' }));
    this._usage = usage?.summary || {};
    const versions = [];
    for (const v of (policyV || [])) versions.push({ target: 'model_policy', ...v });
    for (const v of (registryV || [])) versions.push({ target: 'canon', ...v });
    versions.sort((a, b) => String(b.changed_utc || '').localeCompare(String(a.changed_utc || '')));
    this._versions = versions;
  },
  _modelName(alias) {
    if (!alias) return '\u2014';
    const found = this._canonModels.find(row => row.alias === alias);
    return found ? found.model_id : alias;
  },
  render() {
    let html = this._agents.map(row => `
      <div class="list-item" onclick="PANELS.models.openDetail('${esc(row.agent)}')">
        <div class="item-main">
          <div class="item-title">${esc(row.agent)}</div>
          <div class="item-sub">${esc(this._modelName(row.model))}</div>
        </div>
        ${statusDot(row.model ? 'green' : 'muted')}
      </div>
    `).join('');

    const providers = Object.entries(this._usage?.by_provider || {});
    if (providers.length) {
      html += `
        <div class="list-item" onclick="PANELS.models.openDetail('_usage')">
          <div class="item-main">
            <div class="item-title">${tx('\u8c03\u7528\u6982\u89c8', 'Usage Summary')}</div>
            <div class="item-sub">${providers.reduce((sum, [, v]) => sum + (v.calls || 0), 0)} ${tx('\u6b21\u8c03\u7528', 'calls')} \u00b7 ${providers.length} ${tx('\u4e2a\u63d0\u4f9b\u65b9', 'providers')}</div>
          </div>
        </div>`;
    }
    if (this._versions.length) {
      html += `
        <div class="list-item" onclick="PANELS.models.openDetail('_versions')">
          <div class="item-main">
            <div class="item-title">${tx('\u914d\u7f6e\u7248\u672c', 'Config History')}</div>
            <div class="item-sub">${this._versions.length} ${tx('\u6761\u8bb0\u5f55', 'entries')}</div>
          </div>
        </div>`;
    }
    return html || `<div class="empty">${tx('\u6ca1\u6709\u6a21\u578b\u914d\u7f6e', 'No model config')}</div>`;
  },
  openDetail(key) {
    if (key === '_usage') return this._renderUsage();
    if (key === '_versions') return this._renderVersions();
    return this._renderAgent(key);
  },
  _renderAgent(agent) {
    const row = this._agents.find(item => item.agent === agent);
    if (!row) return;
    const knownAliases = new Set(this._canonModels.map(model => model.alias));
    const extras = Object.values(this._policy.agent_model_map || {}).filter(alias => alias && !knownAliases.has(alias));
    const options = [
      ...this._canonModels,
      ...extras.map(alias => ({ alias, model_id: alias, provider: '' })),
    ];
    let html = '';
    html += fieldText(tx('\u5f53\u524d\u6a21\u578b', 'Current Model'), this._modelName(row.model));
    html += field(tx('\u66f4\u6362\u6a21\u578b', 'Assign Model'), `<select class="inline-select" id="model-sel-${esc(row.agent)}"><option value="">\u2014</option>${options.map(model => `<option value="${esc(model.alias)}"${model.alias === row.model ? ' selected' : ''}>${esc(model.model_id)}</option>`).join('')}</select>`);
    html += actions(btn(tx('\u4fdd\u5b58', 'Save'), `_saveAgentModel('${esc(row.agent)}')`, 'success'));
    pushDetail(row.agent, html);
  },
  _renderUsage() {
    const providers = Object.entries(this._usage?.by_provider || {}).sort((a, b) => (b[1]?.calls || 0) - (a[1]?.calls || 0));
    let html = '';
    if (!providers.length) {
      html = `<div class="empty">${tx('\u6682\u65e0\u8c03\u7528\u6570\u636e', 'No usage data')}</div>`;
    } else {
      html = providers.map(([provider, value]) => `
        <div class="sub-item">
          <div class="item-main">
            <div class="item-title">${esc(provider)}</div>
            <div class="item-sub">${value.calls || 0} ${tx('\u6b21', 'calls')} \u00b7 ${(value.in_tokens || 0).toLocaleString()} in \u00b7 ${(value.out_tokens || 0).toLocaleString()} out</div>
          </div>
        </div>
      `).join('');
    }
    pushDetail(tx('\u8c03\u7528\u6982\u89c8', 'Usage Summary'), html);
  },
  _renderVersions() {
    let html = '';
    if (!this._versions.length) {
      html = `<div class="empty">${tx('\u6682\u65e0\u7248\u672c', 'No versions')}</div>`;
    } else {
      html = this._versions.slice(0, 20).map(version => `
        <div class="sub-item">
          <div class="item-main">
            <div class="item-title">${esc(version.target || '')} v${version.version || 0}</div>
            <div class="item-sub">${fmtTime(version.changed_utc)} \u00b7 ${esc(version.changed_by || '')}${version.reason ? ' \u00b7 ' + esc(version.reason) : ''}</div>
          </div>
          <button class="btn danger" style="padding:4px 10px;font-size:11px" onclick="_rollbackModelVersion('${esc(version.target || '')}',${version.version || 0})">${tx('\u56de\u6eda', 'Rollback')}</button>
        </div>
      `).join('');
    }
    pushDetail(tx('\u914d\u7f6e\u7248\u672c', 'Config History'), html);
  }
});

async function _saveAgentModel(agent) {
  const sel = document.getElementById('model-sel-' + agent);
  if (!sel) return;
  const model = sel.value.trim();
  if (!model) return;
  const ok = await confirmAction(
    tx('\u66f4\u65b0\u6a21\u578b\u5206\u914d', 'Update Model Assignment'),
    tx(`\u786e\u8ba4\u5c06 ${agent} \u5207\u6362\u5230 ${model}\uff1f`, `Assign ${model} to ${agent}?`)
  );
  if (!ok) return;
  try {
    const policy = PANELS.models._policy;
    await apiWrite('/console/model-policy', 'PUT', { ...policy, agent_model_map: { ...(policy.agent_model_map || {}), [agent]: model } });
    refreshPanel('models');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}

async function _rollbackModelVersion(target, version) {
  const ok = await confirmAction(
    tx('\u56de\u6eda\u6a21\u578b\u914d\u7f6e', 'Rollback Model Config'),
    tx(`\u786e\u8ba4\u56de\u6eda ${target} v${version}\uff1f`, `Rollback ${target} v${version}?`)
  );
  if (!ok) return;
  try {
    await apiWrite(target === 'canon' ? '/console/model-canon/rollback/' + version : '/console/model-policy/rollback/' + version, 'POST', {});
    refreshPanel('models');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}
