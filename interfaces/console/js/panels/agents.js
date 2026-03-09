// ── Agents panel: shows 7 ROLES, not 151 instances ──
const RETINUE_ROLES = ['counsel', 'scout', 'sage', 'artificer', 'arbiter', 'scribe', 'envoy'];

registerPanel('agents', {
  _roles: [],
  _retinue: null,
  async load() {
    const [agents, retinue] = await Promise.all([
      api('/console/agents'),
      api('/console/retinue').catch(() => null),
    ]);
    const allAgents = agents || [];
    this._retinue = retinue || {};
    const byRole = {};
    for (const a of allAgents) {
      const role = String(a.id || '').split(/[_\-]/)[0] || 'other';
      if (!byRole[role]) byRole[role] = { role, instances: [], rep: null, skills_count: 0 };
      byRole[role].instances.push(a);
      if (!byRole[role].rep) byRole[role].rep = a.id;
      if (a.skills_count > byRole[role].skills_count) {
        byRole[role].skills_count = a.skills_count;
        byRole[role].rep = a.id;
      }
    }
    // Build per-role pool stats from instances
    const poolInstances = this._retinue.instances || [];
    const poolByRole = {};
    for (const inst of poolInstances) {
      const role = String(inst.id || '').split(/[_\-]/)[0] || 'other';
      if (!poolByRole[role]) poolByRole[role] = { occupied: 0, idle: 0 };
      if (String(inst.status || '') === 'occupied') poolByRole[role].occupied++;
      else poolByRole[role].idle++;
    }
    this._roles = RETINUE_ROLES.map(r => {
      const group = byRole[r] || { role: r, instances: [], rep: r, skills_count: 0 };
      const pool = poolByRole[r] || {};
      return {
        role: r,
        total: group.instances.length,
        occupied: pool.occupied || 0,
        idle: pool.idle || group.instances.length,
        skills_count: group.skills_count,
        rep: group.rep || r,
        allReady: group.instances.every(a => a.workspace_exists),
      };
    });
  },
  render() {
    if (!this._roles.length) return `<div class="empty">No Agents</div>`;
    return this._roles.map(r => {
      const poolLabel = r.occupied > 0
        ? `${r.occupied}/${r.total} occupied`
        : `${r.total} idle`;
      return `
        <div class="list-item" onclick="PANELS.agents.openDetail('${esc(r.role)}')">
          <div class="item-main">
            <div class="item-title">${esc(r.role)}</div>
            <div class="item-sub">${poolLabel} \u00b7 ${r.skills_count} Skills</div>
          </div>
          ${statusDot(r.occupied > 0 ? 'blue' : r.allReady ? 'green' : 'amber')}
        </div>
      `;
    }).join('');
  },
  async openDetail(role) {
    const r = this._roles.find(x => x.role === role);
    if (!r) return;
    pushDetail(role, '<div class="loading">\u2026</div>');
    try {
      const skills = await api('/console/agents/' + encodeURIComponent(r.rep) + '/skills');
      const skillList = Array.isArray(skills) ? skills : [];
      let html = '';
      html += fieldText('Role', r.role);
      html += fieldText(tx('\u6c60\u5927\u5c0f', 'Pool Size'), String(r.total));
      html += fieldText(tx('\u5360\u7528', 'Occupied'), String(r.occupied));
      html += fieldText(tx('\u7a7a\u95f2', 'Idle'), String(r.idle));
      html += field('Workspace', r.allReady
        ? tag(tx('\u5168\u90e8\u5c31\u7eea', 'All Ready'), 'ok')
        : tag(tx('\u90e8\u5206\u7f3a\u5931', 'Some Missing'), 'error'));

      if (skillList.length) {
        html += `<div class="section-heading">Skills</div>`;
        html += skillList.map(s => {
          const enabled = !!s.enabled;
          return `
            <div class="sub-item">
              <div class="item-main">
                <div class="item-title">${esc(s.skill || '')}</div>
                <div class="item-sub">${enabled ? tag(tx('\u542f\u7528', 'enabled'), 'ok') : tag(tx('\u7981\u7528', 'disabled'), 'dim')}</div>
              </div>
              <button class="btn ${enabled ? 'danger' : 'success'}" style="padding:4px 10px;font-size:11px" onclick="_toggleSkill('${esc(r.rep)}','${esc(s.skill || '')}',${enabled},'${esc(role)}')">${enabled ? tx('\u7981\u7528', 'Disable') : tx('\u542f\u7528', 'Enable')}</button>
            </div>
          `;
        }).join('');
      } else {
        html += `<div class="empty">No Skills</div>`;
      }
      pushDetail(role, html);
    } catch (e) {
      pushDetail(role, `<div class="empty">${esc(e.message)}</div>`);
    }
  }
});

