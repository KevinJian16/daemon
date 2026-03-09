async function loadNorm() {
  const prios = await api('/console/psyche/instinct/priorities');
  document.getElementById('priority-tbody').innerHTML = prios.map((p) =>
    `<tr><td>${p.domain}</td><td>${p.weight}</td><td style="color:var(--muted)">${p.source || 'system'}</td><td style="color:var(--muted)">${fmtTime(p.updated_utc)}</td></tr>`
  ).join('');
  await onNormScopeChange();
  const tbody = document.getElementById('norm-versions-tbody');
  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="5" style="color:var(--muted)">${tx('先加载一个 Norm key 查看版本', 'Load a Norm key first to view versions')}</td></tr>`;
  }
  populateNormVersionSelect([]);
  const preview = document.getElementById('norm-version-preview');
  if (preview) preview.textContent = tx('选择一个版本预览。', 'Select one version to preview.');
  cancelNormEditor(tx('请选择一项后加载 Norm Editor。', 'Pick a Norm key, then load Norm Editor.'));
  await loadNormCatalog();
}

function _normDefaults(scope) {
  const defaults = {
    quality: 'default',
    preference: 'output_language',
    ration: 'openai_tokens',
  };
  return defaults[scope] || 'default';
}

async function _loadNormScopeKeys(scope) {
  if (scope === 'preference') {
    const prefs = await api('/console/norm/preferences');
    return (prefs || []).map((p) => String(p.pref_key || '').trim()).filter(Boolean);
  }
  if (scope === 'ration') {
    const rations = await api('/console/norm/rations');
    return (rations || []).map((b) => String(b.resource_type || '').trim()).filter(Boolean);
  }
  return ['default', 'research_report', 'daily_brief'];
}

function onNormKeyPresetChange() {
  const selectEl = document.getElementById('norm-key-select');
  if (!selectEl) return;
  currentNormType = selectEl.value || _normDefaults(currentNormScope || 'quality');
}

async function refreshNormKeyOptions(forceDefault = false) {
  const scopeEl = document.getElementById('norm-scope');
  const selectEl = document.getElementById('norm-key-select');
  const scope = (scopeEl?.value || currentNormScope || 'quality').trim();
  const fallback = _normDefaults(scope);
  const existing = currentNormType || '';
  let keys = [];
  try {
    keys = await _loadNormScopeKeys(scope);
  } catch (_) {
    keys = [];
  }
  keys = Array.from(new Set([fallback].concat(keys.map((k) => String(k || '').trim()).filter(Boolean))));
  currentNormKeys = keys;
  const nextValue = forceDefault ? fallback : (keys.includes(existing) ? existing : fallback);
  if (selectEl) {
    selectEl.innerHTML = keys.map((k) => `<option value="${esc(k)}">${esc(k)}</option>`).join('');
    selectEl.value = keys.includes(nextValue) ? nextValue : fallback;
    currentNormType = selectEl.value || fallback;
  }
}

async function onNormScopeChange(forceDefault = false, autoLoad = false) {
  const scopeEl = document.getElementById('norm-scope');
  const prevScope = currentNormScope || 'quality';
  const scope = (scopeEl?.value || 'quality').trim();
  if (scopeEl) scopeEl.value = scope;
  await refreshNormKeyOptions(forceDefault || scope !== prevScope);
  if (scope !== prevScope) {
    cancelNormEditor(tx('Norm 范围已切换，请重新加载后编辑。', 'Norm scope changed. Reload to edit.'));
  }
  currentNormScope = scope;
  currentNormType = document.getElementById('norm-key-select')?.value || _normDefaults(scope);
  if (autoLoad) await loadNormEditor();
}

function cancelNormEditor(metaText = '') {
  const meta = document.getElementById('norm-editor-meta');
  if (meta) {
    meta.textContent = metaText || tx('编辑器空闲', 'Editor idle');
  }
  if (unifiedEditorState.open && unifiedEditorState.key.startsWith('norm:')) {
    closeUnifiedEditor(true);
  }
}

function _normDescriptor() {
  const scopeEl = document.getElementById('norm-scope');
  const keySel = document.getElementById('norm-key-select');
  const scope = (scopeEl?.value || currentNormScope || 'quality').trim();
  const key = (keySel?.value || currentNormType || _normDefaults(scope)).trim();
  currentNormScope = scope;
  currentNormType = key;
  if (keySel) keySel.value = key;
  if (scope === 'preference') {
    return {
      scope,
      key,
      label: `preference.${key}`,
      getPath: '/console/norm/preferences/' + encodeURIComponent(key),
      putPath: '/console/norm/preferences/' + encodeURIComponent(key),
      versionsPath: '/console/norm/preferences/' + encodeURIComponent(key) + '/versions',
      rollbackPath: '/console/norm/preferences/' + encodeURIComponent(key) + '/rollback/',
    };
  }
  if (scope === 'ration') {
    return {
      scope,
      key,
      label: `ration.${key}`,
      getPath: '/console/norm/rations/' + encodeURIComponent(key),
      putPath: '/console/norm/rations/' + encodeURIComponent(key),
      versionsPath: '/console/norm/rations/' + encodeURIComponent(key) + '/versions',
      rollbackPath: '/console/norm/rations/' + encodeURIComponent(key) + '/rollback/',
    };
  }
  return {
    scope: 'quality',
    key,
    label: `quality.${key}`,
    getPath: '/console/norm/quality/' + encodeURIComponent(key),
    putPath: '/console/norm/quality/' + encodeURIComponent(key),
    versionsPath: '/console/norm/quality/' + encodeURIComponent(key) + '/versions',
    rollbackPath: '/console/norm/quality/' + encodeURIComponent(key) + '/rollback/',
  };
}

function _normEditorContent(scope, value) {
  if (scope === 'preference') {
    if (value && typeof value === 'object' && value.value !== undefined) return String(value.value);
    if (typeof value === 'string') return value;
    return '';
  }
  if (scope === 'ration') {
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

function _normWriteBody(scope, rawText) {
  if (scope === 'preference') {
    return {value: String(rawText ?? '')};
  }
  if (scope === 'ration') {
    const text = String(rawText ?? '').trim();
    if (!text) throw new Error(tx('配额值不能为空', 'Ration value cannot be empty'));
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

async function loadNormEditor() {
  const desc = _normDescriptor();
  const meta = document.getElementById('norm-editor-meta');
  if (meta) meta.textContent = tx(`Loading ${desc.label}…`, `Loading ${desc.label}…`);
  const ok = await openUnifiedEditor({
    key: `norm:${desc.scope}:${desc.key}`,
    title: tx('Norm 编辑器', 'Norm Editor'),
    subtitle: desc.label,
    hint: tx('支持 JSON/文本；保存后会刷新目录与版本。', 'Supports JSON/text; save refreshes catalog and versions.'),
    loadText: async () => {
      const d = await api(desc.getPath);
      return _normEditorContent(desc.scope, d);
    },
    saveText: async (text) => {
      const body = _normWriteBody(desc.scope, text);
      await apiWrite(desc.putPath, 'PUT', body);
    },
    onSaved: async () => {
      await Promise.all([loadNormCatalog(), loadNormVersions()]);
    },
  });
  if (ok) {
    if (meta) meta.textContent = tx(`Editing ${desc.label}`, `Editing ${desc.label}`);
  } else if (meta) {
    meta.textContent = tx(`Failed to load ${desc.label}`, `Failed to load ${desc.label}`);
  }
}

async function saveNormEditor() {
  await saveUnifiedEditor();
}

async function loadNormCatalog() {
  const qualityTbody = document.getElementById('norm-quality-tbody');
  const prefTbody = document.getElementById('norm-pref-tbody');
  const rationTbody = document.getElementById('norm-ration-tbody');
  try {
    const [qualityKeys, prefs, rations] = await Promise.all([
      _loadNormScopeKeys('quality'),
      api('/console/norm/preferences'),
      api('/console/norm/rations'),
    ]);
    if (qualityTbody) {
      qualityTbody.innerHTML = (qualityKeys || []).map((k) => `
        <tr>
          <td title="${esc(k)}">${esc(k)}</td>
          <td style="color:var(--muted)">—</td>
          <td style="color:var(--muted)">—</td>
          <td class="col-action-cell"><button class="action" style="font-size:11px;padding:3px 8px;background:#334155" onclick="editNormKey('quality','${encodeURIComponent(k)}')">${tx('编辑', 'Edit')}</button></td>
        </tr>
      `).join('') || `<tr><td colspan="4" style="color:var(--muted)">${tx('暂无质量键', 'No quality keys')}</td></tr>`;
    }
    if (prefTbody) {
      prefTbody.innerHTML = (prefs || []).map((p) => `
        <tr>
          <td title="${esc(p.pref_key || '')}">${esc(p.pref_key || '')}</td>
          <td style="color:var(--muted)" title="${esc(p.value || '')}">${esc((p.value || '').slice(0, 120))}</td>
          <td style="color:var(--muted)">preference</td>
          <td class="col-action-cell"><button class="action" style="font-size:11px;padding:3px 8px;background:#334155" onclick="editNormKey('preference','${encodeURIComponent(p.pref_key || '')}')">${tx('编辑', 'Edit')}</button></td>
        </tr>
      `).join('') || `<tr><td colspan="4" style="color:var(--muted)">${tx('暂无偏好配置', 'No preferences')}</td></tr>`;
    }
    if (rationTbody) {
      rationTbody.innerHTML = (rations || []).map((b) => `
        <tr>
          <td title="${esc(b.resource_type || '')}">${esc(b.resource_type || '')}</td>
          <td>${Number(b.daily_limit || 0).toLocaleString()}</td>
          <td>${Number(b.current_usage || 0).toLocaleString()}</td>
          <td class="col-action-cell"><button class="action" style="font-size:11px;padding:3px 8px;background:#334155" onclick="editNormKey('ration','${encodeURIComponent(b.resource_type || '')}')">${tx('编辑', 'Edit')}</button></td>
        </tr>
      `).join('') || `<tr><td colspan="4" style="color:var(--muted)">${tx('暂无配额配置', 'No rations')}</td></tr>`;
    }
    await refreshNormKeyOptions(false);
  } catch (e) {
    if (qualityTbody) qualityTbody.innerHTML = `<tr><td colspan="4" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
    if (prefTbody) prefTbody.innerHTML = `<tr><td colspan="4" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
    if (rationTbody) rationTbody.innerHTML = `<tr><td colspan="4" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
  }
}

