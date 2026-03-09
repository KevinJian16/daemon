async function loadOverview() {
  const d = await api('/console/overview');
  const ward = d.ward?.status || d.gate?.status || 'GREEN';
  const badge = document.getElementById('ward-badge');
  badge.textContent = ward;
  badge.className = ward;
  updateWardLabel(ward);
  document.getElementById('stat-memory').textContent = d.memory?.total_active ?? '—';
  document.getElementById('stat-methods').textContent = d.lore?.by_status?.active ?? '—';
  document.getElementById('stat-signals').textContent = d.instinct?.active_signals ?? '—';
  document.getElementById('stat-deeds').textContent = d.running_deeds ?? '—';
  runningDeedsCount = Number(d.running_deeds ?? 0);
  document.getElementById('running-deeds').textContent = tx(`${runningDeedsCount} 运行中`, `${runningDeedsCount} running`);

  const usage = d.cortex_usage?.by_provider || {};
  let html = `<table><thead><tr><th>${tx('提供方', 'Provider')}</th><th>${tx('调用', 'Calls')}</th><th>${tx('输入 Tokens', 'In Tokens')}</th><th>${tx('输出 Tokens', 'Out Tokens')}</th><th>${tx('错误', 'Errors')}</th></tr></thead><tbody>`;
  for (const [p, u] of Object.entries(usage)) {
    html += `<tr><td>${p}</td><td>${u.calls}</td><td>${(u.in_tokens||0).toLocaleString()}</td><td>${(u.out_tokens||0).toLocaleString()}</td><td>${u.errors||0}</td></tr>`;
  }
  if (!Object.keys(usage).length) html += `<tr><td colspan="5" style="color:var(--muted)">${tx('今天暂无调用', 'No calls today')}</td></tr>`;
  html += '</tbody></table>';
  document.getElementById('cortex-table').innerHTML = html;
}

async function loadSpine() {
  const routines = await api('/console/spine/status');
  const tbody = document.getElementById('spine-tbody');
  tbody.innerHTML = routines.map(r => `
    <tr>
      <td>${r.routine}</td>
      <td><span class="badge ${r.mode}">${r.mode}</span></td>
      <td style="color:var(--muted)">${r.last_run_utc ? fmtTime(r.last_run_utc) : tx('从未', 'never')}</td>
    </tr>`).join('');

  const events = await api('/console/spine/nerve/events?limit=30');
  const feed = document.getElementById('nerve-feed');
  if (!events.length) {
    feed.innerHTML = `<div style="color:var(--muted)">${tx('暂无事件', 'No events yet')}</div>`;
  } else {
    feed.innerHTML = events.reverse().map(e =>
      `<div><span class="ts">${e.timestamp}</span> <strong>${e.event}</strong> ${JSON.stringify(e.payload).slice(0,80)}</div>`
    ).join('');
  }

  const depNode = document.getElementById('spine-deps');
  if (!depNode) return;
  try {
    const deps = await api('/console/spine/dependencies');
    if (!deps.length) {
      depNode.textContent = tx('未找到 routine 定义。', 'No routine definitions found.');
      return;
    }
    const sorted = deps.slice().sort((a, b) => String(a.routine||'').localeCompare(String(b.routine||'')));
    const lines = [tx('# Spine 依赖视图', '# Spine Dependency View'), ''];
    for (const row of sorted) {
      const depsText = (row.depends_on || []).length ? row.depends_on.join(', ') : '[root]';
      lines.push(`${row.routine} (${row.mode || 'deterministic'}) <- ${depsText}`);
      lines.push(`  ${tx('读取', 'reads')}: ${(row.reads || []).join(', ') || '—'}`);
      lines.push(`  ${tx('写入', 'writes')}: ${(row.writes || []).join(', ') || '—'}`);
    }
    lines.push('');
    lines.push(tx('# 边', '# Edges'));
    let edgeCount = 0;
    for (const row of sorted) {
      for (const d of (row.depends_on || [])) {
        lines.push(`${d} -> ${row.routine}`);
        edgeCount += 1;
      }
    }
    if (!edgeCount) lines.push(tx('无依赖边。', 'No dependency edges.'));
    depNode.textContent = lines.join('\n');
  } catch (e) {
    depNode.textContent = tx('加载依赖失败：', 'Error loading dependencies: ') + e.message;
  }
}

async function triggerRoutine(name) {
  try {
    const r = await fetch(`${API}/console/spine/${name}/trigger`, {method:'POST'});
    const d = await r.json();
    alert(d.ok ? tx(`✓ ${name} 已触发`, `✓ ${name} triggered`) : `✗ ${d.error || d.detail}`);
    loadSpine();
  } catch(e) { alert(tx('错误：', 'Error: ') + e.message); }
}

