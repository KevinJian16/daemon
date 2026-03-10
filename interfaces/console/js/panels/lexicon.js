registerPanel('lexicon', {
  _meta: null,
  _entries: [],
  _filters: { q: '', category: '' },
  async load() {
    const payload = await api('/console/lexicon');
    this._meta = payload || {};
    this._entries = Array.isArray(payload?.entries) ? payload.entries : [];
  },
  render() {
    const rows = this._filtered();
    const categories = Array.from(new Set((this._entries || []).map((row) => String(row.category || '')).filter(Boolean))).sort();
    let html = `
      <div class="summary-card panel-note">
        <div class="item-title">${esc(cLang === 'zh' ? (this._meta?.title_zh || 'Daemon 术语词典') : (this._meta?.title_en || 'Daemon Lexicon'))}</div>
        <div class="item-sub">${esc(cLang === 'zh' ? (this._meta?.authority_zh || '') : (this._meta?.authority_en || ''))}</div>
        <div class="item-sub">${esc(cLang === 'zh' ? (this._meta?.display_policy_zh || '') : (this._meta?.display_policy_en || ''))}</div>
      </div>
      <div class="filter-bar">
        <input class="lexicon-search" placeholder="${esc(tx('搜索术语、中文名或定义', 'Search term, Chinese rendering, or definition'))}" value="${esc(this._filters.q)}" oninput="PANELS.lexicon._filters.q=this.value;refreshPanel('lexicon')">
        <select onchange="PANELS.lexicon._filters.category=this.value;refreshPanel('lexicon')">
          <option value="">${tx('全部分类', 'All categories')}</option>
          ${categories.map((value) => `<option value="${esc(value)}"${this._filters.category === value ? ' selected' : ''}>${esc(_lexiconCategoryLabel(value))}</option>`).join('')}
        </select>
      </div>
      <div class="item-sub lexicon-summary">${rows.length} / ${this._entries.length} ${tx('条术语', 'entries')}</div>
    `;
    if (!rows.length) return html + `<div class="empty">${tx('没有匹配的术语。', 'No matching terms.')}</div>`;
    html += rows.map((row) => `
      <div class="list-item" onclick="PANELS.lexicon.openDetail('${esc(row.term || '')}')">
        <div class="item-main">
          <div class="item-title">${esc(row.zh || row.term || '')}</div>
          <div class="item-sub">${esc(row.term || '')} · ${esc(_lexiconCategoryLabel(row.category))}</div>
        </div>
        ${tag(tx('正式术语', 'Canonical'), 'ok')}
      </div>
    `).join('');
    return html;
  },
  _filtered() {
    const query = String(this._filters.q || '').trim().toLowerCase();
    return (this._entries || []).filter((row) => {
      if (this._filters.category && String(row.category || '') !== this._filters.category) return false;
      if (!query) return true;
      const hay = [
        row.term,
        row.zh,
        row.definition_zh,
        row.definition_en,
        row.example_zh,
        row.example_en,
      ].map((value) => String(value || '').toLowerCase()).join('\n');
      return hay.includes(query);
    });
  },
  openDetail(term) {
    const row = (this._entries || []).find((entry) => String(entry.term || '') === String(term || ''));
    if (!row) return;
    let html = '';
    html += fieldText(tx('中文显示', 'Chinese Rendering'), row.zh || '—');
    html += fieldText(tx('英文术语', 'Canonical Term'), row.term || '—');
    html += fieldText(tx('分类', 'Category'), _lexiconCategoryLabel(row.category));
    html += field(tx('状态', 'State'), tag(tx('正式术语', 'Canonical'), 'ok'));
    html += fieldText(tx('中文定义', 'Chinese Definition'), row.definition_zh || '—');
    html += fieldText(tx('英文定义', 'English Definition'), row.definition_en || '—');
    if (row.example_zh || row.example_en) {
      html += fieldText(tx('示例', 'Example'), cLang === 'zh' ? (row.example_zh || row.example_en || '') : (row.example_en || row.example_zh || ''));
    }
    if (row.notes_zh || row.notes_en) {
      html += fieldText(tx('备注', 'Notes'), cLang === 'zh' ? (row.notes_zh || row.notes_en || '') : (row.notes_en || row.notes_zh || ''));
    }
    pushDetail(`${row.zh || row.term || ''}`, html);
  },
});

function _lexiconCategoryLabel(value) {
  const key = String(value || '');
  const map = {
    core: tx('核心对象', 'Core objects'),
    psyche: tx('心智', 'Psyche'),
    service: tx('意志与行为', 'Services'),
    retinue: tx('随从', 'Retinue'),
    spine: tx('脊柱', 'Spine'),
    routine: tx('例行', 'Routines'),
    world: tx('世界条件', 'World'),
    surface: tx('表面', 'Surfaces'),
    depth: tx('处理深度', 'Depth'),
    status: tx('状态词汇', 'Statuses'),
  };
  return map[key] || key;
}
