async function loadStrategies() {
  const tbody = document.getElementById('strategies-tbody');
  const shadowBody = document.getElementById('shadow-report-tbody');
  const cluster = document.getElementById('strategy-cluster-filter')?.value?.trim() || '';
  const stage = document.getElementById('strategy-stage-filter')?.value || '';
  const q = document.getElementById('strategy-q')?.value?.trim() || '';
  const shadowQ = document.getElementById('shadow-q')?.value?.trim() || '';
  const strategySize = Number(document.getElementById('strategy-page-size')?.value || 20);
  const shadowSize = Number(document.getElementById('shadow-page-size')?.value || 20);
  _listState('strategies', {size: strategySize}).size = strategySize;
  _listState('shadow', {size: shadowSize}).size = shadowSize;
  let url = '/console/strategies';
  const qs = [];
  if (cluster) qs.push('cluster_id=' + encodeURIComponent(cluster));
  if (stage) qs.push('stage=' + encodeURIComponent(stage));
  if (qs.length) url += '?' + qs.join('&');
  tbody.innerHTML = `<tr><td colspan="8" style="color:var(--muted)">${tx('加载中…', 'Loading…')}</td></tr>`;
  shadowBody.innerHTML = `<tr><td colspan="7" style="color:var(--muted)">${tx('加载中…', 'Loading…')}</td></tr>`;
  try {
    const [rows, shadowRows] = await Promise.all([
      api(url),
      api('/console/strategies/shadow-report?limit=1000'),
    ]);
    const strategyFiltered = _applyListQuery(rows || [], q, ['strategy_id', 'cluster_id', 'cluster_display_name', 'stage', 'risk_level']);
    const strategyPageRows = _paginate(strategyFiltered, 'strategies', 'strategies-pager', 'loadStrategies');
    tbody.innerHTML = strategyPageRows.map(r => {
      const sid = String(r.strategy_id || '');
      const stageBadge = esc(r.stage || '');
      const rollbackBtn = r.stage === 'champion'
        ? `<button class="action" style="font-size:11px;padding:3px 8px;background:#7f1d1d" onclick="rollbackStrategy('${encodeURIComponent(sid)}')">${tx('回滚', 'Rollback')}</button>`
        : `<span style="color:var(--muted);font-size:10px">${tx('仅冠军可回滚', 'Rollback only for champion')}</span>`;
      return `<tr>
        <td style="color:var(--muted);font-size:11px">${esc(sid)}</td>
        <td>${esc(r.cluster_display_name || r.cluster_id || '')}<br><span style="color:var(--muted);font-size:10px">${esc(r.cluster_id || '')}</span></td>
        <td><span class="badge ${r.stage === 'champion' ? 'ok' : r.stage === 'challenger' ? 'degraded' : 'hybrid'}">${stageBadge}</span></td>
        <td><span class="badge ${(r.risk_level || '') === 'low' ? 'ok' : (r.risk_level || '') === 'medium' ? 'degraded' : 'error'}">${esc(r.risk_level || 'unknown')}</span></td>
        <td>${r.global_score != null ? Number(r.global_score).toFixed(4) : '—'}</td>
        <td>${Number(r.sample_n || 0)}</td>
        <td style="color:var(--muted)">${fmtTime(r.updated_utc)}</td>
        <td>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#334155" onclick="viewStrategyDetail('${encodeURIComponent(sid)}')">${tx('查看', 'View')}</button>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#0f766e" onclick="sandboxStrategy('${encodeURIComponent(sid)}','${encodeURIComponent(r.cluster_id || '')}','${encodeURIComponent(r.task_type_compat || '')}')">${tx('沙箱', 'Sandbox')}</button>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#14532d" onclick="promoteStrategy('${encodeURIComponent(sid)}')">${tx('晋升', 'Promote')}</button>
          ${rollbackBtn}
        </td>
      </tr>`;
    }).join('') || `<tr><td colspan="8" style="color:var(--muted)">${tx('暂无 Strategy 记录', 'No Strategy records')}</td></tr>`;

    const shadowFiltered = _applyListQuery(shadowRows || [], shadowQ, ['task_id', 'shadow_of', 'cluster_id', 'created_utc']);
    const shadowPageRows = _paginate(shadowFiltered, 'shadow', 'shadow-pager', 'loadStrategies');
    shadowBody.innerHTML = shadowPageRows.map(r => `
      <tr>
        <td style="color:var(--muted);font-size:11px">${esc(r.task_id || '')}</td>
        <td style="color:var(--muted);font-size:11px">${esc(r.shadow_of || '')}</td>
        <td>${esc(r.cluster_id || '')}</td>
        <td>${Number(r.shadow_global_score || 0).toFixed(4)}</td>
        <td>${Number(r.champion_global_score || 0).toFixed(4)}</td>
        <td><span class="badge ${Number(r.delta_global_score || 0) >= 0 ? 'ok' : 'error'}">${Number(r.delta_global_score || 0).toFixed(4)}</span></td>
        <td style="color:var(--muted)">${fmtTime(r.created_utc)}</td>
      </tr>
    `).join('') || `<tr><td colspan="7" style="color:var(--muted)">${tx('暂无 Shadow 报告', 'No shadow reports')}</td></tr>`;
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
    shadowBody.innerHTML = `<tr><td colspan="7" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
  }
}

async function viewStrategyDetail(sidKey) {
  const strategyId = decodeURIComponent(sidKey || '');
  const target = document.getElementById('strategy-detail');
  if (!strategyId || !target) return;
    target.textContent = tx('加载 strategy 详情…', 'Loading strategy detail…');
  try {
    const [experiments, promotions, audit, releaseEvents] = await Promise.all([
      api('/console/strategies/' + encodeURIComponent(strategyId) + '/experiments?limit=200'),
      api('/console/strategies/' + encodeURIComponent(strategyId) + '/promotions?limit=100'),
      api('/console/strategies/' + encodeURIComponent(strategyId) + '/audit'),
      api('/console/strategies/release-events?strategy_id=' + encodeURIComponent(strategyId) + '&limit=200'),
    ]);
    let rollbackPoints = [];
    const clusterId = audit && audit.cluster_id ? String(audit.cluster_id) : '';
    if (clusterId) {
      rollbackPoints = await api('/console/strategies/rollback-points?cluster_id=' + encodeURIComponent(clusterId) + '&limit=50');
    }
    target.textContent = JSON.stringify(
      {
        strategy_id: strategyId,
        audit: audit || {},
        experiments_count: Array.isArray(experiments) ? experiments.length : 0,
        promotions_count: Array.isArray(promotions) ? promotions.length : 0,
        latest_experiments: (experiments || []).slice(0, 30),
        promotions: promotions || [],
        rollback_points: rollbackPoints || [],
        release_events: releaseEvents || [],
      },
      null,
      2
    );
  } catch (e) {
    target.textContent = tx('错误：', 'Error: ') + e.message;
  }
}

async function promoteStrategy(sidKey) {
  const strategyId = decodeURIComponent(sidKey || '');
  if (!strategyId) return;
  const nextStage = prompt(tx(`将 ${strategyId} 晋升到哪个 stage（默认 champion）：`, `Promote ${strategyId} to stage (default champion):`), 'champion') || 'champion';
  const reason = prompt(tx('晋升原因：', 'Promotion reason:'), 'manual_promotion') || 'manual_promotion';
  try {
    await apiWrite('/console/strategies/' + encodeURIComponent(strategyId) + '/promote', 'POST', {
      next_stage: nextStage,
      reason,
      decided_by: 'console',
    });
    await loadStrategies();
  } catch (e) {
    alert(tx('晋升失败：', 'Promote failed: ') + e.message);
  }
}

async function rollbackStrategy(sidKey) {
  const strategyId = decodeURIComponent(sidKey || '');
  if (!strategyId) return;
  const reason = prompt(tx('回滚原因（将回退到上一冠军）：', 'Rollback reason (will rollback to previous champion):'), 'manual_rollback') || 'manual_rollback';
  try {
    await apiWrite('/console/strategies/' + encodeURIComponent(strategyId) + '/rollback', 'POST', {
      reason,
      decided_by: 'console',
    });
    await loadStrategies();
  } catch (e) {
    alert(tx('回滚失败：', 'Rollback failed: ') + e.message);
  }
}

async function sandboxStrategy(sidKey, clusterKey, taskTypeKey) {
  const strategyId = decodeURIComponent(sidKey || '');
  const clusterId = decodeURIComponent(clusterKey || '');
  const taskTypeCompat = decodeURIComponent(taskTypeKey || '');
  if (!strategyId) return;
  const title = prompt(tx('Sandbox 任务标题：', 'Sandbox task title:'), tx('Sandbox 验证运行', 'Sandbox validation run'));
  if (!title) return;
  const taskType = taskTypeCompat || 'research_report';
  const plan = {
    title: title,
    task_type: taskType,
    semantic_fingerprint: {
      cluster_id: clusterId || 'clst_research_report',
      objective: title,
      risk_level: 'medium'
    },
    steps: [
      { id: 'collect', agent: 'collect', depends_on: [] },
      { id: 'analyze', agent: 'analyze', depends_on: ['collect'] },
      { id: 'review', agent: 'review', depends_on: ['analyze'] },
      { id: 'render', agent: 'render', depends_on: ['review'] },
      { id: 'apply', agent: 'apply', depends_on: ['render'] },
    ]
  };
  try {
    const result = await apiWrite('/console/strategies/' + encodeURIComponent(strategyId) + '/sandbox-submit', 'POST', plan);
    alert(tx('Sandbox 已提交：', 'Sandbox submitted: ') + (result.task_id || ''));
    await loadStrategies();
  } catch (e) {
    alert(tx('Sandbox 提交失败：', 'Sandbox submit failed: ') + e.message);
  }
}

async function loadSemantics() {
  const target = document.getElementById('semantics-detail');
  const versionsBody = document.getElementById('semantic-versions-tbody');
  const versionSelect = document.getElementById('semantic-version-select');
  target.textContent = tx('加载语义数据…', 'Loading semantic data…');
  if (versionsBody) versionsBody.innerHTML = `<tr><td colspan="6" style="color:var(--muted)">${tx('加载中…', 'Loading…')}</td></tr>`;
  if (versionSelect) versionSelect.innerHTML = `<option value="">${tx('选择版本', 'Select version')}</option>`;
  try {
    const [res, catalogVersions, ruleVersions] = await Promise.all([
      api('/console/semantics'),
      api('/console/semantics/catalog/versions?limit=30'),
      api('/console/semantics/mapping_rules/versions?limit=30'),
    ]);
    target.textContent = JSON.stringify(res, null, 2);
    if (versionsBody) {
      const rows = [];
      for (const v of (catalogVersions || [])) {
        rows.push({target: 'catalog', ...v});
      }
      for (const v of (ruleVersions || [])) {
        rows.push({target: 'mapping_rules', ...v});
      }
      rows.sort((a, b) => String(b.changed_utc || '').localeCompare(String(a.changed_utc || '')));
      currentSemanticVersions = rows;
      populateSemanticVersionSelect(rows);
      versionsBody.innerHTML = rows.map(v => `
        <tr>
          <td>${esc(v.target || '')}</td>
          <td>${Number(v.version || 0)}</td>
          <td style="color:var(--muted)">${fmtTime(v.changed_utc)}</td>
          <td>${esc(v.changed_by || '')}</td>
          <td style="color:var(--muted)">${esc(v.reason || '')}</td>
          <td><button class="action" style="font-size:11px;padding:3px 8px;background:#7f1d1d" onclick="rollbackSemanticVersion('${encodeURIComponent(v.target || '')}', ${Number(v.version || 0)})">${tx('回滚', 'Rollback')}</button></td>
        </tr>
      `).join('') || `<tr><td colspan="6" style="color:var(--muted)">${tx('暂无版本', 'No versions')}</td></tr>`;
    }
  } catch (e) {
    currentSemanticVersions = [];
    target.textContent = tx('错误：', 'Error: ') + e.message;
    if (versionsBody) {
      versionsBody.innerHTML = `<tr><td colspan="6" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
    }
  }
}

