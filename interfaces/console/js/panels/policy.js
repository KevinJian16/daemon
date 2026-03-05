async function loadPolicy() {
  const prios = await api('/console/fabric/compass/priorities');
  document.getElementById('priority-tbody').innerHTML = prios.map(p =>
    `<tr><td>${p.domain}</td><td>${p.weight}</td><td style="color:var(--muted)">${p.source||'system'}</td><td style="color:var(--muted)">${fmtTime(p.updated_utc)}</td></tr>`
  ).join('');
  await onPolicyScopeChange();
  const tbody = document.getElementById('policy-versions-tbody');
  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="5" style="color:var(--muted)">${tx('先加载一个 Policy key 查看版本', 'Load a policy key first to view versions')}</td></tr>`;
  }
  populatePolicyVersionSelect([]);
  const preview = document.getElementById('policy-version-preview');
  if (preview) preview.textContent = tx('选择一个版本预览。', 'Select one version to preview.');
  cancelPolicyEditor(tx('请选择一项后加载 Policy Editor。', 'Pick a policy key, then load Policy Editor.'));
  await loadPolicyCatalog();
}

function _policyDefaults(scope) {
  const defaults = {
    quality: 'default',
    preference: 'output_language',
    budget: 'openai_tokens',
  };
  return defaults[scope] || 'default';
}

async function _loadPolicyScopeKeys(scope) {
  if (scope === 'preference') {
    const prefs = await api('/console/policy/preferences');
    return (prefs || []).map(p => String(p.pref_key || '').trim()).filter(Boolean);
  }
  if (scope === 'budget') {
    const budgets = await api('/console/policy/budgets');
    return (budgets || []).map(b => String(b.resource_type || '').trim()).filter(Boolean);
  }
  return ['default', 'research_report', 'daily_brief'];
}

function onPolicyKeyPresetChange() {
  const selectEl = document.getElementById('policy-key-select');
  if (!selectEl) return;
  currentPolicyType = selectEl.value || _policyDefaults(currentPolicyScope || 'quality');
}

async function refreshPolicyKeyOptions(forceDefault = false) {
  const scopeEl = document.getElementById('policy-scope');
  const selectEl = document.getElementById('policy-key-select');
  const scope = (scopeEl?.value || currentPolicyScope || 'quality').trim();
  const fallback = _policyDefaults(scope);
  const existing = currentPolicyType || '';
  let keys = [];
  try {
    keys = await _loadPolicyScopeKeys(scope);
  } catch (_) {
    keys = [];
  }
  keys = Array.from(new Set([fallback].concat(keys.map(k => String(k || '').trim()).filter(Boolean))));
  currentPolicyKeys = keys;
  const nextValue = forceDefault
    ? fallback
    : (keys.includes(existing) ? existing : fallback);
  if (selectEl) {
    const options = keys.map(k => `<option value="${esc(k)}">${esc(k)}</option>`).join('');
    selectEl.innerHTML = options;
    selectEl.value = keys.includes(nextValue) ? nextValue : fallback;
    currentPolicyType = selectEl.value || fallback;
  }
}

async function onPolicyScopeChange(forceDefault = false, autoLoad = false) {
  const scopeEl = document.getElementById('policy-scope');
  const prevScope = currentPolicyScope || 'quality';
  const scope = (scopeEl?.value || 'quality').trim();
  if (scopeEl) scopeEl.value = scope;
  await refreshPolicyKeyOptions(forceDefault || scope !== prevScope);
  if (scope !== prevScope) {
    cancelPolicyEditor(tx('Policy 范围已切换，请重新加载后编辑。', 'Policy scope changed. Reload to edit.'));
  }
  currentPolicyScope = scope;
  currentPolicyType = document.getElementById('policy-key-select')?.value || _policyDefaults(scope);
  if (autoLoad) await loadPolicyEditor();
}

function cancelPolicyEditor(metaText = '') {
  const meta = document.getElementById('policy-editor-meta');
  if (meta) {
    meta.textContent = metaText || tx('编辑器空闲', 'Editor idle');
  }
  if (unifiedEditorState.open && unifiedEditorState.key.startsWith('policy:')) {
    closeUnifiedEditor(true);
  }
}

function _policyDescriptor() {
  const scopeEl = document.getElementById('policy-scope');
  const keySel = document.getElementById('policy-key-select');
  const scope = (scopeEl?.value || currentPolicyScope || 'quality').trim();
  const key = (keySel?.value || currentPolicyType || _policyDefaults(scope)).trim();
  currentPolicyScope = scope;
  currentPolicyType = key;
  if (keySel) keySel.value = key;
  if (scope === 'preference') {
    return {
      scope,
      key,
      label: `preference.${key}`,
      getPath: '/console/policy/preferences/' + encodeURIComponent(key),
      putPath: '/console/policy/preferences/' + encodeURIComponent(key),
      versionsPath: '/console/policy/preferences/' + encodeURIComponent(key) + '/versions',
      rollbackPath: '/console/policy/preferences/' + encodeURIComponent(key) + '/rollback/',
    };
  }
  if (scope === 'budget') {
    return {
      scope,
      key,
      label: `budget.${key}`,
      getPath: '/console/policy/budgets/' + encodeURIComponent(key),
      putPath: '/console/policy/budgets/' + encodeURIComponent(key),
      versionsPath: '/console/policy/budgets/' + encodeURIComponent(key) + '/versions',
      rollbackPath: '/console/policy/budgets/' + encodeURIComponent(key) + '/rollback/',
    };
  }
  return {
    scope: 'quality',
    key,
    label: `quality.${key}`,
    getPath: '/console/policy/quality/' + encodeURIComponent(key),
    putPath: '/console/policy/quality/' + encodeURIComponent(key),
    versionsPath: '/console/policy/quality/' + encodeURIComponent(key) + '/versions',
    rollbackPath: '/console/policy/quality/' + encodeURIComponent(key) + '/rollback/',
  };
}

function _policyEditorContent(scope, value) {
  if (scope === 'preference') {
    if (value && typeof value === 'object' && value.value !== undefined) return String(value.value);
    if (typeof value === 'string') return value;
    return '';
  }
  if (scope === 'budget') {
    const raw = value && typeof value === 'object' ? value : {};
    return JSON.stringify({
      daily_limit: Number(raw.daily_limit || 0),
      current_usage: Number(raw.current_usage || 0),
      reset_utc: raw.reset_utc || '',
    }, null, 2);
  }
  const rules = value && typeof value === 'object' && value.rules !== undefined ? value.rules : value;
  return JSON.stringify(rules || {}, null, 2);
}

function _policyWriteBody(scope, rawText) {
  if (scope === 'preference') {
    return {value: String(rawText ?? '')};
  }
  if (scope === 'budget') {
    const text = String(rawText ?? '').trim();
    if (!text) throw new Error(tx('预算值不能为空', 'Budget value cannot be empty'));
    let dailyLimit = NaN;
    if (/^-?\d+(\.\d+)?$/.test(text)) {
      dailyLimit = Number(text);
    } else {
      const parsed = JSON.parse(text);
      dailyLimit = Number(parsed?.daily_limit);
    }
    if (!Number.isFinite(dailyLimit)) throw new Error('daily_limit must be numeric');
    return {daily_limit: dailyLimit};
  }
  const parsed = JSON.parse(String(rawText ?? '{}') || '{}');
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Quality profile must be a JSON object');
  }
  return {rules: parsed};
}

async function loadPolicyEditor() {
  const desc = _policyDescriptor();
  const meta = document.getElementById('policy-editor-meta');
  if (meta) meta.textContent = tx(`Loading ${desc.label}…`, `Loading ${desc.label}…`);
  const ok = await openUnifiedEditor({
    key: `policy:${desc.scope}:${desc.key}`,
    title: tx('Policy 编辑器', 'Policy Editor'),
    subtitle: desc.label,
    hint: tx('支持 JSON/文本；保存后会刷新目录与版本。', 'Supports JSON/text; save refreshes catalog and versions.'),
    loadText: async () => {
      const d = await api(desc.getPath);
      return _policyEditorContent(desc.scope, d);
    },
    saveText: async (text) => {
      const body = _policyWriteBody(desc.scope, text);
      await apiWrite(desc.putPath, 'PUT', body);
    },
    onSaved: async () => {
      await Promise.all([loadPolicyCatalog(), loadPolicyVersions()]);
    },
  });
  if (ok) {
    if (meta) meta.textContent = tx(`Editing ${desc.label}`, `Editing ${desc.label}`);
  } else {
    if (meta) meta.textContent = tx(`Failed to load ${desc.label}`, `Failed to load ${desc.label}`);
  }
}

async function savePolicyEditor() {
  await saveUnifiedEditor();
}

async function loadPolicyCatalog() {
  const qualityTbody = document.getElementById('policy-quality-tbody');
  const prefTbody = document.getElementById('policy-pref-tbody');
  const budgetTbody = document.getElementById('policy-budget-tbody');
  try {
    const [qualityKeys, prefs, budgets] = await Promise.all([
      _loadPolicyScopeKeys('quality'),
      api('/console/policy/preferences'),
      api('/console/policy/budgets'),
    ]);
    if (qualityTbody) {
      qualityTbody.innerHTML = (qualityKeys || []).map(k => `
        <tr>
          <td title="${esc(k)}">${esc(k)}</td>
          <td style="color:var(--muted)">—</td>
          <td style="color:var(--muted)">—</td>
          <td class="col-action-cell"><button class="action" style="font-size:11px;padding:3px 8px;background:#334155" onclick="editPolicyKey('quality','${encodeURIComponent(k)}')">${tx('编辑', 'Edit')}</button></td>
        </tr>
      `).join('') || `<tr><td colspan="4" style="color:var(--muted)">${tx('暂无质量键', 'No quality keys')}</td></tr>`;
    }
    if (prefTbody) {
      prefTbody.innerHTML = (prefs || []).map(p => `
        <tr>
          <td title="${esc(p.pref_key || '')}">${esc(p.pref_key || '')}</td>
          <td style="color:var(--muted)" title="${esc(p.value || '')}">${esc((p.value || '').slice(0, 120))}</td>
          <td style="color:var(--muted)">preference</td>
          <td class="col-action-cell"><button class="action" style="font-size:11px;padding:3px 8px;background:#334155" onclick="editPolicyKey('preference','${encodeURIComponent(p.pref_key || '')}')">${tx('编辑', 'Edit')}</button></td>
        </tr>
      `).join('') || `<tr><td colspan="4" style="color:var(--muted)">${tx('暂无偏好配置', 'No preferences')}</td></tr>`;
    }
    if (budgetTbody) {
      budgetTbody.innerHTML = (budgets || []).map(b => `
        <tr>
          <td title="${esc(b.resource_type || '')}">${esc(b.resource_type || '')}</td>
          <td>${Number(b.daily_limit || 0).toLocaleString()}</td>
          <td>${Number(b.current_usage || 0).toLocaleString()}</td>
          <td class="col-action-cell"><button class="action" style="font-size:11px;padding:3px 8px;background:#334155" onclick="editPolicyKey('budget','${encodeURIComponent(b.resource_type || '')}')">${tx('编辑', 'Edit')}</button></td>
        </tr>
      `).join('') || `<tr><td colspan="4" style="color:var(--muted)">${tx('暂无预算配置', 'No budgets')}</td></tr>`;
    }
    await refreshPolicyKeyOptions(false);
  } catch (e) {
    if (qualityTbody) qualityTbody.innerHTML = `<tr><td colspan="4" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
    if (prefTbody) prefTbody.innerHTML = `<tr><td colspan="4" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
    if (budgetTbody) budgetTbody.innerHTML = `<tr><td colspan="4" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
  }
}

