async function loadSchedules() {
  const q = document.getElementById('schedules-q')?.value?.trim() || '';
  const sizeSel = Number(document.getElementById('schedules-page-size')?.value || 20);
  _listState('schedules', {size: sizeSel}).size = sizeSel;
  const routines = await api('/console/schedules');
  const routineSelect = document.getElementById('schedule-history-routine');
  if (routineSelect) {
    const existing = routineSelect.value || '';
    routineSelect.innerHTML = `<option value="">${tx('全部 routines', 'All routines')}</option>` + routines.map(r => `<option value="${r.routine}">${r.routine}</option>`).join('');
    if (existing) routineSelect.value = existing;
  }
  const filtered = _applyListQuery(routines || [], q, ['routine', 'mode', 'schedule', 'next_run_utc', 'last_run_utc']);
  const pageRows = _paginate(filtered, 'schedules', 'schedules-pager', 'loadSchedules');
  document.getElementById('schedules-tbody').innerHTML = pageRows.map(r =>
    `<tr>
      <td>${r.routine}</td>
      <td><span class="badge ${r.mode}">${r.mode}</span></td>
      <td style="color:var(--muted)">${r.enabled === false ? '(disabled) ' : ''}${r.schedule || '—'}</td>
      <td style="color:var(--muted)">${r.last_run_utc ? fmtTime(r.last_run_utc) : tx('从未', 'never')}</td>
      <td style="color:var(--muted)">${r.next_run_utc ? fmtTime(r.next_run_utc) : '—'}</td>
      <td>
        <button class="action" onclick="triggerRoutine('${r.routine.replace('spine.','')}')" style="font-size:11px;padding:3px 8px">${tx('▶ 运行', '▶ Run')}</button>
        <button class="action" onclick="editSchedule('${r.routine}')" style="font-size:11px;padding:3px 8px;background:#334155">${tx('✎ 编辑', '✎ Edit')}</button>
      </td>
    </tr>`
  ).join('') || `<tr><td colspan="6" style="color:var(--muted)">${tx('暂无调度', 'No schedules')}</td></tr>`;
  await loadScheduleHistory();
}

async function editSchedule(routine) {
  const rows = await api('/console/schedules');
  const row = (rows || []).find(r => String(r.routine || '') === String(routine || ''));
  const routineId = String(routine || '');
  if (!routineId || !row) return;
  await openUnifiedEditor({
    key: `schedule:${routineId}`,
    title: tx('调度编辑器', 'Schedule Editor'),
    subtitle: routineId,
    hint: tx('以 JSON 编辑：{"schedule":"cron/adaptive","enabled":true}', 'Edit as JSON: {"schedule":"cron/adaptive","enabled":true}'),
    loadText: async () => JSON.stringify({
      schedule: String(row?.schedule || ''),
      enabled: row?.enabled !== false,
    }, null, 2),
    saveText: async (text) => {
      let parsed = {};
      try {
        parsed = JSON.parse(String(text || '{}'));
      } catch (e) {
        throw new Error(tx('调度 JSON 无效：', 'Invalid schedule JSON: ') + e.message);
      }
      const schedule = String(parsed?.schedule || '').trim();
      const enabled = parsed?.enabled !== false;
      await apiWrite('/console/schedules/' + encodeURIComponent(routineId), 'PUT', {
        schedule: schedule || undefined,
        enabled,
      });
    },
    onSaved: async () => {
      await loadSchedules();
    },
  });
}

async function loadScheduleHistory() {
  const tbody = document.getElementById('schedule-history-tbody');
  if (!tbody) return;
  const q = document.getElementById('schedule-history-q')?.value?.trim() || '';
  const preset = document.getElementById('schedule-history-date-preset')?.value || 'all';
  const sizeSel = Number(document.getElementById('schedule-history-page-size')?.value || 20);
  _listState('schedule_history', {size: sizeSel}).size = sizeSel;
  let url = '/console/schedules/history?limit=500';
  const routine = document.getElementById('schedule-history-routine')?.value || '';
  if (routine) url += '&routine=' + encodeURIComponent(routine);
  try {
    const rows = await api(url);
    let filtered = rows || [];
    if (preset !== 'all') {
      const now = Date.now();
      let deltaMs = 0;
      if (preset === 'today') {
        const d = new Date();
        deltaMs = now - Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), 0, 0, 0);
      } else if (preset === 'last_24h') {
        deltaMs = 24 * 3600 * 1000;
      } else if (preset === 'last_7d') {
        deltaMs = 7 * 24 * 3600 * 1000;
      }
      const cutoff = now - deltaMs;
      filtered = filtered.filter((r) => {
        const ts = Date.parse(String(r?.run_utc || ''));
        return Number.isFinite(ts) ? ts >= cutoff : false;
      });
    }
    filtered = _applyListQuery(filtered, q, ['run_utc', 'routine', 'trigger', 'status']);
    const pageRows = _paginate(filtered, 'schedule_history', 'schedule-history-pager', 'loadScheduleHistory');
    tbody.innerHTML = pageRows.map(r => `
      <tr>
        <td style="color:var(--muted)">${fmtTime(r.run_utc)}</td>
        <td>${esc(r.routine||'')}</td>
        <td style="color:var(--muted)">${esc(r.trigger||'')}</td>
        <td><span class="badge ${r.status==='ok'?'ok':r.status==='contract_failed'?'degraded':'error'}">${esc(r.status||'')}</span></td>
        <td style="color:var(--muted);font-size:11px">${esc(JSON.stringify(r.detail||{}).slice(0,140))}</td>
      </tr>
    `).join('') || `<tr><td colspan="5" style="color:var(--muted)">${tx('暂无历史', 'No history')}</td></tr>`;
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
  }
}

// ── User Circuits ──────────────────────────────────────────────────────────

async function loadCircuits() {
  const tbody = document.getElementById('circuits-tbody');
  if (!tbody) return;
  try {
    const circuits = await api('/circuits');
    if (!circuits || !circuits.length) {
      tbody.innerHTML = `<tr><td colspan="6" style="color:var(--muted)">${tx('暂无周期 Circuit', 'No circuits')}</td></tr>`;
      return;
    }
    tbody.innerHTML = circuits.map(c => {
      const status = c.status || 'active';
      const badge = status === 'active' ? 'ok' : status === 'paused' ? 'degraded' : 'error';
      return `<tr>
        <td>${esc(c.run_title||c.name||'')}</td>
        <td style="color:var(--muted);font-family:monospace">${esc(c.cron||'')}</td>
        <td style="color:var(--muted)">${esc(c.run_type||'')}</td>
        <td><span class="badge ${badge}">${status}</span></td>
        <td style="color:var(--muted)">${c.last_triggered_utc ? fmtTime(c.last_triggered_utc) : '—'}</td>
        <td style="color:var(--muted)">${c.run_count||0}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
  }
}