function populateSemanticVersionSelect(rows) {
  const sel = document.getElementById('semantic-version-select');
  if (!sel) return;
  const opts = [`<option value="">${tx('选择版本', 'Select version')}</option>`]
    .concat((rows || []).map((r, idx) => `<option value="${idx}">${esc(r.target || '')} / v${Number(r.version || 0)}</option>`))
    .join('');
  sel.innerHTML = opts;
}

function selectedSemanticVersion() {
  const sel = document.getElementById('semantic-version-select');
  const raw = sel?.value ?? '';
  if (raw === '') return null;
  const idx = Number(raw);
  if (!Number.isInteger(idx) || idx < 0 || idx >= currentSemanticVersions.length) return null;
  return currentSemanticVersions[idx];
}

async function viewSelectedSemanticVersion() {
  const row = selectedSemanticVersion();
  if (!row) {
    alert(tx('请选择一个版本。', 'Please select one version.'));
    return;
  }
  let parsed = {};
  try {
    parsed = row.value_json ? JSON.parse(row.value_json) : row;
  } catch (_) {
    parsed = row;
  }
  await openUnifiedEditor({
    key: `semantic-version:${row.target}:${row.version}`,
    title: tx('Semantic 版本预览', 'Semantic Version Preview'),
    subtitle: `${row.target} / v${Number(row.version || 0)}`,
    hint: tx('只读预览。', 'Read-only preview.'),
    readOnly: true,
    loadText: async () => JSON.stringify(parsed, null, 2),
  });
}