async function editNormKey(scope, keyEncoded) {
  const key = decodeURIComponent(keyEncoded || '');
  const scopeEl = document.getElementById('norm-scope');
  const keySel = document.getElementById('norm-key-select');
  if (scopeEl) scopeEl.value = scope;
  await onNormScopeChange(false, false);
  if (keySel && Array.from(keySel.options).some((opt) => opt.value === key)) {
    keySel.value = key;
    currentNormType = key;
  }
  await loadNormEditor();
}

async function loadNormVersions() {
  const desc = _normDescriptor();
  const tbody = document.getElementById('norm-versions-tbody');
  try {
    const versions = await api(desc.versionsPath);
    currentNormVersions = Array.isArray(versions) ? versions : [];
    if (!currentNormVersions.length) {
      tbody.innerHTML = `<tr><td colspan="5" style="color:var(--muted)">${tx('未找到版本', 'No versions found')}</td></tr>`;
      populateNormVersionSelect([]);
      return;
    }
    tbody.innerHTML = currentNormVersions.map((v) => `
      <tr>
        <td>v${v.version}</td>
        <td style="color:var(--muted)">${fmtTime(v.changed_utc)}</td>
        <td style="color:var(--muted)">${esc(v.changed_by || '')}</td>
        <td style="color:var(--muted)">${esc(v.reason || '')}</td>
        <td>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#334155" onclick="viewNormVersion(${v.version})">${tx('查看', 'View')}</button>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#7f1d1d" onclick="rollbackNormVersion(${v.version})">${tx('回滚', 'Rollback')}</button>
        </td>
      </tr>
    `).join('');
    populateNormVersionSelect(currentNormVersions);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
  }
}