async function editPolicyKey(scope, keyEncoded) {
  const key = decodeURIComponent(keyEncoded || '');
  const scopeEl = document.getElementById('policy-scope');
  const keySel = document.getElementById('policy-key-select');
  if (scopeEl) scopeEl.value = scope;
  await onPolicyScopeChange(false, false);
  if (keySel && Array.from(keySel.options).some(opt => opt.value === key)) {
    keySel.value = key;
    currentPolicyType = key;
  }
  await loadPolicyEditor();
}

async function loadPolicyVersions() {
  const desc = _policyDescriptor();
  const tbody = document.getElementById('policy-versions-tbody');
  try {
    const versions = await api(desc.versionsPath);
    currentPolicyVersions = Array.isArray(versions) ? versions : [];
    if (!currentPolicyVersions.length) {
      tbody.innerHTML = `<tr><td colspan="5" style="color:var(--muted)">${tx('未找到版本', 'No versions found')}</td></tr>`;
      populatePolicyVersionSelect([]);
      return;
    }
    tbody.innerHTML = currentPolicyVersions.map(v => `
      <tr>
        <td>v${v.version}</td>
        <td style="color:var(--muted)">${fmtTime(v.changed_utc)}</td>
        <td style="color:var(--muted)">${esc(v.changed_by||'')}</td>
        <td style="color:var(--muted)">${esc(v.reason||'')}</td>
        <td>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#334155" onclick="viewPolicyVersion(${v.version})">${tx('查看', 'View')}</button>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#7f1d1d" onclick="rollbackPolicyVersion(${v.version})">${tx('回滚', 'Rollback')}</button>
        </td>
      </tr>
    `).join('');
    populatePolicyVersionSelect(currentPolicyVersions);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
  }
}

