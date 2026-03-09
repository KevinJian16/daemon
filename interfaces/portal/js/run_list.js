// ── Nav data ──────────────────────────────────────────────
let deeds=[], offerings=[];

function dotCls(s){
  const v = String(s || '').toLowerCase();
  if (v === 'pending_review' || v === 'awaiting_eval') return 'd-amber';
  if (['running','queued','paused','cancelling'].includes(v)) return 'd-blue';
  if (['completed','done','cancelled'].includes(v)) return 'd-green';
  return 'd-muted';
}
function sLabel(s){ return t('s_'+(s||'').replace('-','_')) || s; }
function parseUtcMs(input){
  if (!input) return NaN;
  const raw = String(input).trim();
  if (!raw) return NaN;
  let normalized = raw.includes('T') ? raw : raw.replace(' ', 'T');
  if (!/[zZ]$|[+\-]\d{2}:?\d{2}$/.test(normalized)) normalized += 'Z';
  const parsed = Date.parse(normalized);
  if (Number.isFinite(parsed)) return parsed;
  const fallback = Date.parse(raw);
  return Number.isFinite(fallback) ? fallback : NaN;
}
function relTime(u){
  const ms = parseUtcMs(u);
  if (!Number.isFinite(ms)) return '\u2014';
  let diff=(Date.now()-ms)/1000;
  if (!Number.isFinite(diff)) return '\u2014';
  if (diff < 0) diff = 0;
  if(diff<60) return '<1m';
  if(diff<3600) return Math.floor(diff/60)+'m';
  if(diff<86400) return Math.floor(diff/3600)+'h';
  return Math.floor(diff/86400)+'d';
}

function makeItem(deed_id, title, scale, deedStatus, time, onClick) {
  const el = document.createElement('div');
  el.className = 'nav-item'; el.dataset.id = deed_id;
  const isRunning = ['running','queued'].includes(String(deedStatus||'').toLowerCase());
  el.innerHTML = `<span class="n-dot ${dotCls(deedStatus)}${isRunning?' breathing':''}"></span>
    <span class="n-title">${esc(title||deed_id)}</span>
    ${scale?`<span class="n-scale">${esc(scale)}</span>`:''}
    <span class="n-time">${esc(relTime(time))}</span>`;
  el.onclick = onClick;
  return el;
}

async function renderNav() {
  let runningDeeds=[], awaitingDeeds=[], historyDeeds=[];
  try { runningDeeds = await api('/deeds?phase=running&limit=200'); } catch(e){ runningDeeds=[]; }
  try { awaitingDeeds = await api('/deeds?phase=awaiting_eval&limit=200'); } catch(e){ awaitingDeeds=[]; }
  try { historyDeeds = await api('/deeds?phase=history&limit=200'); } catch(e){ historyDeeds=[]; }
  deeds=[...runningDeeds,...awaitingDeeds,...historyDeeds];
  const pending = awaitingDeeds || [];
  const running = runningDeeds || [];

  // Pending
  const pb = document.getElementById('pending-badge');
  const pl = document.getElementById('pending-list');
  if(pending.length){
    pb.textContent=pending.length; pb.style.display='';
    pl.innerHTML='';
    pending.forEach(tk=>{
      const scale=tk.work_scale||(tk.plan&&tk.plan.work_scale)||'';
      const el=makeItem(tk.deed_id,tk.deed_title||tk.title||tk.deed_type||tk.deed_id,scale,'pending_review',tk.updated_utc||tk.created_utc,()=>openDeed(tk,el));
      pl.appendChild(el);
    });
  } else {
    pb.style.display='none';
    pl.innerHTML=`<div class="nav-empty">${t('none')}</div>`;
  }

  // Running
  const rl=document.getElementById('running-list');
  if(running.length){
    rl.innerHTML='';
    running.forEach(tk=>{
      const scale=tk.work_scale||(tk.plan&&tk.plan.work_scale)||'';
      const deedStatus=tk.deed_status||'';
      const el=makeItem(tk.deed_id,tk.deed_title||tk.title||tk.deed_type||tk.deed_id,scale,deedStatus,tk.updated_utc||tk.created_utc,()=>openDeed(tk,el));
      rl.appendChild(el);
    });
  } else {
    rl.innerHTML=`<div class="nav-empty">${t('none')}</div>`;
  }

  // History: §2.1 auto-clustering by Dominion (group_label)
  _renderHistoryClustered(historyDeeds);
  const hs=document.getElementById('history-search');
  if(hs) hs.placeholder=lang==='zh'?hs.dataset.phZh:hs.dataset.phEn;
}

