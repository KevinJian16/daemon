const RETINUE_ROLES = ['counsel', 'scout', 'sage', 'artificer', 'arbiter', 'scribe', 'envoy'];

registerPanel('agents', {
  _roles: [],
  async load() {
    const [agents, retinue] = await Promise.all([
      api('/console/agents'),
      api('/console/retinue').catch(() => null),
    ]);
    const allAgents = Array.isArray(agents) ? agents : [];
    const poolInstances = Array.isArray(retinue?.instances) ? retinue.instances : [];
    const byRole = {};
    for (const agent of allAgents) {
      const role = String(agent.id || '').split(/[_\-]/)[0] || 'other';
      if (!byRole[role]) byRole[role] = { role, total: 0, rep: agent.id, skills_count: 0, workspace_ready: true };
      byRole[role].total += 1;
      byRole[role].rep = byRole[role].rep || agent.id;
      byRole[role].skills_count = Math.max(byRole[role].skills_count, agent.skills_count || 0);
      byRole[role].workspace_ready = byRole[role].workspace_ready && agent.workspace_exists !== false;
    }
    const poolByRole = {};
    for (const inst of poolInstances) {
      const role = String(inst.id || '').split(/[_\-]/)[0] || 'other';
      if (!poolByRole[role]) poolByRole[role] = { occupied: 0, idle: 0 };
      if (String(inst.status || '') === 'occupied') poolByRole[role].occupied += 1;
      else poolByRole[role].idle += 1;
    }
    this._roles = RETINUE_ROLES.map(role => ({
      role,
      total: byRole[role]?.total || 0,
      rep: byRole[role]?.rep || role,
      skills_count: byRole[role]?.skills_count || 0,
      workspace_ready: byRole[role]?.workspace_ready !== false,
      occupied: poolByRole[role]?.occupied || 0,
      idle: poolByRole[role]?.idle || 0,
    }));
  },
  render() {
    return this._roles.map(row => `
      <div class="list-item" onclick="PANELS.agents.openDetail('${esc(row.role)}')">
        <div class="item-main">
          <div class="item-title">${esc(row.role)}</div>
          <div class="item-sub">${row.occupied > 0 ? `${row.occupied}/${row.total || 0} ${tx('占用', 'occupied')}` : `${row.total || 0} ${tx('空闲', 'idle')}`} \u00b7 ${row.skills_count || 0} ${tx('项技能', 'skills')}</div>
        </div>
        ${statusDot(row.workspace_ready ? (row.occupied > 0 ? 'blue' : 'green') : 'amber')}
      </div>
    `).join('');
  },
  async openDetail(role) {
    const row = this._roles.find(item => item.role === role);
    if (!row) return;
    pushDetail(role, '<div class="loading">\u2026</div>');
    try {
      const skills = await api('/console/agents/' + encodeURIComponent(row.rep) + '/skills');
      let html = '';
      html += fieldText(tx('角色', 'Role'), row.role);
      html += fieldText(tx('\u6c60\u5927\u5c0f', 'Pool Size'), String(row.total || 0));
      html += fieldText(tx('\u5360\u7528', 'Occupied'), String(row.occupied || 0));
      html += fieldText(tx('\u7a7a\u95f2', 'Idle'), String(row.idle || 0));
      html += field(tx('工位', 'Workspace'), row.workspace_ready ? tag(tx('\u5c31\u7eea', 'Ready'), 'ok') : tag(tx('\u7f3a\u5931', 'Missing'), 'warn'));
      html += actions(btn(tx('打开技能', 'Open Skills'), `PANELS.skills._roleFilter='${esc(row.role)}';showPanel('skills',true)`, 'ghost'));
      if (Array.isArray(skills) && skills.length) {
        html += `<div class="section-heading">${tx('技能', 'Skills')}</div>`;
        html += skills.map(skill => `
          <div class="sub-item">
            <div class="item-main">
              <div class="item-title">${esc(skill.title || skill.skill || '')}</div>
              <div class="item-sub">${esc(skill.skill || '')}</div>
            </div>
            <button class="btn ${skill.enabled ? 'danger' : 'success'}" style="padding:4px 10px;font-size:11px" onclick="_toggleSkillEnabled('${esc(row.rep)}','${esc(skill.skill || '')}',${skill.enabled ? 'true' : 'false'})">${skill.enabled ? tx('\u7981\u7528', 'Disable') : tx('\u542f\u7528', 'Enable')}</button>
          </div>
        `).join('');
      } else {
        html += `<div class="empty">${tx('这个角色还没有挂载技能。', 'No skills attached to this role yet.')}</div>`;
      }
      pushDetail(role, html);
    } catch (e) {
      pushDetail(role, `<div class="empty">${esc(e.message)}</div>`);
    }
  }
});

async function _toggleSkillEnabled(agent, skill, enabled) {
  const next = enabled !== 'true';
  const ok = await confirmAction(
    tx('切换技能', 'Toggle Skill'),
    tx(`${next ? '\u542f\u7528' : '\u7981\u7528'} ${agent} / ${skill}\uff1f`, `${next ? 'Enable' : 'Disable'} ${agent} / ${skill}?`)
  );
  if (!ok) return;
  try {
    await apiWrite('/console/agents/' + encodeURIComponent(agent) + '/skills/' + encodeURIComponent(skill) + '/enabled', 'PATCH', { enabled: next });
    refreshPanel('agents');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}
