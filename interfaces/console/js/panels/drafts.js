registerPanel('drafts', {
  _rows: [],
  _filters: { status: '', source: '' },
  async load() {
    this._rows = await api('/console/drafts?limit=400');
  },
  render() {
    const rows = this._filtered();
    const sources = Array.from(new Set((this._rows || []).map((row) => String(row.source || '')).filter(Boolean))).sort();
    let html = `<div class="filter-bar">
      <select onchange="PANELS.drafts._filters.status=this.value;refreshPanel('drafts')">
        <option value="">${tx('全部状态', 'All status')}</option>
        ${['open', 'refining', 'crystallized', 'superseded', 'abandoned'].map((value) => `<option value="${value}"${this._filters.status === value ? ' selected' : ''}>${esc(draftStatusLabel(value))}</option>`).join('')}
      </select>
      <select onchange="PANELS.drafts._filters.source=this.value;refreshPanel('drafts')">
        <option value="">${tx('全部来源', 'All sources')}</option>
        ${sources.map((value) => `<option value="${esc(value)}"${this._filters.source === value ? ' selected' : ''}>${esc(value)}</option>`).join('')}
      </select>
    </div>`;
    if (!rows.length) return html + `<div class="empty">${tx('暂无草稿。', 'No drafts yet.')}</div>`;
    html += rows.map((row) => renderSubItem(
      row.intent_snapshot || row.draft_id || '',
      [draftStatusLabel(row.status), row.source || 'manual', row.folio_id || ''].filter(Boolean).join(' · '),
      statusDot(row.status || 'muted'),
      `PANELS.drafts.openDetail('${esc(row.draft_id || '')}')`
    )).join('');
    return html;
  },
  _filtered() {
    return (this._rows || []).filter((row) => {
      if (this._filters.status && String(row.status || '') !== this._filters.status) return false;
      if (this._filters.source && String(row.source || '') !== this._filters.source) return false;
      return true;
    });
  },
  async openDetail(draftId) {
    if (!draftId) return;
    pushDetail(tx('草稿', 'Draft'), '<div class="loading">…</div>');
    const row = await api('/console/drafts/' + encodeURIComponent(draftId));
    const brief = row.candidate_brief || {};
    const design = row.candidate_design || {};
    const moves = Array.isArray(design.moves) ? design.moves : [];
    const timeline = moves.map((move, index) => ({
      label: String(move.instruction || move.message || move.title || `${tx('步骤', 'Step')} ${index + 1}`),
      state: 'pending',
      agent: String(move.agent || ''),
    }));
    let html = '';
    html += fieldText(tx('草稿 ID', 'Draft ID'), row.draft_id, { mono: true });
    html += field(tx('状态', 'Status'), tag(draftStatusLabel(row.status), toneForDraft(row.status)));
    html += fieldText(tx('来源', 'Source'), row.source || 'manual');
    html += fieldText(tx('所属卷', 'Folio'), row.folio_id || '—', { mono: true });
    html += fieldText(tx('创建', 'Created'), fmtTime(row.created_utc));
    html += fieldText(tx('更新', 'Updated'), fmtTime(row.updated_utc));
    html += fieldText(tx('意图快照', 'Intent Snapshot'), row.intent_snapshot || '—');
    html += fieldText(tx('候选简报', 'Candidate Brief'), [
      brief.objective || '',
      brief.dag_budget ? `${brief.dag_budget} ${tx('步上限', 'step budget')}` : '',
      brief.standing ? tx('常札', 'Standing') : '',
    ].filter(Boolean).join(' · ') || '—');
    if (row.seed_event && Object.keys(row.seed_event).length) {
      html += fieldText(tx('触发事件', 'Seed Event'), shortJsonSummary(row.seed_event));
    }
    html += sectionHeading(tx('候选结构', 'Candidate structure'));
    html += renderTimeline(timeline);
    pushDetail(row.intent_snapshot || row.draft_id || tx('草稿', 'Draft'), html);
  },
});
