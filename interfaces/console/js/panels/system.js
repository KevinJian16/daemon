registerPanel('system', {
  _storage: null,
  _report: null,
  _challenge: null,
  async load() {
    [this._storage, this._report] = await Promise.all([
      api('/console/system/storage').catch(() => null),
      api('/console/system/reset/last-report').catch(() => null),
    ]);
  },
  render() {
    let html = '';
    html += `<div class="list-item" onclick="PANELS.system.openDetail('storage')">
      <div class="item-main">
        <div class="item-title">${tx('\u6258\u7ba1 Drive \u5b58\u50a8', 'Managed Drive Storage')}</div>
        <div class="item-sub">${this._storage?.ready ? tag(tx('\u5c31\u7eea', 'Ready'), 'ok') : tag(tx('\u672a\u5c31\u7eea', 'Not ready'), 'error')}</div>
      </div>
    </div>`;
    html += `<div class="list-item" onclick="PANELS.system.openDetail('reset')">
      <div class="item-main">
        <div class="item-title">${tx('\u7cfb\u7edf\u91cd\u7f6e', 'System Reset')}</div>
        <div class="item-sub">${tx('challenge/confirm \u673a\u5236', 'Challenge/confirm mechanism')}</div>
      </div>
    </div>`;
    if (this._report && Object.keys(this._report).length) {
      html += `<div class="list-item" onclick="PANELS.system.openDetail('report')">
        <div class="item-main">
          <div class="item-title">${tx('\u6700\u8fd1\u91cd\u7f6e\u62a5\u544a', 'Last Reset Report')}</div>
          <div class="item-sub">${fmtTime(this._report.completed_utc || this._report.started_utc)}</div>
        </div>
      </div>`;
    }
    return html;
  },
  openDetail(key) {
    if (key === 'storage') return this._renderStorage();
    if (key === 'reset') return this._renderReset();
    if (key === 'report') return this._renderReport();
  },
  _renderStorage() {
    const s = this._storage || {};
    let html = '';
    html += field(tx('\u72b6\u6001', 'Status'), s.ready ? tag(tx('\u5c31\u7eea', 'Ready'), 'ok') : tag(esc(s.error || tx('\u672a\u5c31\u7eea', 'Not ready')), 'error'));
    html += fieldText(tx('\u4e2a\u4eba\u4e91\u76d8\u6839\u76ee\u5f55', 'My Drive Root'), s.my_drive_root, { mono: true });
    html += fieldText(tx('\u5f52\u6863\u6839\u76ee\u5f55', 'Vault Root'), s.vault_root, { mono: true });
    html += fieldText(tx('\u4ea7\u51fa\u6839\u76ee\u5f55', 'Offering Root'), s.offering_root, { mono: true });
    html += field(tx('\u76ee\u5f55\u540d', 'Directory Name'),
      `<input type="text" class="inline-input" id="sys-dir-name" value="${esc(s.daemon_dir_name || 'daemon')}" style="width:200px">`);
    html += actions(
      btn(tx('\u4fdd\u5b58', 'Save'), '_saveStorage()', 'success')
    );
    pushDetail(tx('\u6258\u7ba1\u5b58\u50a8', 'Managed Storage'), html);
  },
  _renderReset() {
    let html = '';
    html += field(tx('\u6a21\u5f0f', 'Mode'),
      `<select class="inline-select" id="sys-reset-mode"><option value="strict">strict</option><option value="light">light</option></select>`);
    html += field(tx('\u91cd\u7f6e\u540e\u91cd\u542f', 'Restart After Reset'),
      `<label style="display:flex;align-items:center;gap:6px"><input type="checkbox" id="sys-reset-restart"> ${tx('\u662f', 'Yes')}</label>`);
    if (PANELS.system._challenge) {
      html += fieldText(tx('\u6311\u6218\u7801', 'Challenge ID'), PANELS.system._challenge.challenge_id, { mono: true });
      html += fieldText(tx('\u786e\u8ba4\u7801', 'Confirm Code'), PANELS.system._challenge.confirm_code, { mono: true });
    }
    html += actions(
      btn(tx('\u751f\u6210\u6311\u6218\u7801', 'Issue Challenge'), '_issueChallenge()', 'primary'),
      PANELS.system._challenge ? btn(tx('\u786e\u8ba4\u91cd\u7f6e', 'Confirm Reset'), '_confirmReset()', 'danger') : ''
    );
    pushDetail(tx('\u7cfb\u7edf\u91cd\u7f6e', 'System Reset'), html);
  },
  _renderReport() {
    const r = this._report || {};
    let html = '';
    for (const [k, v] of Object.entries(r)) {
      html += fieldText(humanize(k), typeof v === 'object' ? JSON.stringify(v) : String(v));
    }
    if (!Object.keys(r).length) html = `<div class="empty">${tx('\u6682\u65e0\u62a5\u544a', 'No report')}</div>`;
    pushDetail(tx('\u91cd\u7f6e\u62a5\u544a', 'Reset Report'), html);
  }
});

async function _saveStorage() {
  const input = document.getElementById('sys-dir-name');
  const name = String(input?.value || '').trim();
  if (!name) return;
  const ok = await confirmAction(
    tx('\u4fdd\u5b58\u5b58\u50a8\u914d\u7f6e', 'Save Storage Config'),
    tx(`\u786e\u8ba4\u5c06\u76ee\u5f55\u540d\u4fee\u6539\u4e3a ${name}\uff1f`, `Set directory name to ${name}?`)
  );
  if (!ok) return;
  try {
    await apiWrite('/console/system/storage', 'PUT', { daemon_dir_name: name });
    refreshPanel('system');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}

async function _issueChallenge() {
  const mode = document.getElementById('sys-reset-mode')?.value || 'strict';
  const restart = !!document.getElementById('sys-reset-restart')?.checked;
  try {
    PANELS.system._challenge = await apiWrite('/console/system/reset/challenge', 'POST', { mode, restart, ttl_seconds: 180 });
    PANELS.system.openDetail('reset');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}

async function _confirmReset() {
  if (!PANELS.system._challenge) return;
  const ok = await confirmAction(
    tx('\u7cfb\u7edf\u91cd\u7f6e', 'System Reset'),
    tx('\u786e\u8ba4\u7acb\u5373\u6267\u884c\u7cfb\u7edf\u91cd\u7f6e\uff1f\u8fd9\u4f1a\u505c\u6b62\u670d\u52a1\u5e76\u6e05\u7406\u8fd0\u884c\u6001\u3002', 'Confirm system reset? This will stop services and clean runtime state.')
  );
  if (!ok) return;
  const mode = document.getElementById('sys-reset-mode')?.value || PANELS.system._challenge.mode || 'strict';
  const restart = !!document.getElementById('sys-reset-restart')?.checked;
  try {
    await apiWrite('/console/system/reset/confirm', 'POST', {
      challenge_id: PANELS.system._challenge.challenge_id,
      confirm_code: PANELS.system._challenge.confirm_code,
      mode,
      restart,
    });
    PANELS.system._challenge = null;
    refreshPanel('system');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}