function populateNormVersionSelect(versions) {
  const sel = document.getElementById('norm-version-select');
  if (!sel) return;
  const opts = [`<option value="">${tx('选择版本', 'Select version')}</option>`].concat(
    (versions || []).map((v) => `<option value="${v.version}">v${v.version}</option>`)
  ).join('');
  sel.innerHTML = opts;
}

function selectedNormVersion() {
  const sel = document.getElementById('norm-version-select');
  const v = Number(sel?.value || 0);
  if (!v) return null;
  return v;
}

function _normVersionValue(version) {
  const row = currentNormVersions.find((v) => Number(v.version) === Number(version));
  if (!row) return null;
  try {
    return row.value_json ? JSON.parse(row.value_json) : null;
  } catch (_) {
    return null;
  }
}

async function viewNormVersion(version) {
  const desc = _normDescriptor();
  const value = _normVersionValue(version);
  if (!value) return;
  const meta = document.getElementById('norm-editor-meta');
  if (meta) meta.textContent = tx(`Viewing v${version} of ${desc.label}`, `Viewing v${version} of ${desc.label}`);
  await openUnifiedEditor({
    key: `norm-version:${desc.scope}:${desc.key}:v${version}`,
    title: tx('Norm 版本预览', 'Norm Version Preview'),
    subtitle: `${desc.label} / v${version}`,
    hint: tx('只读预览；如需修改请使用 Edit Norm。', 'Read-only preview. Use Edit Norm for modifications.'),
    readOnly: true,
    loadText: async () => _normEditorContent(desc.scope, value),
  });
}

async function viewSelectedNormVersion() {
  const v = selectedNormVersion();
  const preview = document.getElementById('norm-version-preview');
  if (!v) {
    if (preview) preview.textContent = tx('请选择一个版本。', 'Please select one version.');
    return;
  }
  const value = _normVersionValue(v);
  if (!value) {
    if (preview) preview.textContent = tx('无法解析所选版本。', 'Unable to parse selected version.');
    return;
  }
  if (preview) preview.textContent = JSON.stringify(value, null, 2);
  await viewNormVersion(v);
}

async function rollbackNormVersion(version) {
  const desc = _normDescriptor();
  if (!confirm(tx(`确认回滚 ${desc.label} 到 v${version} 吗？`, `Rollback ${desc.label} to v${version}?`))) return;
  try {
    await apiWrite(desc.rollbackPath + version, 'POST', {});
    await loadNorm();
  } catch (e) {
    alert(tx('回滚失败：', 'Rollback failed: ') + e.message);
  }
}

async function rollbackSelectedNormVersion() {
  const v = selectedNormVersion();
  if (!v) {
    alert(tx('请选择一个版本。', 'Please select one version.'));
    return;
  }
  await rollbackNormVersion(v);
}
