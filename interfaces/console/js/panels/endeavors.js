async function loadEndeavors() {
  const tbody = document.getElementById('endeavors-tbody');
  if (!tbody) return;
  const q = document.getElementById('endeavor-q')?.value?.trim() || '';
  const sizeSel = Number(document.getElementById('endeavor-page-size')?.value || 20);
  _listState('endeavors', {size: sizeSel}).size = sizeSel;
  try {
    const rows = await api('/endeavors?limit=500');
    const normalized = (rows || []).map((r) => ({
      ...r,
      endeavor_status: r.endeavor_status || '',
      endeavor_phase: r.endeavor_phase || '',
    }));
    const filtered = _applyListQuery(normalized, q, ['endeavor_id', 'deed_id', 'endeavor_status', 'endeavor_phase', 'updated_utc']);
    const pageRows = _paginate(filtered, 'endeavors', 'endeavors-pager', 'loadEndeavors');
    tbody.innerHTML = pageRows.map(r => `
      <tr>
        <td style="color:var(--muted);font-size:11px">${esc(r.endeavor_id || '')}</td>
        <td style="color:var(--muted);font-size:11px">${esc(r.deed_id || '')}</td>
        <td><span class="badge ${r.endeavor_status==='completed' ? 'ok' : r.endeavor_status==='running' ? 'hybrid' : r.endeavor_status==='paused' ? 'degraded' : r.endeavor_status==='cancelled' ? 'error' : 'deterministic'}">${esc(r.endeavor_status || '')}</span></td>
        <td>${esc(r.endeavor_phase || '')}</td>
        <td>${Number(r.current_passage_index || 0)} / ${Number(r.total_passages || 0)}</td>
        <td style="color:var(--muted)">${fmtTime(r.updated_utc)}</td>
        <td>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#334155" onclick="viewEndeavor('${encodeURIComponent(r.endeavor_id || '')}')">${tx('查看', 'View')}</button>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#0f766e" onclick="confirmEndeavor('${encodeURIComponent(r.endeavor_id || '')}')">${tx('确认', 'Confirm')}</button>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#14532d" onclick="resumeEndeavor('${encodeURIComponent(r.endeavor_id || '')}')">${tx('恢复', 'Resume')}</button>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#7f1d1d" onclick="cancelEndeavor('${encodeURIComponent(r.endeavor_id || '')}')">${tx('取消', 'Cancel')}</button>
        </td>
      </tr>
    `).join('') || `<tr><td colspan="7" style="color:var(--muted)">${tx('暂无 Endeavor', 'No endeavors')}</td></tr>`;
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
  }
}

async function viewEndeavor(endeavorKey) {
  const endeavorId = decodeURIComponent(endeavorKey || '');
  if (!endeavorId) return;
  const target = document.getElementById('endeavor-detail');
  if (!target) return;
  target.textContent = tx('加载 Endeavor 详情…', 'Loading endeavor detail…');
  try {
    const row = await api('/endeavors/' + encodeURIComponent(endeavorId));
    target.textContent = JSON.stringify(row, null, 2);
  } catch (e) {
    target.textContent = tx('错误：', 'Error: ') + e.message;
  }
}

async function resumeEndeavor(endeavorKey) {
  const endeavorId = decodeURIComponent(endeavorKey || '');
  if (!endeavorId) return;
  let detail = null;
  try {
    detail = await api('/endeavors/' + encodeURIComponent(endeavorId));
  } catch (e) {
    alert(tx('加载 Endeavor 详情失败：', 'Load endeavor detail failed: ') + e.message);
    return;
  }
  const manifest = detail?.manifest || {};
  const phase = String(manifest.endeavor_phase || '');
  const payload = {};
  if (phase === 'phase0_waiting_confirmation') {
    payload.confirmed = true;
  }
  if (phase === 'passage_waiting_feedback') {
    const satisfied = confirm(tx(`Endeavor ${endeavorId} 段落反馈：点确定=满意，点取消=不满意`, `Endeavor ${endeavorId} passage feedback: click OK=satisfied, Cancel=unsatisfied`));
    const comment = prompt(tx('反馈备注（可选）：', 'Feedback comment (optional):'), '') || '';
    payload.feedback = {
      satisfied,
      rating: satisfied ? 5 : 2,
      comment,
      source: 'console',
    };
  }
  const resumeFromRaw = prompt(tx(`从哪个 passage 序号恢复 ${endeavorId}（从 0 开始，留空=当前）：`, `Resume ${endeavorId} from passage index (0-based, empty = current):`), '');
  if (resumeFromRaw !== null && String(resumeFromRaw).trim() !== '') {
    const v = Number(resumeFromRaw);
    if (!Number.isNaN(v)) payload.resume_from = Math.max(0, Math.floor(v));
  }
  try {
    await apiWrite('/endeavors/' + encodeURIComponent(endeavorId) + '/resume', 'POST', payload);
    await loadEndeavors();
    await viewEndeavor(encodeURIComponent(endeavorId));
  } catch (e) {
    alert(tx('恢复 Endeavor 失败：', 'Resume endeavor failed: ') + e.message);
  }
}

async function confirmEndeavor(endeavorKey) {
  const endeavorId = decodeURIComponent(endeavorKey || '');
  if (!endeavorId) return;
  if (!confirm(tx(`确认 Endeavor ${endeavorId} 并开始执行吗？`, `Confirm endeavor ${endeavorId} and start execution?`))) return;
  try {
    await apiWrite('/endeavors/' + encodeURIComponent(endeavorId) + '/confirm', 'POST', {});
    await loadEndeavors();
    await viewEndeavor(encodeURIComponent(endeavorId));
  } catch (e) {
    alert(tx('确认 Endeavor 失败：', 'Confirm endeavor failed: ') + e.message);
  }
}

async function cancelEndeavor(endeavorKey) {
  const endeavorId = decodeURIComponent(endeavorKey || '');
  if (!endeavorId) return;
  if (!confirm(tx(`确认取消 Endeavor ${endeavorId} 吗？`, `Cancel endeavor ${endeavorId}?`))) return;
  try {
    await apiWrite('/endeavors/' + encodeURIComponent(endeavorId) + '/cancel', 'POST', {});
    await loadEndeavors();
    await viewEndeavor(encodeURIComponent(endeavorId));
  } catch (e) {
    alert(tx('取消 Endeavor 失败：', 'Cancel endeavor failed: ') + e.message);
  }
}