// §2.1: "daemon 自动将相关 Deed 归组，用自然语言标签呈现"
let _historyDeeds = [];
function _renderHistoryClustered(items) {
  _historyDeeds = items || [];
  const container = document.getElementById('history-groups');
  container.innerHTML = '';
  if (!_historyDeeds.length) {
    container.innerHTML = `<div class="nav-empty" style="padding:6px 14px">${t('none')}</div>`;
    return;
  }

  // Group by group_label; "Independent" or empty = ungrouped
  const groups = {};
  const independent = [];
  _historyDeeds.forEach(d => {
    const label = (d.group_label || '').trim();
    if (!label || label === 'Independent') {
      independent.push(d);
    } else {
      if (!groups[label]) groups[label] = [];
      groups[label].push(d);
    }
  });

  // Render grouped items first (collapsible)
  Object.keys(groups).forEach(label => {
    const items = groups[label];
    const grp = document.createElement('div');
    grp.className = 'dominion-group';
    const key = 'd_dg_' + label;
    const collapsed = localStorage.getItem(key) === '1';
    if (collapsed) grp.classList.add('collapsed');

    const hdr = document.createElement('div');
    hdr.className = 'dominion-group-label';
    hdr.innerHTML = `<span class="dg-chevron">\u25BE</span><span class="dg-title">${esc(label)}</span><span class="dg-count">${items.length}</span>`;
    hdr.onclick = () => {
      const c = grp.classList.toggle('collapsed');
      localStorage.setItem(key, c ? '1' : '0');
    };
    grp.appendChild(hdr);

    const body = document.createElement('div');
    body.className = 'dominion-group-body';
    items.forEach(d => {
      const el = makeItem(d.deed_id, d.deed_title || d.title || d.deed_id, '', _deedStatus(d) || 'completed', d.updated_utc || d.created_utc, () => openDeed(d, el));
      body.appendChild(el);
    });
    grp.appendChild(body);
    container.appendChild(grp);
  });

  // Render independent items flat
  independent.forEach(d => {
    const el = makeItem(d.deed_id, d.deed_title || d.title || d.deed_id, '', _deedStatus(d) || 'completed', d.updated_utc || d.created_utc, () => openDeed(d, el));
    container.appendChild(el);
  });
}

// ── Open deed → chat view ────────────────────────────────
async function openDeed(deed, navEl) {
  clearActive();
  if (navEl) navEl.classList.add('active');

  // Load messages from backend
  let messages = [];
  try {
    messages = await api('/deeds/' + encodeURIComponent(deed.deed_id) + '/messages?limit=500');
  } catch (_) {}

  showDeedChat(deed, messages);
}

// ── WebSocket event handlers ─────────────────────────────

function onWsDeedMessage(p) {
  const deedId = p.deed_id || '';
  if (!deedId || deedId !== currentDeedId) return;
  addChatMsg(p.role || 'assistant', p.content || '', p.event || '');
}

function onWsDeedCompleted(p) {
  const deedId = String(p.deed_id || '').trim();
  if (!deedId || deedId !== currentDeedId || !currentDeedData) return;
  currentDeedData.deed_status = 'awaiting_eval';
  _setChatBadge('awaiting_eval');
  document.getElementById('btn-pause').style.display = 'none';
  document.getElementById('btn-redirect').style.display = 'none';
  document.getElementById('btn-cancel').style.display = 'none';
  document.getElementById('ch-controls').style.display = 'none';
  // T5: compact plan component
  const planLive = document.getElementById('deed-plan-live');
  if (planLive) planLive.classList.add('compacting');
  _loadOfferingPreview(currentDeedData);
  showFeedbackInline(deedId);
}

function onWsDeedFailed(p) {
  const deedId = String(p.deed_id || '').trim();
  if (!deedId || deedId !== currentDeedId || !currentDeedData) return;
  currentDeedData.deed_status = 'failed';
  _setChatBadge('failed');
  document.getElementById('btn-pause').style.display = 'none';
  document.getElementById('btn-redirect').style.display = 'none';
  document.getElementById('btn-cancel').style.display = 'none';
  document.getElementById('btn-retry').style.display = '';
  document.getElementById('ch-controls').style.display = '';
}

function onWsDeedProgress(p) {
  // Update plan component step states in-place (T4)
  const deedId = String(p.deed_id || '').trim();
  if (!deedId || deedId !== currentDeedId) return;
  const moveId = p.move_id || '';
  const moveStatus = p.status || '';
  if (!moveId) return;
  // Find step by data-step-id and update state
  const step = document.querySelector('.plan-step[data-step-id="' + CSS.escape(moveId) + '"]');
  if (step) {
    step.classList.remove('pending', 'active', 'done');
    if (moveStatus === 'completed' || moveStatus === 'done') step.classList.add('done');
    else if (moveStatus === 'running') step.classList.add('active');
    else step.classList.add('pending');
  }
  // Update progress bar
  const allSteps = document.querySelectorAll('.plan-step');
  const doneSteps = document.querySelectorAll('.plan-step.done');
  const fill = document.querySelector('.plan-pbar-fill');
  if (fill && allSteps.length) {
    fill.style.width = Math.round(doneSteps.length / allSteps.length * 100) + '%';
  }
}

function onWsPassageCompleted(p) {
  // Update passage states in plan component
  const deedId = String(p.deed_id || '').trim();
  if (!deedId || deedId !== currentDeedId) return;
  const pidx = p.passage_index;
  if (pidx == null) return;
  // Mark passage as done, next as current
  const segs = document.querySelectorAll('.passage-seg');
  const items = document.querySelectorAll('.passage-item');
  segs.forEach((seg, i) => {
    seg.classList.remove('pending', 'current', 'done');
    if (i <= pidx) seg.classList.add('done');
    else if (i === pidx + 1) seg.classList.add('current');
    else seg.classList.add('pending');
  });
  items.forEach((item, i) => {
    item.classList.remove('pending', 'current', 'done');
    if (i <= pidx) item.classList.add('done');
    else if (i === pidx + 1) item.classList.add('current');
    else item.classList.add('pending');
  });
  // Update header passage progress
  const pel = document.getElementById('ch-passage');
  if (pel) {
    pel.textContent = (pidx + 2) + '/' + segs.length;
  }
}

function onWsEvalExpiring(p) {
  const deedId = String(p.deed_id || '').trim();
  if (!deedId || deedId !== currentDeedId) return;
  addChatMsg('system', t('fbFollowUp'), 'eval_expiring');
}