async function _toggleSkill(repAgent, skill, currentlyEnabled, role) {
  const action = currentlyEnabled ? tx('\u7981\u7528', 'Disable') : tx('\u542f\u7528', 'Enable');
  const ok = await confirmAction(
    'Toggle Skill',
    tx(`${action} ${role} / ${skill}\uff1f`, `${action} ${role} / ${skill}?`)
  );
  if (!ok) return;
  try {
    await apiWrite(
      '/console/agents/' + encodeURIComponent(repAgent) + '/skills/' + encodeURIComponent(skill) + '/enabled',
      'PATCH',
      { enabled: !currentlyEnabled }
    );
    refreshPanel('agents');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}

// ── Skill Evolution panel ──
registerPanel('evolution', {
  _data: [],
  _filter: '',
  async load() {
    let url = '/console/skill-evolution/proposals?limit=500';
    if (this._filter) url += '&status=' + encodeURIComponent(this._filter);
    this._data = await api(url);
  },
  render() {
    let html = `<div class="filter-bar">
      <select onchange="PANELS.evolution._filter=this.value;showPanel('evolution',true)">
        <option value="">${tx('\u5168\u90e8\u72b6\u6001', 'All status')}</option>
        ${['pending', 'approved', 'rejected', 'applied', 'apply_failed'].map(s =>
          `<option value="${s}"${this._filter === s ? ' selected' : ''}>${s}</option>`
        ).join('')}
      </select>
    </div>`;

    if (!this._data.length) {
      html += `<div class="empty">No Proposals</div>`;
      return html;
    }
    html += this._data.map(p => {
      const st = p.status || '';
      const dotType = st === 'applied' ? 'green' : st === 'approved' ? 'blue' : (st === 'rejected' || st === 'apply_failed') ? 'red' : 'amber';
      return `
        <div class="list-item" onclick="PANELS.evolution.openDetail('${esc(p.proposal_id || '')}')">
          <div class="item-main">
            <div class="item-title">${esc(p.skill || '')}</div>
            <div class="item-sub">${esc(st)} \u00b7 ${fmtTime(p.created_utc || p.reviewed_utc)}</div>
          </div>
          ${statusDot(dotType)}
        </div>
      `;
    }).join('');
    return html;
  },
  openDetail(proposalId) {
    const p = this._data.find(x => x.proposal_id === proposalId);
    if (!p) return;
    let html = '';
    html += fieldText('Proposal ID', p.proposal_id, { mono: true });
    html += fieldText('Skill', p.skill);
    html += field(tx('\u72b6\u6001', 'Status'), tag(p.status || '', p.status === 'applied' ? 'ok' : p.status === 'rejected' ? 'error' : 'warn'));
    if (p.agent) html += fieldText('Agent', p.agent);
    if (p.reviewed_utc) html += fieldText(tx('\u5ba1\u6838\u65f6\u95f4', 'Reviewed'), fmtTime(p.reviewed_utc));
    if (p.reviewer) html += fieldText(tx('\u5ba1\u6838\u4eba', 'Reviewer'), p.reviewer);
    if (p.note) html += fieldText(tx('\u5907\u6ce8', 'Note'), p.note);
    if (p.diff_summary) html += fieldText(tx('\u53d8\u66f4\u6458\u8981', 'Diff Summary'), p.diff_summary);

    const btns = [];
    if (p.status === 'pending') {
      btns.push(btn(tx('\u901a\u8fc7', 'Approve'), `_reviewProposal('${esc(proposalId)}','approve')`, 'success'));
      btns.push(btn(tx('\u62d2\u7edd', 'Reject'), `_reviewProposal('${esc(proposalId)}','reject')`, 'danger'));
    }
    if (p.status === 'approved') {
      btns.push(btn(tx('\u5e94\u7528', 'Apply'), `_applyProposal('${esc(proposalId)}')`, 'primary'));
    }
    if (btns.length) html += actions(...btns);
    pushDetail(p.skill || proposalId, html);
  }
});

async function _reviewProposal(proposalId, decision) {
  const ok = await confirmAction(
    tx('\u5ba1\u6838\u63d0\u6848', 'Review Proposal'),
    tx(`${decision === 'approve' ? '\u901a\u8fc7' : '\u62d2\u7edd'} ${proposalId}\uff1f`, `${decision} ${proposalId}?`)
  );
  if (!ok) return;
  try {
    await apiWrite(
      '/console/skill-evolution/proposals/' + encodeURIComponent(proposalId) + '/review',
      'POST',
      { decision, reviewer: 'console', note: '', apply: decision === 'approve' }
    );
    refreshPanel('evolution');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}

async function _applyProposal(proposalId) {
  const ok = await confirmAction(
    tx('\u5e94\u7528\u63d0\u6848', 'Apply Proposal'),
    tx(`\u786e\u8ba4\u5e94\u7528 ${proposalId}\uff1f`, `Apply ${proposalId}?`)
  );
  if (!ok) return;
  try {
    await apiWrite('/console/skill-evolution/proposals/' + encodeURIComponent(proposalId) + '/apply', 'POST', {});
    refreshPanel('evolution');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}
