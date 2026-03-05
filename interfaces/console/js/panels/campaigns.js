async function loadCampaigns() {
  const tbody = document.getElementById('campaigns-tbody');
  if (!tbody) return;
  const q = document.getElementById('campaign-q')?.value?.trim() || '';
  const sizeSel = Number(document.getElementById('campaign-page-size')?.value || 20);
  _listState('campaigns', {size: sizeSel}).size = sizeSel;
  try {
    const rows = await api('/campaigns?limit=500');
    const filtered = _applyListQuery(rows || [], q, ['campaign_id', 'task_id', 'status', 'current_phase', 'updated_utc']);
    const pageRows = _paginate(filtered, 'campaigns', 'campaigns-pager', 'loadCampaigns');
    tbody.innerHTML = pageRows.map(r => `
      <tr>
        <td style="color:var(--muted);font-size:11px">${esc(r.campaign_id || '')}</td>
        <td style="color:var(--muted);font-size:11px">${esc(r.task_id || '')}</td>
        <td><span class="badge ${r.status==='completed' ? 'ok' : r.status==='running' ? 'hybrid' : r.status==='paused' ? 'degraded' : r.status==='cancelled' ? 'error' : 'deterministic'}">${esc(r.status || '')}</span></td>
        <td>${esc(r.current_phase || '')}</td>
        <td>${Number(r.current_milestone_index || 0)} / ${Number(r.total_milestones || 0)}</td>
        <td style="color:var(--muted)">${fmtTime(r.updated_utc)}</td>
        <td>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#334155" onclick="viewCampaign('${encodeURIComponent(r.campaign_id || '')}')">${tx('查看', 'View')}</button>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#0f766e" onclick="confirmCampaign('${encodeURIComponent(r.campaign_id || '')}')">${tx('确认', 'Confirm')}</button>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#14532d" onclick="resumeCampaign('${encodeURIComponent(r.campaign_id || '')}')">${tx('恢复', 'Resume')}</button>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#7f1d1d" onclick="cancelCampaign('${encodeURIComponent(r.campaign_id || '')}')">${tx('取消', 'Cancel')}</button>
        </td>
      </tr>
    `).join('') || `<tr><td colspan="7" style="color:var(--muted)">${tx('暂无 Campaign', 'No campaigns')}</td></tr>`;
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
  }
}

async function viewCampaign(campaignKey) {
  const campaignId = decodeURIComponent(campaignKey || '');
  if (!campaignId) return;
  const target = document.getElementById('campaign-detail');
  if (!target) return;
  target.textContent = tx('加载 Campaign 详情…', 'Loading campaign detail…');
  try {
    const row = await api('/campaigns/' + encodeURIComponent(campaignId));
    target.textContent = JSON.stringify(row, null, 2);
  } catch (e) {
    target.textContent = tx('错误：', 'Error: ') + e.message;
  }
}

async function resumeCampaign(campaignKey) {
  const campaignId = decodeURIComponent(campaignKey || '');
  if (!campaignId) return;
  let detail = null;
  try {
    detail = await api('/campaigns/' + encodeURIComponent(campaignId));
  } catch (e) {
    alert(tx('加载 Campaign 详情失败：', 'Load campaign detail failed: ') + e.message);
    return;
  }
  const manifest = detail?.manifest || {};
  const phase = String(manifest.current_phase || '');
  const payload = {};
  if (phase === 'phase0_waiting_confirmation') {
    payload.confirmed = true;
  }
  if (phase === 'milestone_waiting_feedback') {
    const satisfied = confirm(tx(`Campaign ${campaignId} 里程碑反馈：点确定=满意，点取消=不满意`, `Campaign ${campaignId} milestone feedback: click OK=satisfied, Cancel=unsatisfied`));
    const comment = prompt(tx('反馈备注（可选）：', 'Feedback comment (optional):'), '') || '';
    payload.feedback = {
      satisfied,
      rating: satisfied ? 5 : 2,
      comment,
      source: 'console',
    };
  }
  const resumeFromRaw = prompt(tx(`从哪个 milestone 序号恢复 ${campaignId}（从 0 开始，留空=当前）：`, `Resume ${campaignId} from milestone index (0-based, empty = current):`), '');
  if (resumeFromRaw !== null && String(resumeFromRaw).trim() !== '') {
    const v = Number(resumeFromRaw);
    if (!Number.isNaN(v)) payload.resume_from = Math.max(0, Math.floor(v));
  }
  try {
    await apiWrite('/campaigns/' + encodeURIComponent(campaignId) + '/resume', 'POST', payload);
    await loadCampaigns();
    await viewCampaign(encodeURIComponent(campaignId));
  } catch (e) {
    alert(tx('恢复 Campaign 失败：', 'Resume campaign failed: ') + e.message);
  }
}

async function confirmCampaign(campaignKey) {
  const campaignId = decodeURIComponent(campaignKey || '');
  if (!campaignId) return;
  if (!confirm(tx(`确认 Campaign ${campaignId} 并开始执行吗？`, `Confirm campaign ${campaignId} and start execution?`))) return;
  try {
    await apiWrite('/campaigns/' + encodeURIComponent(campaignId) + '/confirm', 'POST', {});
    await loadCampaigns();
    await viewCampaign(encodeURIComponent(campaignId));
  } catch (e) {
    alert(tx('确认 Campaign 失败：', 'Confirm campaign failed: ') + e.message);
  }
}

async function cancelCampaign(campaignKey) {
  const campaignId = decodeURIComponent(campaignKey || '');
  if (!campaignId) return;
  if (!confirm(tx(`确认取消 Campaign ${campaignId} 吗？`, `Cancel campaign ${campaignId}?`))) return;
  try {
    await apiWrite('/campaigns/' + encodeURIComponent(campaignId) + '/cancel', 'POST', {});
    await loadCampaigns();
    await viewCampaign(encodeURIComponent(campaignId));
  } catch (e) {
    alert(tx('取消 Campaign 失败：', 'Cancel campaign failed: ') + e.message);
  }
}