async function rollbackSelectedSemanticVersion() {
  const row = selectedSemanticVersion();
  if (!row) {
    alert(tx('请选择一个版本。', 'Please select one version.'));
    return;
  }
  await rollbackSemanticVersion(encodeURIComponent(row.target || ''), Number(row.version || 0));
}

async function saveSemanticCatalog(rawText = '{}') {
  const raw = String(rawText ?? '{}');
  let parsed = {};
  try {
    parsed = JSON.parse(raw);
  } catch (e) {
    alert(tx('目录 JSON 无效：', 'Catalog JSON invalid: ') + e.message);
    return;
  }
  try {
    await apiWrite('/console/semantics/catalog', 'PUT', parsed);
  } catch (e) {
    alert(tx('保存语义目录失败：', 'Save semantic catalog failed: ') + e.message);
  }
}

async function saveSemanticRules(rawText = '{}') {
  const raw = String(rawText ?? '{}');
  let parsed = {};
  try {
    parsed = JSON.parse(raw);
  } catch (e) {
    alert(tx('规则 JSON 无效：', 'Rules JSON invalid: ') + e.message);
    return;
  }
  try {
    await apiWrite('/console/semantics/mapping-rules', 'PUT', parsed);
  } catch (e) {
    alert(tx('保存语义规则失败：', 'Save semantic rules failed: ') + e.message);
  }
}

