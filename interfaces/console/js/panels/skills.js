registerPanel('skills', {
  _mode: 'library',
  _roleFilter: '',
  _skills: [],
  _proposals: [],
  async load() {
    const roleQuery = this._roleFilter ? '?role=' + encodeURIComponent(this._roleFilter) : '';
    const [skills, proposals] = await Promise.all([
      api('/console/skills' + roleQuery).catch(() => []),
      api('/console/skills/proposals?limit=200').catch(() => []),
    ]);
    this._skills = Array.isArray(skills) ? skills : [];
    this._proposals = Array.isArray(proposals) ? proposals : [];
  },
  render() {
    let html = `<div class="filter-bar">
      <select onchange="PANELS.skills._mode=this.value;refreshPanel('skills')">
        <option value="library"${this._mode === 'library' ? ' selected' : ''}>${tx('\u6280\u80fd\u5e93', 'Library')}</option>
        <option value="proposals"${this._mode === 'proposals' ? ' selected' : ''}>${tx('\u63d0\u6848', 'Proposals')}</option>
      </select>
      <select onchange="PANELS.skills._roleFilter=this.value;refreshPanel('skills')">
        <option value="">${tx('\u5168\u90e8 role', 'All roles')}</option>
        ${['counsel', 'scout', 'sage', 'artificer', 'arbiter', 'scribe', 'envoy'].map(role => `<option value="${role}"${this._roleFilter === role ? ' selected' : ''}>${role}</option>`).join('')}
      </select>
    </div>`;
    if (this._mode === 'proposals') {
      if (!this._proposals.length) return html + `<div class="empty">${tx('\u6682\u65e0\u5f85\u5ba1\u63d0\u6848', 'No proposals')}</div>`;
      html += this._proposals.map(row => `
        <div class="list-item" onclick="PANELS.skills.openDetail('proposal:${esc(row.proposal_id || '')}')">
          <div class="item-main">
            <div class="item-title">${esc(row.skill || row.proposal_id || '')}</div>
            <div class="item-sub">${esc(row.status || '')}${row.agent ? ' \u00b7 ' + esc(row.agent) : ''}</div>
          </div>
          ${statusDot(row.status === 'applied' ? 'green' : row.status === 'approved' ? 'blue' : row.status === 'rejected' || row.status === 'apply_failed' ? 'red' : 'amber')}
        </div>
      `).join('');
      return html;
    }
    if (!this._skills.length) return html + `<div class="empty">${tx('\u6682\u65e0 skills', 'No skills')}</div>`;
    html += this._skills.map(row => `
      <div class="list-item" onclick="PANELS.skills.openDetail('skill:${esc(row.role || '')}:${esc(row.skill || '')}')">
        <div class="item-main">
          <div class="item-title">${esc(row.title || row.skill || '')}</div>
          <div class="item-sub">${esc(row.role || '')} \u00b7 ${esc(row.skill || '')}</div>
        </div>
        ${statusDot(row.enabled ? 'green' : 'muted')}
      </div>
    `).join('');
    return html;
  },
  async openDetail(key) {
    if (String(key).startsWith('proposal:')) {
      const proposalId = String(key).split(':').slice(1).join(':');
      return this._renderProposal(proposalId);
    }
    const [, role, skill] = String(key).split(':');
    if (!role || !skill) return;
    pushDetail(skill, '<div class="loading">\u2026</div>');
    const row = await api('/console/skills/' + encodeURIComponent(role) + '/' + encodeURIComponent(skill));
    let html = '';
    html += fieldText('Role', row.role);
    html += fieldText('Skill', row.skill);
    html += field(tx('\u72b6\u6001', 'Status'), row.enabled ? tag(tx('\u542f\u7528', 'Enabled'), 'ok') : tag(tx('\u7981\u7528', 'Disabled'), 'dim'));
    html += fieldText(tx('\u66f4\u65b0', 'Updated'), fmtTime(row.updated_utc));
    html += `<div class="section-heading">${tx('\u5185\u5bb9', 'Content')}</div>`;
    html += `<textarea class="editor-textarea" id="skill-editor">${esc(row.content || '')}</textarea>`;
    html += actions(btn(tx('\u4fdd\u5b58', 'Save'), `_saveSkill('${esc(row.role || '')}','${esc(row.skill || '')}')`, 'success'));
    pushDetail(row.title || row.skill || skill, html);
  },
  _renderProposal(proposalId) {
    const row = this._proposals.find(item => String(item.proposal_id || '') === proposalId);
    if (!row) return;
    let html = '';
    html += fieldText('Proposal ID', row.proposal_id, { mono: true });
    html += fieldText('Skill', row.skill || '\u2014');
    html += field(tx('\u72b6\u6001', 'Status'), tag(row.status || '', row.status === 'applied' ? 'ok' : row.status === 'rejected' ? 'error' : 'warn'));
    if (row.agent) html += fieldText('Agent', row.agent);
    if (row.diff_summary) html += fieldText(tx('\u53d8\u66f4\u6458\u8981', 'Diff Summary'), row.diff_summary);
    if (row.review_note) html += fieldText(tx('\u5907\u6ce8', 'Note'), row.review_note);
    const buttons = [];
    if (row.status === 'pending') {
      buttons.push(btn(tx('\u901a\u8fc7', 'Approve'), `_reviewSkillProposal('${esc(proposalId)}','approve')`, 'success'));
      buttons.push(btn(tx('\u62d2\u7edd', 'Reject'), `_reviewSkillProposal('${esc(proposalId)}','reject')`, 'danger'));
    }
    if (row.status === 'approved') {
      buttons.push(btn(tx('\u5e94\u7528', 'Apply'), `_applySkillProposal('${esc(proposalId)}')`, 'primary'));
    }
    if (buttons.length) html += actions(...buttons);
    pushDetail(row.skill || proposalId, html);
  }
});

async function _saveSkill(role, skill) {
  const textarea = document.getElementById('skill-editor');
  if (!textarea) return;
  const content = textarea.value;
  const ok = await confirmAction(
    tx('\u4fdd\u5b58 Skill', 'Save Skill'),
    tx(`\u786e\u8ba4\u66f4\u65b0 ${role} / ${skill}\uff1f`, `Save ${role} / ${skill}?`)
  );
  if (!ok) return;
  try {
    await apiWrite('/console/skills/' + encodeURIComponent(role) + '/' + encodeURIComponent(skill), 'PUT', { content });
    refreshPanel('skills');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}

async function _reviewSkillProposal(proposalId, decision) {
  const ok = await confirmAction(
    tx('\u5ba1\u6838\u63d0\u6848', 'Review Proposal'),
    tx(`\u786e\u8ba4${decision === 'approve' ? '\u901a\u8fc7' : '\u62d2\u7edd'} ${proposalId}\uff1f`, `${decision} ${proposalId}?`)
  );
  if (!ok) return;
  try {
    await apiWrite('/console/skills/proposals/' + encodeURIComponent(proposalId) + '/review', 'POST', { decision, reviewer: 'console', apply: decision === 'approve' });
    refreshPanel('skills');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}

async function _applySkillProposal(proposalId) {
  const ok = await confirmAction(
    tx('\u5e94\u7528\u63d0\u6848', 'Apply Proposal'),
    tx(`\u786e\u8ba4\u5e94\u7528 ${proposalId}\uff1f`, `Apply ${proposalId}?`)
  );
  if (!ok) return;
  try {
    await apiWrite('/console/skills/proposals/' + encodeURIComponent(proposalId) + '/apply', 'POST', {});
    refreshPanel('skills');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}
