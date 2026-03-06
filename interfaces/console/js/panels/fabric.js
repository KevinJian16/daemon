async function showFabric(type) {
  currentFabricView = String(type || 'memory');
  const content = document.getElementById('fabric-content');
  if (content && !String(content.textContent || '').trim()) {
    content.textContent = tx('加载中…', 'Loading…');
  }
  if (type === 'memory') {
    const units = await api('/console/fabric/memory?limit=50');
    let html = `<div class="card"><h3>${tx('Memory Units（最近 50 条）', 'Memory Units (latest 50)')}</h3><table><thead><tr><th>${tx('操作', 'Action')}</th><th>${tx('标题', 'Title')}</th><th>${tx('领域', 'Domain')}</th><th>${tx('层级', 'Tier')}</th><th>${tx('来源', 'Source')}</th><th>${tx('置信度', 'Confidence')}</th><th>${tx('创建时间', 'Created')}</th></tr></thead><tbody>`;
    html += units.map(u => `<tr><td><button class="action" style="font-size:11px;padding:3px 8px;background:#334155" onclick="viewMemoryUnit('${u.unit_id}')">${tx('查看', 'View')}</button></td><td>${esc(u.title)}</td><td>${u.domain}</td><td>${u.tier}</td><td>${esc(u.source_type || 'synthetic')}</td><td>${(u.confidence*100).toFixed(0)}%</td><td style="color:var(--muted)">${fmtTime(u.created_utc)}</td></tr>`).join('');
    html += '</tbody></table></div>';
    html += `<div class="card"><h3>${tx('Memory Unit 详情', 'Memory Unit Detail')}</h3><pre id="memory-detail">${tx('选择一条 unit 查看 usage/links/audit 详情。', 'Select a unit to inspect usage/links/audit details.')}</pre></div>`;
    content.innerHTML = html;
  } else if (type === 'playbook') {
    const methods = await api('/console/fabric/playbook');
    let html = `<div class="card"><h3>${tx('活跃 Playbook Recipes', 'Active Playbook Recipes')}</h3><table><thead><tr><th>${tx('操作', 'Action')}</th><th>${tx('名称', 'Name')}</th><th>${tx('类别', 'Category')}</th><th>${tx('成功率', 'Success Rate')}</th><th>${tx('运行次数', 'Runs')}</th><th>${tx('版本', 'Version')}</th></tr></thead><tbody>`;
    html += methods.map(m => `<tr><td><button class="action" style="font-size:11px;padding:3px 8px;background:#334155" onclick="viewPlaybookMethod('${m.method_id}')">${tx('查看', 'View')}</button></td><td>${esc(m.name)}</td><td>${m.category}</td><td>${m.success_rate != null ? (m.success_rate*100).toFixed(1)+'%' : '—'}</td><td>${m.total_runs}</td><td>v${m.version}</td></tr>`).join('');
    html += '</tbody></table></div>';
    html += `<div class="card">
      <h3>${tx('Playbook Recipe 详情', 'Playbook Recipe Detail')}</h3>
      <div class="search-row">
        <select id="playbook-version-select"><option value="">Select version</option></select>
        <button class="action" style="background:#334155" onclick="previewSelectedPlaybookVersion()">${tx('查看版本', 'View Version')}</button>
      </div>
      <pre id="playbook-version-preview">${tx('选择一个版本预览 spec。', 'Select one version to preview spec.')}</pre>
      <pre id="playbook-detail">${tx('选择一个 recipe 查看评估与版本。', 'Select a recipe to inspect evaluations and versions.')}</pre>
    </div>`;
    content.innerHTML = html;
  } else if (type === 'compass') {
    const [prios, budgets, signals] = await Promise.all([
      api('/console/fabric/compass/priorities'),
      api('/console/fabric/compass/budgets'),
      api('/console/fabric/compass/signals'),
    ]);
    let html = `<div class="card"><h3>${tx('优先级', 'Priorities')}</h3><table><thead><tr><th>${tx('领域', 'Domain')}</th><th>${tx('权重', 'Weight')}</th></tr></thead><tbody>`;
    html += prios.map(p => `<tr><td>${p.domain}</td><td>${p.weight}</td></tr>`).join('');
    html += '</tbody></table></div>';
    html += `<div class="card"><h3>${tx('资源预算', 'Resource Budgets')}</h3><table><thead><tr><th>${tx('资源', 'Resource')}</th><th>${tx('日限额', 'Daily Limit')}</th><th>${tx('当前用量', 'Current Usage')}</th></tr></thead><tbody>`;
    html += budgets.map(b => `<tr><td>${b.resource_type}</td><td>${(b.daily_limit||0).toLocaleString()}</td><td>${(b.current_usage||0).toLocaleString()}</td></tr>`).join('');
    html += '</tbody></table></div>';
    if (signals.length) {
      html += `<div class="card"><h3>${tx('活跃 Attention Signals', 'Active Attention Signals')}</h3><table><thead><tr><th>${tx('领域', 'Domain')}</th><th>${tx('趋势', 'Trend')}</th><th>${tx('级别', 'Severity')}</th><th>${tx('观测时间', 'Observed')}</th></tr></thead><tbody>`;
      html += signals.map(s => `<tr><td>${s.domain}</td><td>${esc(s.trend)}</td><td><span class="badge ${s.severity==='critical'?'error':s.severity==='high'?'degraded':'ok'}">${s.severity}</span></td><td style="color:var(--muted)">${fmtTime(s.observed_utc)}</td></tr>`).join('');
      html += '</tbody></table></div>';
      const timeline = signals
        .slice()
        .sort((a, b) => String(a.observed_utc || '').localeCompare(String(b.observed_utc || '')))
        .map(s => `[${String(s.observed_utc || '').replace('T', ' ').replace('Z', '')}] ${s.domain} (${s.severity}) ${s.trend}`);
      html += `<div class="card"><h3>${tx('Signal 时间线', 'Signal Timeline')}</h3><pre>${esc(timeline.join('\n') || tx('暂无 signals', 'No signals'))}</pre></div>`;
    }
    content.innerHTML = html;
  }
}

