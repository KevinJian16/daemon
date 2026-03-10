registerPanel('system', {
  _storage: null,
  _report: null,
  _challenge: null,
  async load() {
    const [storage, report] = await Promise.all([
      api('/console/system/storage').catch(() => null),
      api('/console/system/reset/last-report').catch(() => null),
    ]);
    this._storage = storage || {};
    this._report = report || {};
  },
  render() {
    let html = '';
    html += `<div class="list-item" onclick="PANELS.system.openDetail('storage')">
      <div class="item-main">
        <div class="item-title">${tx('\u5b58\u50a8\u7ed1\u5b9a', 'Storage Bindings')}</div>
        <div class="item-sub">${this._storage?.ready ? tag(tx('\u5c31\u7eea', 'Ready'), 'ok') : tag(tx('\u672a\u5c31\u7eea', 'Not ready'), 'warn')}</div>
      </div>
    </div>`;
    html += `<div class="list-item" onclick="PANELS.system.openDetail('reset')">
      <div class="item-main">
        <div class="item-title">${tx('\u7cfb\u7edf\u91cd\u7f6e', 'System Reset')}</div>
        <div class="item-sub">${tx('\u53cc\u91cd\u786e\u8ba4\u673a\u5236', 'Challenge and confirm flow')}</div>
      </div>
    </div>`;
    if (this._report && Object.keys(this._report).length) {
      html += `<div class="list-item" onclick="PANELS.system.openDetail('report')">
        <div class="item-main">
          <div class="item-title">${tx('\u6700\u8fd1\u91cd\u7f6e', 'Last Reset')}</div>
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
    const row = this._storage || {};
    let html = '';
    html += field(tx('\u72b6\u6001', 'Status'), row.ready ? tag(tx('\u5c31\u7eea', 'Ready'), 'ok') : tag(tx('\u672a\u5c31\u7eea', 'Not ready'), 'warn'));
    html += field(tx('宝库路径', 'Vault Path'), _storagePathField('vault', row.vault_root || ''));
    html += field(tx('献作路径', 'Offering Path'), _storagePathField('offering', row.offering_root || ''));
    html += `<div class="field-note">${tx('\u76f4\u63a5\u586b\u5199\u672c\u5730\u7edd\u5bf9\u8def\u5f84\u3002Console \u4e0d\u518d\u901a\u8fc7\u76ee\u5f55\u540d\u63a8\u5bfc\u5b58\u50a8\u4f4d\u7f6e\u3002', 'Paste absolute local paths directly. Console no longer derives storage from a directory nickname.')}</div>`;
    html += actions(btn(tx('\u4fdd\u5b58', 'Save'), '_saveStoragePaths()', 'success'));
    pushDetail(tx('\u5b58\u50a8\u7ed1\u5b9a', 'Storage Bindings'), html);
  },
  _renderReset() {
    let html = '';
    html += field(tx('\u6a21\u5f0f', 'Mode'), `<select class="inline-select" id="sys-reset-mode"><option value="strict">strict</option><option value="light">light</option></select>`);
    html += field(tx('\u91cd\u7f6e\u540e\u91cd\u542f', 'Restart After Reset'), `<label style="display:flex;align-items:center;gap:6px"><input type="checkbox" id="sys-reset-restart"> ${tx('\u662f', 'Yes')}</label>`);
    if (PANELS.system._challenge) {
      html += fieldText(tx('\u6311\u6218\u7801', 'Challenge ID'), PANELS.system._challenge.challenge_id, { mono: true });
      html += fieldText(tx('\u786e\u8ba4\u7801', 'Confirm Code'), PANELS.system._challenge.confirm_code, { mono: true });
    }
    html += actions(
      btn(tx('\u751f\u6210\u6311\u6218', 'Issue Challenge'), '_issueChallenge()', 'primary'),
      PANELS.system._challenge ? btn(tx('\u786e\u8ba4\u91cd\u7f6e', 'Confirm Reset'), '_confirmReset()', 'danger') : ''
    );
    pushDetail(tx('\u7cfb\u7edf\u91cd\u7f6e', 'System Reset'), html);
  },
  _renderReport() {
    const report = this._report || {};
    let html = '';
    html += fieldText(tx('\u5f00\u59cb', 'Started'), fmtTime(report.started_utc));
    html += fieldText(tx('\u5b8c\u6210', 'Completed'), fmtTime(report.completed_utc));
    html += fieldText(tx('\u6a21\u5f0f', 'Mode'), report.mode || '\u2014');
    html += fieldText(tx('\u91cd\u542f', 'Restart'), report.restart ? tx('\u662f', 'Yes') : tx('\u5426', 'No'));
    html += fieldText(tx('\u6e05\u7406\u7ec4\u4ef6', 'Cleared Areas'), _summarizeReportValue(report.cleaned_paths || report.cleaned || []));
    html += fieldText(tx('\u5907\u4efd', 'Backups'), _summarizeReportValue(report.backups || []));
    html += fieldText(tx('\u5907\u6ce8', 'Notes'), _summarizeReportValue(report.notes || report.summary || ''));
    pushDetail(tx('\u6700\u8fd1\u91cd\u7f6e', 'Last Reset'), html);
  }
});

function _summarizeReportValue(value) {
  if (Array.isArray(value)) {
    if (!value.length) return '\u2014';
    return value.slice(0, 4).map(item => String(item)).join(' \u00b7 ') + (value.length > 4 ? ` (+${value.length - 4})` : '');
  }
  if (value && typeof value === 'object') {
    const keys = Object.keys(value);
    return keys.length ? keys.slice(0, 4).join(' \u00b7 ') + (keys.length > 4 ? ` (+${keys.length - 4})` : '') : '\u2014';
  }
  return String(value || '\u2014');
}

function _storagePathField(kind, value) {
  return `<div class="storage-path-row">
    <input class="inline-input path-input" id="storage-${kind}" value="${esc(value || '')}">
    <button class="btn btn-ghost btn-sm" onclick="_triggerStoragePicker('${kind}')">${tx('\u9009\u62e9…', 'Choose…')}</button>
    <input type="file" id="storage-${kind}-picker" webkitdirectory directory multiple style="display:none" onchange="_handleStoragePicked('${kind}', this)">
  </div>`;
}

async function _saveStoragePaths() {
  const vaultInput = document.getElementById('storage-vault');
  const offeringInput = document.getElementById('storage-offering');
  const vault_root = String(vaultInput?.value || '').trim();
  const offering_root = String(offeringInput?.value || '').trim();
  if (!vault_root || !offering_root) return;
  const ok = await confirmAction(
    tx('\u4fdd\u5b58\u5b58\u50a8\u914d\u7f6e', 'Save Storage Paths'),
    tx('\u786e\u8ba4\u66f4\u65b0\u5b9d\u5e93\u548c\u732e\u4f5c\u7684\u5b58\u50a8\u8def\u5f84\uff1f', 'Save the Vault and Offering paths?')
  );
  if (!ok) return;
  try {
    await apiWrite('/console/system/storage', 'PUT', { vault_root, offering_root });
    refreshPanel('system');
  } catch (e) {
    pushDetail(tx('\u9519\u8bef', 'Error'), `<div class="empty">${esc(e.message)}</div>`);
  }
}

function _triggerStoragePicker(kind) {
  const picker = document.getElementById('storage-' + kind + '-picker');
  if (picker) picker.click();
}

function _handleStoragePicked(kind, input) {
  const target = document.getElementById('storage-' + kind);
  const file = input?.files?.[0];
  if (!target || !file) return;
  const nativePath = file.path || '';
  const relativePath = file.webkitRelativePath || '';
  if (nativePath && relativePath && nativePath.endsWith(relativePath)) {
    target.value = nativePath.slice(0, nativePath.length - relativePath.length).replace(/[\\/]+$/, '');
  } else if (nativePath) {
    target.value = nativePath;
  } else {
    target.placeholder = tx('\u8bf7\u7c98\u8d34\u7edd\u5bf9\u8def\u5f84', 'Paste the absolute path');
    target.focus();
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
    tx('\u786e\u8ba4\u7acb\u5373\u6267\u884c\u7cfb\u7edf\u91cd\u7f6e\uff1f', 'Confirm the reset now?')
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
