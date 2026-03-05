async function loadTraces() {
  const routine = document.getElementById('trace-routine').value;
  const status = document.getElementById('trace-status').value;
  const q = document.getElementById('trace-q')?.value?.trim() || '';
  const sizeSel = Number(document.getElementById('trace-page-size')?.value || 50);
  _listState('traces', {size: sizeSel}).size = sizeSel;
  const preset = document.getElementById('trace-date-preset')?.value || 'last_24h';
  const now = new Date();
  const toIso = (d) => d.toISOString().replace(/\.\d{3}Z$/, 'Z');
  let since = '';
  if (preset === 'last_1h') since = toIso(new Date(now.getTime() - 1 * 3600 * 1000));
  else if (preset === 'last_6h') since = toIso(new Date(now.getTime() - 6 * 3600 * 1000));
  else if (preset === 'last_24h') since = toIso(new Date(now.getTime() - 24 * 3600 * 1000));
  else if (preset === 'last_7d') since = toIso(new Date(now.getTime() - 7 * 24 * 3600 * 1000));
  let url = '/console/traces?limit=1000';
  if (routine) url += '&routine=' + encodeURIComponent(routine);
  if (status) url += '&status=' + status;
  if (since) url += '&since=' + encodeURIComponent(since);
  try {
    const rows = await api(url);
    const filtered = _applyListQuery(rows || [], q, ['trace_id', 'routine', 'status', 'started_utc', 'error']);
    const traces = _paginate(filtered, 'traces', 'traces-pager', 'loadTraces');
    document.getElementById('traces-tbody').innerHTML = traces.map(t => {
      const rawId = String(t.trace_id || '');
      const shortId = rawId.length > 14 ? `${rawId.slice(0, 14)}…` : rawId;
      return `<tr>
        <td style="color:var(--muted);font-size:11px"><button class="action trace-id-btn" title="${esc(rawId)}" style="font-size:10px;padding:2px 6px;background:#334155" onclick="loadTraceDetail('${t.trace_id}')">${esc(shortId)}</button></td>
        <td>${t.routine}</td>
        <td><span class="badge ${t.status}">${t.status}</span></td>
        <td>${t.degraded ? '<span class="badge degraded">yes</span>' : '—'}</td>
        <td style="color:var(--muted)">${fmtTime(t.started_utc)}</td>
        <td>${t.elapsed_s}s</td>
      </tr>`;
    }).join('') || `<tr><td colspan="6" style="color:var(--muted)">${tx('未找到 traces', 'No traces found')}</td></tr>`;
  } catch (e) {
    document.getElementById('traces-tbody').innerHTML = `<tr><td colspan="6" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
    const pager = document.getElementById('traces-pager');
    if (pager) pager.innerHTML = '';
  }
}

async function loadTraceDetail(traceId) {
  const target = document.getElementById('trace-detail');
  target.textContent = tx('加载 trace 详情…', 'Loading trace detail…');
  try {
    const t = await api('/console/traces/' + encodeURIComponent(traceId));
    const lines = [];
    lines.push(`# ${t.trace_id || traceId}`);
    lines.push(`routine: ${t.routine || ''}`);
    lines.push(`status: ${t.status || ''} (degraded: ${t.degraded ? 'yes' : 'no'})`);
    lines.push(`started_utc: ${t.started_utc || ''}`);
    lines.push(`elapsed_s: ${t.elapsed_s || 0}`);
    if (t.error) lines.push(`error: ${t.error}`);
    lines.push('');
    lines.push(tx('## 步骤', '## Steps'));
    const steps = Array.isArray(t.steps) ? t.steps : [];
    if (!steps.length) {
      lines.push(tx('- 未记录步骤', '- no steps recorded'));
    } else {
      for (const s of steps) {
        lines.push(`- [${s.t ?? 0}s] ${s.name || 'step'}`);
        if (s.detail !== undefined && s.detail !== null && s.detail !== '') {
          lines.push(`  detail: ${JSON.stringify(s.detail).slice(0, 500)}`);
        }
      }
    }
    lines.push('');
    lines.push(tx('## 结果', '## Result'));
    lines.push(JSON.stringify(t.result || {}, null, 2));
    lines.push('');
    lines.push(tx('## Cortex 汇总', '## Cortex Summary'));
    const cs = t.cortex_summary || {};
    lines.push(`total_calls: ${cs.total_calls || 0}`);
    lines.push(`total_in_tokens: ${cs.total_in_tokens || 0}`);
    lines.push(`total_out_tokens: ${cs.total_out_tokens || 0}`);
    const bp = cs.by_provider || {};
    const providers = Object.keys(bp);
    if (!providers.length) {
      lines.push(tx('- 无关联 cortex 调用', '- no cortex calls attributed'));
    } else {
      lines.push(tx('- 按 provider：', '- by_provider:'));
      for (const p of providers) {
        const row = bp[p] || {};
        lines.push(`  - ${p}: calls=${row.calls||0}, in=${row.in_tokens||0}, out=${row.out_tokens||0}, errors=${row.errors||0}, avg_elapsed_s=${row.avg_elapsed_s||0}`);
      }
    }
    const latest = Array.isArray(cs.latest_calls) ? cs.latest_calls : [];
    if (latest.length) {
      lines.push(tx('- 最近调用：', '- latest_calls:'));
      for (const c of latest) {
        lines.push(`  - [${c.timestamp||''}] ${c.provider||'unknown'} ${c.model||''} in=${c.in_tokens||0} out=${c.out_tokens||0} elapsed=${c.elapsed_s||0}s success=${c.success ? 'yes' : 'no'}`);
        if (c.prompt_preview) lines.push(`    prompt: ${String(c.prompt_preview).slice(0, 180)}`);
        if (c.output_preview) lines.push(`    output: ${String(c.output_preview).slice(0, 180)}`);
        if (c.error) lines.push(`    error: ${String(c.error).slice(0, 180)}`);
      }
    }
    target.textContent = lines.join('\n');
  } catch (e) {
    target.textContent = tx('加载 trace 详情失败：', 'Error loading trace detail: ') + e.message;
}
}