async function openSemanticCatalogEditor() {
  await openUnifiedEditor({
    key: 'semantics:catalog',
    title: tx('语义能力目录', 'Semantic Capability Catalog'),
    subtitle: 'config/semantics/capability_catalog.json',
    hint: tx('编辑完成后保存，会写入版本并刷新语义视图。', 'Saving writes a new version and refreshes semantic views.'),
    loadText: async () => {
      const res = await api('/console/semantics');
      return JSON.stringify(res?.catalog || {}, null, 2);
    },
    saveText: async (text) => {
      await saveSemanticCatalog(text);
    },
    onSaved: async () => {
      await loadSemantics();
    },
  });
}

async function openSemanticRulesEditor() {
  await openUnifiedEditor({
    key: 'semantics:rules',
    title: tx('语义映射规则', 'Semantic Mapping Rules'),
    subtitle: 'config/semantics/mapping_rules.json',
    hint: tx('编辑完成后保存，会写入版本并刷新语义视图。', 'Saving writes a new version and refreshes semantic views.'),
    loadText: async () => {
      const res = await api('/console/semantics');
      return JSON.stringify(res?.mapping_rules || {}, null, 2);
    },
    saveText: async (text) => {
      await saveSemanticRules(text);
    },
    onSaved: async () => {
      await loadSemantics();
    },
  });
}

async function rollbackSemanticVersion(targetKey, version) {
  const target = decodeURIComponent(targetKey || '');
  const v = Number(version || 0);
  if (!target || !v) return;
  if (!confirm(tx(`确认将 ${target} 回滚到版本 ${v} 吗？`, `Rollback ${target} to version ${v}?`))) return;
  try {
    await apiWrite('/console/semantics/' + encodeURIComponent(target) + '/rollback/' + v, 'POST', {});
    await loadSemantics();
  } catch (e) {
    alert(tx('语义配置回滚失败：', 'Semantic rollback failed: ') + e.message);
  }
}