async function viewMemoryUnit(unitId) {
  const target = document.getElementById('memory-detail');
  if (!target) return;
  target.textContent = tx('加载 memory unit 详情…', 'Loading memory unit detail…');
  try {
    const u = await api('/console/fabric/memory/' + encodeURIComponent(unitId));
    const summary = {
      unit_id: u.unit_id,
      title: u.title,
      domain: u.domain,
      tier: u.tier,
      confidence: u.confidence,
      usage_count: Array.isArray(u.usage) ? u.usage.length : 0,
      links_out_count: Array.isArray(u.links_out) ? u.links_out.length : 0,
      links_in_count: Array.isArray(u.links_in) ? u.links_in.length : 0,
      audit_count: Array.isArray(u.audit) ? u.audit.length : 0,
      sources: u.sources || [],
      usage: u.usage || [],
      links_out: u.links_out || [],
      links_in: u.links_in || [],
      audit: u.audit || [],
    };
    target.textContent = JSON.stringify(summary, null, 2);
  } catch (e) {
    target.textContent = tx('错误：', 'Error: ') + e.message;
  }
}

async function viewPlaybookMethod(methodId) {
  const target = document.getElementById('playbook-detail');
  if (!target) return;
  target.textContent = tx('加载 playbook recipe 详情…', 'Loading playbook recipe detail…');
  try {
    const m = await api('/console/fabric/playbook/' + encodeURIComponent(methodId));
    const detail = {
      method_id: m.method_id,
      name: m.name,
      status: m.status,
      version: m.version,
      success_rate: m.success_rate,
      total_runs: m.total_runs,
      spec: m.spec || {},
      evaluations_count: Array.isArray(m.evaluations) ? m.evaluations.length : 0,
      versions_count: Array.isArray(m.versions) ? m.versions.length : 0,
      evaluations: m.evaluations || [],
      versions: m.versions || [],
    };
    activePlaybookMethod = detail;
    populatePlaybookVersionSelects(detail.versions || []);
    target.textContent = JSON.stringify(detail, null, 2);
  } catch (e) {
    target.textContent = tx('错误：', 'Error: ') + e.message;
  }
}

function _playbookVersionSpec(version) {
  if (!activePlaybookMethod || !Array.isArray(activePlaybookMethod.versions)) return null;
  const row = activePlaybookMethod.versions.find(v => Number(v.version) === Number(version));
  if (!row) return null;
  try {
    return row.spec_json ? JSON.parse(row.spec_json) : null;
  } catch (_) {
    return null;
  }
}

function populatePlaybookVersionSelects(versions) {
  const sel = document.getElementById('playbook-version-select');
  const preview = document.getElementById('playbook-version-preview');
  if (!sel || !preview) return;
  const opts = [`<option value="">${tx('选择版本', 'Select version')}</option>`]
    .concat((versions || []).map(v => `<option value="${v.version}">v${v.version}</option>`))
    .join('');
  sel.innerHTML = opts;
  preview.textContent = tx('选择一个版本预览 spec。', 'Select one version to preview spec.');
}

function previewSelectedPlaybookVersion() {
  const sel = document.getElementById('playbook-version-select');
  const preview = document.getElementById('playbook-version-preview');
  if (!sel || !preview) return;
  const v = sel.value;
  if (!v) {
    preview.textContent = tx('选择一个版本预览 spec。', 'Select one version to preview spec.');
    return;
  }
  const spec = _playbookVersionSpec(v);
  if (!spec) {
    preview.textContent = tx('无法解析所选版本载荷。', 'Unable to parse selected version payload.');
    return;
  }
  preview.textContent = JSON.stringify(spec, null, 2);
}
