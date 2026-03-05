async function loadModelControl() {
  const configStatus = document.getElementById('model-config-status');
  const summary = document.getElementById('model-usage-summary');
  const cortexSummary = document.getElementById('cortex-usage-summary');
  const cortexBody = document.getElementById('cortex-usage-tbody');
  const versionsBody = document.getElementById('model-policy-versions-tbody');
  const versionSelect = document.getElementById('model-version-select');
  if (summary) summary.innerHTML = `<div class="model-empty">${tx('加载模型用量…', 'Loading model usage…')}</div>`;
  if (cortexSummary) cortexSummary.innerHTML = `<div class="model-empty">${tx('加载 Cortex 汇总…', 'Loading Cortex summary…')}</div>`;
  if (cortexBody) cortexBody.innerHTML = `<tr><td colspan="8" style="color:var(--muted)">${tx('加载中…', 'Loading…')}</td></tr>`;
  if (versionsBody) versionsBody.innerHTML = `<tr><td colspan="6" style="color:var(--muted)">${tx('加载中…', 'Loading…')}</td></tr>`;
  if (versionSelect) versionSelect.innerHTML = `<option value="">${tx('选择版本', 'Select version')}</option>`;
  try {
    const [policy, registry, usage, policyVersions, registryVersions] = await Promise.all([
      api('/console/model-policy'),
      api('/console/model-registry'),
      api('/console/model-usage?limit=1000'),
      api('/console/model-policy/versions?limit=50'),
      api('/console/model-registry/versions?limit=50'),
    ]);
    currentModelPolicy = policy || {};
    const policyCount = Object.keys(policy || {}).length;
    const registryModels = Array.isArray(registry?.models)
      ? registry.models.length
      : (registry?.models && typeof registry.models === 'object')
        ? Object.keys(registry.models).length
        : Object.keys(registry || {}).length;
    const defaultProvider =
      String(policy?.routing?.default_provider || policy?.default_provider || '').trim()
      || '—';
    const defaultModel =
      String(policy?.routing?.default_model || policy?.default_model || '').trim()
      || '—';
    const policyCountEl = document.getElementById('model-policy-count');
    const registryCountEl = document.getElementById('model-registry-count');
    const providerEl = document.getElementById('model-default-provider');
    const modelEl = document.getElementById('model-default-model');
    if (policyCountEl) policyCountEl.textContent = Number(policyCount).toLocaleString();
    if (registryCountEl) registryCountEl.textContent = Number(registryModels).toLocaleString();
    if (providerEl) providerEl.textContent = defaultProvider;
    if (modelEl) modelEl.textContent = defaultModel;
    if (configStatus && !policyCountEl) {
      configStatus.innerHTML = tx('模型配置卡片未加载。', 'Model config cards not mounted.');
    }
    const usageSummary = usage?.summary || {};
    const byProvider = usageSummary.by_provider || {};
    const byModel = usageSummary.by_model || {};
    const providerRows = Object.entries(byProvider).sort((a, b) => (b[1]?.calls || 0) - (a[1]?.calls || 0)).slice(0, 10);
    const modelRows = Object.entries(byModel).sort((a, b) => (b[1]?.calls || 0) - (a[1]?.calls || 0)).slice(0, 10);
    if (summary) {
      summary.innerHTML = `
        <div class="model-table-shell">
          <table>
            <thead><tr><th>Provider</th><th>Calls</th><th>In</th><th>Out</th><th>Errors</th></tr></thead>
            <tbody>
              ${providerRows.map(([k, v]) => `
                <tr>
                  <td>${esc(k)}</td>
                  <td>${Number(v.calls || 0).toLocaleString()}</td>
                  <td>${Number(v.in_tokens || 0).toLocaleString()}</td>
                  <td>${Number(v.out_tokens || 0).toLocaleString()}</td>
                  <td>${Number(v.errors || 0).toLocaleString()}</td>
                </tr>
              `).join('') || `<tr><td colspan="5" style="color:var(--muted)">${tx('暂无 provider 汇总', 'No provider summary')}</td></tr>`}
            </tbody>
          </table>
        </div>
        <div class="model-table-shell">
          <table>
            <thead><tr><th>Model</th><th>Calls</th><th>In</th><th>Out</th><th>Errors</th></tr></thead>
            <tbody>
              ${modelRows.map(([k, v]) => `
                <tr>
                  <td>${esc(k)}</td>
                  <td>${Number(v.calls || 0).toLocaleString()}</td>
                  <td>${Number(v.in_tokens || 0).toLocaleString()}</td>
                  <td>${Number(v.out_tokens || 0).toLocaleString()}</td>
                  <td>${Number(v.errors || 0).toLocaleString()}</td>
                </tr>
              `).join('') || `<tr><td colspan="5" style="color:var(--muted)">${tx('暂无 model 汇总', 'No model summary')}</td></tr>`}
            </tbody>
          </table>
        </div>
      `;
    }
    if (versionsBody) {
      const rows = [];
      for (const v of (policyVersions || [])) rows.push({target: 'policy', ...v});
      for (const v of (registryVersions || [])) rows.push({target: 'registry', ...v});
      rows.sort((a, b) => String(b.changed_utc || '').localeCompare(String(a.changed_utc || '')));
      currentModelVersions = rows;
      populateModelVersionSelect(rows);
      versionsBody.innerHTML = rows.map(v => `
        <tr>
          <td>${esc(v.target || '')}</td>
          <td>${Number(v.version || 0)}</td>
          <td style="color:var(--muted)">${fmtTime(v.changed_utc)}</td>
          <td>${esc(v.changed_by || '')}</td>
          <td style="color:var(--muted)">${esc(v.reason || '')}</td>
          <td><button class="action" style="font-size:11px;padding:3px 8px;background:#7f1d1d" onclick="rollbackModelConfigVersion('${encodeURIComponent(v.target || '')}', ${Number(v.version || 0)})">${tx('回滚', 'Rollback')}</button></td>
        </tr>
      `).join('') || `<tr><td colspan="6" style="color:var(--muted)">${tx('暂无版本', 'No versions')}</td></tr>`;
    }
    await loadCortexUsage();
  } catch (e) {
    currentModelVersions = [];
    if (summary) summary.innerHTML = `<div class="model-empty">${tx('错误：', 'Error: ')}${esc(e.message)}</div>`;
    const policyCountEl = document.getElementById('model-policy-count');
    const registryCountEl = document.getElementById('model-registry-count');
    const providerEl = document.getElementById('model-default-provider');
    const modelEl = document.getElementById('model-default-model');
    if (policyCountEl) policyCountEl.textContent = '—';
    if (registryCountEl) registryCountEl.textContent = '—';
    if (providerEl) providerEl.textContent = '—';
    if (modelEl) modelEl.textContent = '—';
    if (versionsBody) {
      versionsBody.innerHTML = `<tr><td colspan="6" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
    }
  }
}

function populateModelVersionSelect(rows) {
  const sel = document.getElementById('model-version-select');
  if (!sel) return;
  const opts = [`<option value="">${tx('选择版本', 'Select version')}</option>`]
    .concat((rows || []).map((r, idx) => `<option value="${idx}">${esc(r.target || '')} / v${Number(r.version || 0)}</option>`))
    .join('');
  sel.innerHTML = opts;
}

function selectedModelVersion() {
  const sel = document.getElementById('model-version-select');
  const raw = sel?.value ?? '';
  if (raw === '') return null;
  const idx = Number(raw);
  if (!Number.isInteger(idx) || idx < 0 || idx >= currentModelVersions.length) return null;
  return currentModelVersions[idx];
}

async function viewSelectedModelVersion() {
  const row = selectedModelVersion();
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
    key: `model-version:${row.target}:${row.version}`,
    title: tx('Model 版本预览', 'Model Version Preview'),
    subtitle: `${row.target} / v${Number(row.version || 0)}`,
    hint: tx('只读预览。', 'Read-only preview.'),
    readOnly: true,
    loadText: async () => JSON.stringify(parsed, null, 2),
  });
}

async function rollbackSelectedModelVersion() {
  const row = selectedModelVersion();
  if (!row) {
    alert(tx('请选择一个版本。', 'Please select one version.'));
    return;
  }
  await rollbackModelConfigVersion(encodeURIComponent(row.target || ''), Number(row.version || 0));
}

async function saveModelPolicy(rawText = '{}') {
  const raw = String(rawText ?? '{}');
  let parsed = {};
  try {
    parsed = JSON.parse(raw);
  } catch (e) {
    alert(tx('Model Policy JSON 无效：', 'Model Policy JSON invalid: ') + e.message);
    return;
  }
  try {
    await apiWrite('/console/model-policy', 'PUT', parsed);
  } catch (e) {
    alert(tx('保存 Model Policy 失败：', 'Save Model Policy failed: ') + e.message);
  }
}

async function saveModelRegistry(rawText = '{}') {
  const raw = String(rawText ?? '{}');
  let parsed = {};
  try {
    parsed = JSON.parse(raw);
  } catch (e) {
    alert(tx('模型注册表 JSON 无效：', 'Registry JSON invalid: ') + e.message);
    return;
  }
  try {
    await apiWrite('/console/model-registry', 'PUT', parsed);
  } catch (e) {
    alert(tx('保存模型注册表失败：', 'Save model registry failed: ') + e.message);
  }
}

async function openModelPolicyEditor() {
  await openUnifiedEditor({
    key: 'model:policy',
    title: tx('Model Policy 配置', 'Model Policy'),
    subtitle: 'config/model_policy.json',
    hint: tx('保存后自动刷新模型用量与版本列表。', 'Save refreshes model usage and version list.'),
    loadText: async () => {
      const data = await api('/console/model-policy');
      return JSON.stringify(data || {}, null, 2);
    },
    saveText: async (text) => {
      await saveModelPolicy(text);
    },
    onSaved: async () => {
      await loadModelControl();
    },
  });
}

async function openModelRegistryEditor() {
  await openUnifiedEditor({
    key: 'model:registry',
    title: tx('模型注册表', 'Model Registry'),
    subtitle: 'config/model_registry.json',
    hint: tx('保存后自动刷新模型用量与版本列表。', 'Save refreshes model usage and version list.'),
    loadText: async () => {
      const data = await api('/console/model-registry');
      return JSON.stringify(data || {}, null, 2);
    },
    saveText: async (text) => {
      await saveModelRegistry(text);
    },
    onSaved: async () => {
      await loadModelControl();
    },
  });
}

async function rollbackModelConfigVersion(targetKey, version) {
  const target = decodeURIComponent(targetKey || '');
  const v = Number(version || 0);
  if (!target || !v) return;
  if (!confirm(tx(`确认将模型 ${target} 回滚到版本 ${v} 吗？`, `Rollback model ${target} to version ${v}?`))) return;
  const endpoint = target === 'registry'
    ? '/console/model-registry/rollback/' + v
    : '/console/model-policy/rollback/' + v;
  try {
    await apiWrite(endpoint, 'POST', {});
    await loadModelControl();
  } catch (e) {
    alert(tx('模型回滚失败：', 'Model rollback failed: ') + e.message);
  }
}

