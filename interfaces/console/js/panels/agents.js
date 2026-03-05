async function loadAgents() {
  const q = document.getElementById('agents-q')?.value?.trim() || '';
  const sizeSel = Number(document.getElementById('agents-page-size')?.value || 20);
  _listState('agents', {size: sizeSel}).size = sizeSel;
  const agents = await api('/console/agents');
  const filtered = _applyListQuery(agents || [], q, ['id', 'skills_count', 'workspace_exists']);
  const pageRows = _paginate(filtered, 'agents', 'agents-pager', 'loadAgents');
  document.getElementById('agents-tbody').innerHTML = pageRows.map(a =>
    `<tr>
      <td>${esc(a.id)}</td>
      <td>${a.skills_count}</td>
      <td><span class="badge ${a.workspace_exists ? 'ok' : 'error'}">${a.workspace_exists ? tx('就绪', 'ready') : tx('缺失', 'missing')}</span></td>
      <td><button class="action" style="font-size:11px;padding:3px 8px" onclick="manageAgent('${encodeURIComponent(a.id)}')">${tx('管理', 'Manage')}</button></td>
    </tr>`
  ).join('') || `<tr><td colspan="4" style="color:var(--muted)">${tx('未找到 agents', 'No agents found')}</td></tr>`;
  if (activeAgentId) {
    await reloadActiveAgentSkills();
  }
}

async function manageAgent(agentKey) {
  activeAgentId = decodeURIComponent(agentKey);
  await reloadActiveAgentSkills();
}