function populatePolicyVersionSelect(versions) {
  const sel = document.getElementById('policy-version-select');
  if (!sel) return;
  const opts = [`<option value="">${tx('选择版本', 'Select version')}</option>`].concat(
    (versions || []).map(v => `<option value="${v.version}">v${v.version}</option>`)
  ).join('');
  sel.innerHTML = opts;
}

function selectedPolicyVersion() {
  const sel = document.getElementById('policy-version-select');
  const v = Number(sel?.value || 0);
  if (!v) return null;
  return v;
}

function _policyVersionValue(version) {
  const row = currentPolicyVersions.find(v => Number(v.version) === Number(version));
  if (!row) return null;
  try {
    return row.value_json ? JSON.parse(row.value_json) : null;
  } catch (_) {
    return null;
  }
}

async function viewPolicyVersion(version) {
  const desc = _policyDescriptor();
  const value = _policyVersionValue(version);
  if (!value) return;
  const meta = document.getElementById('policy-editor-meta');
  if (meta) meta.textContent = tx(`Viewing v${version} of ${desc.label}`, `Viewing v${version} of ${desc.label}`);
  await openUnifiedEditor({
    key: `policy-version:${desc.scope}:${desc.key}:v${version}`,
    title: tx('Policy 版本预览', 'Policy Version Preview'),
    subtitle: `${desc.label} / v${version}`,
    hint: tx('只读预览；如需修改请使用 Edit Policy。', 'Read-only preview. Use Edit Policy for modifications.'),
    readOnly: true,
    loadText: async () => _policyEditorContent(desc.scope, value),
  });
}

async function viewSelectedPolicyVersion() {
  const v = selectedPolicyVersion();
  const preview = document.getElementById('policy-version-preview');
  if (!v) {
    if (preview) preview.textContent = tx('请选择一个版本。', 'Please select one version.');
    return;
  }
  const value = _policyVersionValue(v);
  if (!value) {
    if (preview) preview.textContent = tx('无法解析所选版本。', 'Unable to parse selected version.');
    return;
  }
  if (preview) preview.textContent = JSON.stringify(value, null, 2);
  await viewPolicyVersion(v);
}

async function rollbackPolicyVersion(version) {
  const desc = _policyDescriptor();
  if (!confirm(tx(`确认回滚 ${desc.label} 到 v${version} 吗？`, `Rollback ${desc.label} to v${version}?`))) return;
  try {
    await apiWrite(
      desc.rollbackPath + version,
      'POST',
      {}
    );
    await loadPolicy();
  } catch (e) {
    alert(tx('回滚失败：', 'Rollback failed: ') + e.message);
  }
}

async function rollbackSelectedPolicyVersion() {
  const v = selectedPolicyVersion();
  if (!v) {
    alert(tx('请选择一个版本。', 'Please select one version.'));
    return;
  }
  await rollbackPolicyVersion(v);
}
