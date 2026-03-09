registerPanel('endeavors', {
  _data: [],
  async load() {
    this._data = await api('/endeavors?limit=500');
  },
  render() {
    if (!this._data || !this._data.length) return `<div class="empty">No Endeavors</div>`;
    return this._data.map(r => {
      const st = r.endeavor_status || '';
      const dotType = st === 'completed' ? 'green' : st === 'running' ? 'blue' : st === 'paused' ? 'amber' : st === 'cancelled' || st === 'failed' ? 'red' : 'muted';
      return `
        <div class="list-item" onclick="PANELS.endeavors.openDetail('${esc(r.endeavor_id || '')}')">
          <div class="item-main">
            <div class="item-title">${esc(r.endeavor_id || '')}</div>
            <div class="item-sub">${esc(r.endeavor_phase || '')} \u00b7 ${Number(r.current_passage_index || 0)}/${Number(r.total_passages || 0)}</div>
          </div>
          ${statusDot(dotType)}
        </div>
      `;
    }).join('');
  },
  async openDetail(endeavorId) {
    pushDetail(tx('\u52a0\u8f7d\u4e2d\u2026', 'Loading\u2026'), '<div class="loading">\u2026</div>');
    try {
      const r = await api('/endeavors/' + encodeURIComponent(endeavorId));
      const m = r.manifest || {};
      const st = m.endeavor_status || '';
      const ph = m.endeavor_phase || '';
      let html = '';
      html += fieldText('Endeavor ID', m.endeavor_id || endeavorId, { mono: true });
      if (m.deed_id) html += fieldText('Deed ID', m.deed_id, { mono: true });
      html += field(tx('\u72b6\u6001', 'Status'), tag(st, st === 'completed' ? 'ok' : st === 'running' ? 'info' : st === 'paused' ? 'warn' : 'error'));
      html += fieldText('Phase', ph);
      html += fieldText('Passage Progress', `${Number(m.current_passage_index || 0)} / ${Number(m.total_passages || 0)}`);
      if (m.updated_utc) html += fieldText(tx('\u66f4\u65b0\u65f6\u95f4', 'Updated'), fmtTime(m.updated_utc));

      // Passages
      const passages = m.passages || [];
      if (passages.length) {
        html += `<div class="section-heading">Passages</div>`;
        html += passages.map((p, i) => {
          const pst = p.status || (i < (m.current_passage_index || 0) ? 'done' : 'pending');
          return `
            <div class="sub-item">
              <div class="item-main">
                <div class="item-title">${esc(p.title || ('Passage ' + (i + 1)))}</div>
                <div class="item-sub">${esc(pst)}</div>
              </div>
              ${statusDot(pst === 'done' || pst === 'passed' ? 'green' : pst === 'failed' ? 'red' : 'muted')}
            </div>
          `;
        }).join('');
      }

      const btns = [];
      if (ph === 'phase0_waiting_confirmation') {
        btns.push(btn(tx('\u786e\u8ba4\u5f00\u59cb', 'Confirm Start'), `_confirmEndeavor('${esc(endeavorId)}')`, 'success'));
      }
      if (st === 'paused' || (ph.includes('waiting') && ph !== 'passage_waiting_feedback')) {
        btns.push(btn(tx('\u6062\u590d\u6267\u884c', 'Resume'), `_resumeEndeavor('${esc(endeavorId)}')`, 'primary'));
      }
      if (st === 'running' || st === 'paused') {
        btns.push(btn(tx('\u53d6\u6d88', 'Cancel'), `_cancelEndeavor('${esc(endeavorId)}')`, 'danger'));
      }
      if (btns.length) html += actions(...btns);

      pushDetail(m.endeavor_id || endeavorId, html);
    } catch (e) {
      pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
    }
  }
});

async function _confirmEndeavor(endeavorId) {
  const ok = await confirmAction(
    'Confirm Endeavor',
    tx(`\u786e\u8ba4 ${endeavorId} \u5e76\u5f00\u59cb\u6267\u884c\uff1f`, `Confirm ${endeavorId} and start execution?`)
  );
  if (!ok) return;
  try {
    await apiWrite('/endeavors/' + encodeURIComponent(endeavorId) + '/confirm', 'POST', {});
    refreshPanel('endeavors');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}

async function _resumeEndeavor(endeavorId) {
  const ok = await confirmAction(
    'Resume Endeavor',
    tx(`\u786e\u8ba4\u6062\u590d ${endeavorId}\uff1f`, `Resume ${endeavorId}?`)
  );
  if (!ok) return;
  try {
    await apiWrite('/endeavors/' + encodeURIComponent(endeavorId) + '/resume', 'POST', {});
    refreshPanel('endeavors');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}

async function _cancelEndeavor(endeavorId) {
  const ok = await confirmAction(
    'Cancel Endeavor',
    tx(`\u786e\u8ba4\u53d6\u6d88 ${endeavorId}\uff1f\u6b64\u64cd\u4f5c\u4e0d\u53ef\u9006\u3002`, `Cancel ${endeavorId}? This is irreversible.`)
  );
  if (!ok) return;
  try {
    await apiWrite('/endeavors/' + encodeURIComponent(endeavorId) + '/cancel', 'POST', {});
    refreshPanel('endeavors');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}