async function reloadActiveAgentSkills() {
  const tbody = document.getElementById('agent-skills-tbody');
  document.getElementById('skills-agent-tag').textContent = activeAgentId || tx('未选择 agent', 'No agent selected');
  if (!activeAgentId) {
    tbody.innerHTML = `<tr><td colspan="4" style="color:var(--muted)">${tx('请选择一个 agent 管理 skills', 'Select an agent to manage skills')}</td></tr>`;
    return;
  }
  try {
    const q = document.getElementById('agent-skills-q')?.value?.trim() || '';
    const sizeSel = Number(document.getElementById('agent-skills-page-size')?.value || 20);
    _listState('agent_skills', {size: sizeSel}).size = sizeSel;
    const skills = await api('/console/agents/' + encodeURIComponent(activeAgentId) + '/skills');
    activeAgentSkills = Array.isArray(skills) ? skills : [];
    if (!activeAgentSkills.length) {
      tbody.innerHTML = `<tr><td colspan="4" style="color:var(--muted)">${tx('未找到 skills', 'No skills found')}</td></tr>`;
      return;
    }
    const filtered = _applyListQuery(activeAgentSkills, q, ['skill', 'enabled', 'path']);
    const pageRows = _paginate(filtered, 'agent_skills', 'agent-skills-pager', 'reloadActiveAgentSkills');
    tbody.innerHTML = pageRows.map(s => {
      const skillKey = encodeURIComponent(s.skill || '');
      const enabled = !!s.enabled;
      return `<tr>
        <td>${esc(s.skill)}</td>
        <td><span class="badge ${enabled ? 'ok' : 'error'}">${enabled ? 'enabled' : 'disabled'}</span></td>
        <td style="color:var(--muted)">${esc((s.path||'').replace(/^.*openclaw\//, 'openclaw/'))}</td>
        <td>
          <button class="action" style="font-size:11px;padding:3px 8px;background:${enabled ? '#7f1d1d' : '#14532d'}" onclick="toggleSkillEnabled('${skillKey}', ${enabled ? 'true' : 'false'})">${enabled ? tx('禁用', 'Disable') : tx('启用', 'Enable')}</button>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#334155" onclick="openSkillEditor('${skillKey}')">${tx('编辑', 'Edit')}</button>
        </td>
      </tr>`;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
  }
}

async function toggleSkillEnabled(skillKey, currentlyEnabled) {
  if (!activeAgentId) return;
  const skill = decodeURIComponent(skillKey);
  try {
    await apiWrite(
      '/console/agents/' + encodeURIComponent(activeAgentId) + '/skills/' + encodeURIComponent(skill) + '/enabled',
      'PATCH',
      {enabled: !currentlyEnabled}
    );
    await reloadActiveAgentSkills();
    await loadAgents();
  } catch (e) {
    alert(tx('更新 Skill 状态失败：', 'Failed to update skill state: ') + e.message);
  }
}

async function openSkillEditor(skillKey) {
  const skill = decodeURIComponent(skillKey);
  const row = activeAgentSkills.find(s => s.skill === skill);
  if (!row) return;
  await openUnifiedEditor({
    key: `skill:${activeAgentId}:${skill}`,
    title: tx('Skill 编辑器', 'Skill Editor'),
    subtitle: `${activeAgentId} / ${skill}`,
    hint: tx('保存后会立即回写 SKILL.md 并刷新列表。', 'Save writes SKILL.md and refreshes list immediately.'),
    loadText: async () => String(row.content || ''),
    saveText: async (content) => {
      if (!String(content || '').trim()) {
        throw new Error(tx('Skill 内容不能为空', 'Skill content cannot be empty'));
      }
      await apiWrite(
        '/console/agents/' + encodeURIComponent(activeAgentId) + '/skills/' + encodeURIComponent(skill),
        'PUT',
        {content}
      );
    },
    onSaved: async () => {
      await reloadActiveAgentSkills();
      await loadAgents();
    },
  });
}

async function loadSkillEvolution() {
  const status = document.getElementById('sev-status').value;
  const q = document.getElementById('sev-q')?.value?.trim() || '';
  const sizeSel = Number(document.getElementById('sev-page-size')?.value || 20);
  _listState('skill_evolution', {size: sizeSel}).size = sizeSel;
  const tbody = document.getElementById('sev-tbody');
  tbody.innerHTML = `<tr><td colspan="5" style="color:var(--muted)">${tx('加载中…', 'Loading…')}</td></tr>`;
  let url = '/console/skill-evolution/proposals?limit=500';
  if (status) url += '&status=' + encodeURIComponent(status);
  try {
    const rows = await api(url);
    const filtered = _applyListQuery(rows || [], q, ['proposal_id', 'skill', 'status', 'reviewed_utc']);
    const pageRows = _paginate(filtered, 'skill_evolution', 'sev-pager', 'loadSkillEvolution');
    if (!pageRows.length) {
      tbody.innerHTML = `<tr><td colspan="5" style="color:var(--muted)">${tx('未找到提案', 'No proposals found')}</td></tr>`;
      return;
    }
    tbody.innerHTML = pageRows.map(p => {
      const pid = encodeURIComponent(p.proposal_id || '');
      return `<tr>
        <td style="color:var(--muted);font-size:11px">${esc(p.proposal_id || '')}</td>
        <td>${esc(p.skill || '')}</td>
        <td><span class="badge ${p.status === 'applied' ? 'ok' : p.status === 'rejected' || p.status === 'apply_failed' ? 'error' : 'degraded'}">${esc(p.status || '')}</span></td>
        <td style="color:var(--muted)">${fmtTime(p.reviewed_utc) || '—'}</td>
        <td>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#334155" onclick="viewSkillProposal('${pid}')">${tx('查看', 'View')}</button>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#14532d" onclick="reviewSkillProposal('${pid}','approve')">${tx('通过', 'Approve')}</button>
          <button class="action" style="font-size:11px;padding:3px 8px;background:#7f1d1d" onclick="reviewSkillProposal('${pid}','reject')">${tx('拒绝', 'Reject')}</button>
          <button class="action" style="font-size:11px;padding:3px 8px" onclick="applySkillProposal('${pid}')">${tx('应用', 'Apply')}</button>
        </td>
      </tr>`;
    }).join('');
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" style="color:var(--red)">${tx('错误：', 'Error: ')}${esc(e.message)}</td></tr>`;
  }
}

async function _findSkillProposal(proposalId) {
  const all = await api('/console/skill-evolution/proposals?limit=300');
  return all.find(p => String(p.proposal_id || '') === String(proposalId || '')) || null;
}

async function viewSkillProposal(pidKey) {
  const proposalId = decodeURIComponent(pidKey);
  const detail = document.getElementById('sev-detail');
  detail.textContent = tx('加载提案详情…', 'Loading proposal detail…');
  try {
    const row = await _findSkillProposal(proposalId);
    if (!row) {
      detail.textContent = tx('未找到提案。', 'Proposal not found.');
      return;
    }
    detail.textContent = JSON.stringify(row, null, 2);
  } catch (e) {
    detail.textContent = tx('错误：', 'Error: ') + e.message;
  }
}

async function reviewSkillProposal(pidKey, decision) {
  const proposalId = decodeURIComponent(pidKey);
  const note = prompt(tx(`${decision.toUpperCase()} 给 ${proposalId} 的备注：`, `${decision.toUpperCase()} note for ${proposalId}:`)) || '';
  try {
    await apiWrite(
      '/console/skill-evolution/proposals/' + encodeURIComponent(proposalId) + '/review',
      'POST',
      {decision, reviewer: 'console', note, apply: decision === 'approve'}
    );
    await loadSkillEvolution();
    await viewSkillProposal(encodeURIComponent(proposalId));
  } catch (e) {
    alert(tx('审核失败：', 'Review failed: ') + e.message);
  }
}

async function applySkillProposal(pidKey) {
  const proposalId = decodeURIComponent(pidKey);
  try {
    await apiWrite('/console/skill-evolution/proposals/' + encodeURIComponent(proposalId) + '/apply', 'POST', {});
    await loadSkillEvolution();
    await viewSkillProposal(encodeURIComponent(proposalId));
  } catch (e) {
    alert(tx('应用失败：', 'Apply failed: ') + e.message);
  }
}

