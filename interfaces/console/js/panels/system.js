async function loadSystemResetPanel() {
  await loadSystemStorage();
  await loadSystemResetReport();
  const state = document.getElementById('system-reset-state');
  if (!state) return;
  if (!resetChallenge) {
    state.textContent = tx('尚未生成重置挑战码。', 'No reset challenge issued.');
    return;
  }
  state.textContent = JSON.stringify(resetChallenge, null, 2);
}

async function issueResetChallenge() {
  const mode = document.getElementById('reset-mode')?.value || 'strict';
  const restart = !!document.getElementById('reset-restart')?.checked;
  try {
    const data = await apiWrite('/console/system/reset/challenge', 'POST', {
      mode,
      restart,
      ttl_seconds: 180,
    });
    resetChallenge = data;
    await loadSystemResetPanel();
  } catch (e) {
    alert(tx('生成挑战码失败：', 'Issue challenge failed: ') + e.message);
  }
}

async function confirmSystemReset() {
  if (!resetChallenge || !resetChallenge.challenge_id || !resetChallenge.confirm_code) {
    alert(tx('请先生成挑战码。', 'Issue challenge first.'));
    return;
  }
  if (!confirm(tx('确认立即执行系统重置吗？这会停止服务并清理运行态。', 'Confirm system reset now? This will stop services and clean runtime state.'))) return;
  const mode = document.getElementById('reset-mode')?.value || resetChallenge.mode || 'strict';
  const restart = !!document.getElementById('reset-restart')?.checked;
  try {
    const data = await apiWrite('/console/system/reset/confirm', 'POST', {
      challenge_id: resetChallenge.challenge_id,
      confirm_code: resetChallenge.confirm_code,
      mode,
      restart,
    });
    const state = document.getElementById('system-reset-state');
    if (state) state.textContent = JSON.stringify(data, null, 2);
    resetChallenge = null;
    alert(tx('重置请求已接收。几秒后刷新报告查看结果。', 'Reset accepted. Refresh report in a few seconds.'));
  } catch (e) {
    alert(tx('确认重置失败：', 'Confirm reset failed: ') + e.message);
  }
}

async function loadSystemResetReport() {
  const target = document.getElementById('system-reset-report');
  if (!target) return;
  target.textContent = tx('加载重置报告…', 'Loading reset report…');
  try {
    const data = await api('/console/system/reset/last-report');
    target.textContent = data && Object.keys(data).length ? JSON.stringify(data, null, 2) : tx('暂无报告。', 'No report.');
  } catch (e) {
    target.textContent = tx('错误：', 'Error: ') + e.message;
  }
}

function renderStorageStatus(data) {
  const body = document.getElementById('storage-status-body');
  if (!body) return;
  const rows = [
    ['Status', data.ready ? '<span style="color:#4ade80">✓ ready</span>' : `<span style="color:#f87171">✗ ${esc(data.error||'not ready')}</span>`],
    ['my_drive_root', esc(data.my_drive_root || '—')],
    ['archive_root', esc(data.archive_root || '—')],
    ['outcome_root', esc(data.outcome_root || '—')],
  ];
  body.innerHTML = rows.map(([k, v]) =>
    `<tr><td style="color:var(--muted);padding:4px 0;padding-right:16px;white-space:nowrap">${k}</td><td style="word-break:break-all;padding:4px 0">${v}</td></tr>`
  ).join('');
}

async function loadSystemStorage() {
  const body = document.getElementById('storage-status-body');
  const input = document.getElementById('storage-daemon-dir-name');
  if (body) body.innerHTML = `<tr><td colspan="2" style="color:var(--muted);padding:6px 0">${tx('加载中…','Loading…')}</td></tr>`;
  try {
    const data = await api('/console/system/storage');
    if (input) input.value = String(data.daemon_dir_name || 'daemon');
    renderStorageStatus(data);
  } catch (e) {
    if (body) body.innerHTML = `<tr><td colspan="2" style="color:#f87171;padding:6px 0">${tx('错误：','Error: ')}${esc(e.message)}</td></tr>`;
  }
}

async function saveSystemStorage() {
  const input = document.getElementById('storage-daemon-dir-name');
  const daemonDirName = String(input?.value || '').trim();
  if (!daemonDirName) {
    alert(tx('daemon_dir_name 不能为空。', 'daemon_dir_name is required.'));
    return;
  }
  try {
    const data = await apiWrite('/console/system/storage', 'PUT', {daemon_dir_name: daemonDirName});
    if (input) input.value = String(data.daemon_dir_name || daemonDirName);
    renderStorageStatus(data);
  } catch (e) {
    alert(tx('保存存储设置失败：', 'Save storage settings failed: ') + e.message);
  }
}

function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