function jumpToTrace(traceId) {
  const resolved = decodeURIComponent(traceId || '');
  if (!resolved) return;
  const btn = Array.from(document.querySelectorAll('nav button')).find(b => (b.getAttribute('onclick') || '').includes("show('traces'"));
  show('traces', btn || null);
  loadTraceDetail(resolved);
}

async function loadCortexUsage() {
  const tbody = document.getElementById('cortex-usage-tbody');
  const summary = document.getElementById('cortex-usage-summary');
  const preset = document.getElementById('cortex-date-preset')?.value || 'last_24h';
  const now = new Date();
  const toIso = (d) => d.toISOString().replace(/\.\d{3}Z$/, 'Z');
  let since = '';
  if (preset === 'last_1h') since = toIso(new Date(now.getTime() - 1 * 3600 * 1000));
  else if (preset === 'last_6h') since = toIso(new Date(now.getTime() - 6 * 3600 * 1000));
  else if (preset === 'last_24h') since = toIso(new Date(now.getTime() - 24 * 3600 * 1000));
  else if (preset === 'last_7d') since = toIso(new Date(now.getTime() - 7 * 24 * 3600 * 1000));
  const until = toIso(now);
  const q = document.getElementById('cortex-q')?.value?.trim() || '';
  const sizeSel = Number(document.getElementById('cortex-page-size')?.value || 20);
  _listState('cortex', {size: sizeSel}).size = sizeSel;
  let url = '/console/cortex/usage?limit=2000';
  if (since) url += '&since=' + encodeURIComponent(since);
  if (until) url += '&until=' + encodeURIComponent(until);
  try {
    const res = await api(url);
    const rows = Array.isArray(res.records) ? res.records : [];
    const filtered = _applyListQuery(rows, q, ['timestamp', 'trace_id', 'provider', 'model', 'routine']);
    const pageRows = _paginate(filtered, 'cortex', 'cortex-pager', 'loadCortexUsage');
    tbody.innerHTML = pageRows.map(r => {
      const rawTrace = String(r.trace_id || '');
      const traceLabel = esc(rawTrace);
      const traceAction = rawTrace
        ? `<button class="action" style="font-size:10px;padding:2px 6px;background:#334155" onclick="jumpToTrace('${encodeURIComponent(rawTrace)}')">${traceLabel}</button>`
        : '<span style="color:var(--muted)">—</span>';
      return `<tr>
        <td style="color:var(--muted)">${fmtTime(r.timestamp)}</td>
        <td>${traceAction}</td>
        <td>${esc(r.provider||'')}</td>
        <td style="color:var(--muted)">${esc(r.model||'')}</td>
        <td>${Number(r.in_tokens||0).toLocaleString()}</td>
        <td>${Number(r.out_tokens||0).toLocaleString()}</td>
        <td>${Number(r.elapsed_s||0).toFixed(2)}s</td>
        <td><span class="badge ${r.success ? 'ok' : 'error'}">${r.success ? tx('正常', 'ok') : tx('错误', 'error')}</span></td>
      </tr>`;
    }).join('') || `<tr><td colspan="8" style="color:var(--muted)">${tx('暂无用量记录', 'No usage records')}</td></tr>`;

    const byProvider = {};
    for (const r of filtered) {
      const p = String(r.provider || 'unknown');
      if (!byProvider[p]) byProvider[p] = {calls: 0, in_tokens: 0, out_tokens: 0, errors: 0, avg_elapsed_s: 0};
      byProvider[p].calls += 1;
      byProvider[p].in_tokens += Number(r.in_tokens || 0);
      byProvider[p].out_tokens += Number(r.out_tokens || 0);
      byProvider[p].avg_elapsed_s += Number(r.elapsed_s || 0);
      if (!r.success) byProvider[p].errors += 1;
    }
    for (const p of Object.keys(byProvider)) {
      const x = byProvider[p];
      x.avg_elapsed_s = x.calls ? Number((x.avg_elapsed_s / x.calls).toFixed(3)) : 0;
    }
    if (summary) {
      const providerRows = Object.entries(byProvider).sort((a, b) => b[1].calls - a[1].calls);
      summary.innerHTML = `
        <div class="model-table-shell">
          <table>
            <thead><tr><th>Provider</th><th>Calls</th><th>In</th><th>Out</th><th>Errors</th><th>Avg Elapsed</th></tr></thead>
            <tbody>
              ${providerRows.map(([provider, v]) => `
                <tr>
                  <td>${esc(provider)}</td>
                  <td>${Number(v.calls || 0).toLocaleString()}</td>
                  <td>${Number(v.in_tokens || 0).toLocaleString()}</td>
                  <td>${Number(v.out_tokens || 0).toLocaleString()}</td>
                  <td>${Number(v.errors || 0).toLocaleString()}</td>
                  <td>${Number(v.avg_elapsed_s || 0).toFixed(3)}s</td>
                </tr>
              `).join('') || `<tr><td colspan="6" style="color:var(--muted)">${tx('暂无汇总数据', 'No summary data')}</td></tr>`}
            </tbody>
          </table>
        </div>
      `;
    }
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
    if (summary) summary.innerHTML = `<div class="model-empty">${tx('加载用量汇总失败：', 'Error loading usage summary: ')}${esc(e.message)}</div>`;
  }
}
