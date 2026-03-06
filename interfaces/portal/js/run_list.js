// ── Nav data ──────────────────────────────────────────────
let runs=[], outcomes=[];
let curRunId=null;

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
  if (!Number.isFinite(ms)) return '—';
  let diff=(Date.now()-ms)/1000;
  if (!Number.isFinite(diff)) return '—';
  if (diff < 0) diff = 0;
  if(diff<60) return '<1m';
  if(diff<3600) return Math.floor(diff/60)+'m';
  if(diff<86400) return Math.floor(diff/3600)+'h';
  return Math.floor(diff/86400)+'d';
}

function makeItem(run_id, title, scale, runStatus, time, onClick) {
  const el = document.createElement('div');
  el.className = 'nav-item'; el.dataset.id = run_id;
  el.innerHTML = `<span class="n-dot ${dotCls(runStatus)}"></span>
    <span class="n-title">${esc(title||run_id)}</span>
    ${scale?`<span class="n-scale">${esc(scale)}</span>`:''}
    <span class="n-time">${esc(relTime(time))}</span>`;
  el.onclick = onClick;
  return el;
}

async function renderNav() {
  let runningRuns=[], awaitingRuns=[], historyRuns=[];
  try { runningRuns = await api('/runs?phase=running&limit=200'); } catch(e){ runningRuns=[]; }
  try { awaitingRuns = await api('/runs?phase=awaiting_eval&limit=200'); } catch(e){ awaitingRuns=[]; }
  try { historyRuns = await api('/runs?phase=history&limit=200'); } catch(e){ historyRuns=[]; }
  runs=[...runningRuns,...awaitingRuns,...historyRuns];
  try { outcomes = await api('/outcome?limit=200'); } catch(e){ outcomes=[]; }
  const pending = awaitingRuns || [];
  const running = runningRuns || [];
  const histOut = outcomes || [];
  let circuits = [];
  try { circuits = await api('/circuits'); } catch(e) { circuits = []; }

  // Pending
  const pb = document.getElementById('pending-badge');
  const pl = document.getElementById('pending-list');
  if(pending.length){
    pb.textContent=pending.length; pb.style.display='';
    pl.innerHTML='';
    pending.forEach(tk=>{
      const scale=tk.work_scale||(tk.plan&&tk.plan.work_scale)||'';
      const el=makeItem(tk.run_id,tk.run_title||tk.title||tk.run_type||tk.run_id,scale,'pending_review',tk.updated_utc||tk.created_utc,()=>openRun(tk,el));
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
      const runStatus=tk.run_status||'';
      const el=makeItem(tk.run_id,tk.run_title||tk.title||tk.run_type||tk.run_id,scale,runStatus,tk.updated_utc||tk.created_utc,()=>openRun(tk,el));
      rl.appendChild(el);
    });
  } else {
    rl.innerHTML=`<div class="nav-empty">${t('none')}</div>`;
  }

  // History
  histAllOutcomes=histOut;
  renderHistoryGrouped(histOut);
  // Update search placeholder for current lang
  const hs=document.getElementById('history-search');
  if(hs) hs.placeholder=lang==='zh'?hs.dataset.phZh:hs.dataset.phEn;

  // Circuits
  const cl = document.getElementById('circuit-list');
  if (cl) {
    if (circuits.length) {
      cl.innerHTML = '';
      circuits.forEach((c) => {
        const cid = String(c.circuit_id || '');
        const scale = String(c.status || '');
        const title = c.run_title || c.name || cid;
        const el = makeItem(
          cid,
          title,
          'circuit',
          String(c.status || 'active'),
          c.last_triggered_utc || c.created_utc || '',
          () => {
            clearActive();
            el.classList.add('active');
            showCircuits(cid);
          },
        );
        el.dataset.kind = 'circuit';
        if (currentCircuitId && currentCircuitId === cid) {
          el.classList.add('active');
        }
        cl.appendChild(el);
      });
    } else {
      cl.innerHTML = `<div class="nav-empty">${t('none')}</div>`;
    }
  }

  if (document.getElementById('view-circuits')?.style.display === 'flex') {
    renderCircuitsPage();
  }
}

// ── Open run ─────────────────────────────────────────────
async function openRun(run, navEl) {
  clearActive(); if(navEl) navEl.classList.add('active');
  curRunId=run.run_id;
  const runStatus = run.run_status || '';
  const workScale = run.work_scale || (run.plan && run.plan.work_scale) || '';
  const campaignId = run.campaign_id || (run.plan && run.plan.campaign_id) || run.run_id;
  document.getElementById('det-title').textContent = run.run_title||run.title||run.run_type||run.run_id;
  setBadge(runStatus);
  const sc=document.getElementById('det-scale');
  if(workScale){sc.textContent=workScale;sc.style.display='';}else sc.style.display='none';
  document.getElementById('det-time').textContent = relTime(run.created_utc);

  const runStatusLower = String(runStatus || '').toLowerCase();
  const isRunning=['running','queued','cancelling'].includes(runStatusLower);
  const isPaused = runStatusLower === 'paused';
  const ctrl=document.getElementById('det-controls');
  if(isRunning || isPaused){
    ctrl.classList.remove('hidden');
    const isCampaign = String(workScale || '').toLowerCase() === 'campaign';
    document.getElementById('btn-resume').style.display = isPaused && !isCampaign ? '' : 'none';
    document.getElementById('btn-pause').style.display = isRunning && !isCampaign ? '' : 'none';
    document.getElementById('btn-redirect').style.display = isRunning && !isCampaign ? '' : 'none';
    document.getElementById('btn-cancel').style.display = '';
  } else ctrl.classList.add('hidden');

  const pw=document.getElementById('prog-wrap');
  if(isRunning){
    pw.style.display='block';
    const pct=run.progress_pct||(run.step_index&&run.total_steps?Math.round(run.step_index/run.total_steps*100):0);
    document.getElementById('prog-fill').style.width=pct+'%';
    document.getElementById('prog-label').textContent=run.current_step||'';
  } else if (isPaused) {
    pw.style.display='block';
    document.getElementById('prog-fill').style.width='100%';
    document.getElementById('prog-label').textContent=lang==='zh'?'已暂停':'Paused';
  } else pw.style.display='none';

  document.getElementById('output-body').innerHTML='<p style="color:var(--muted);font-size:13px">Loading…</p>';
  document.getElementById('ms-timeline').style.display='none';
  document.getElementById('rating-wrap').style.display='none';
  showDetail();

  if(workScale==='campaign'){
    try{ const c=await api('/campaigns/'+encodeURIComponent(campaignId)); renderCampaign(c); }catch(e){ document.getElementById('output-body').innerHTML=''; }
    return;
  }
  const match=outcomes.find(o=>o.run_id===run.run_id);
  if(match) await renderOutcomeContent(match);
  else if(isRunning || isPaused) document.getElementById('output-body').innerHTML=`<p style="color:var(--muted);font-size:13px">${esc(run.current_step|| (isPaused ? (lang==='zh'?'Run 已暂停':'Run paused') : 'Run is active…'))}</p>`;
  else document.getElementById('output-body').innerHTML=`<p style="color:var(--muted);font-size:13px">No output yet.</p>`;
}

async function openOutcome(outcome, navEl) {
  clearActive(); if(navEl) navEl.classList.add('active');
  curRunId=outcome.run_id;
  document.getElementById('det-title').textContent=outcome.title||outcome.run_id;
  setBadge('completed');
  const sc=document.getElementById('det-scale');
  if(outcome.run_type){sc.textContent=outcome.run_type;sc.style.display='';}else sc.style.display='none';
  document.getElementById('det-time').textContent=relTime(outcome.delivered_utc);
  document.getElementById('det-controls').classList.add('hidden');
  document.getElementById('prog-wrap').style.display='none';
  document.getElementById('ms-timeline').style.display='none';
  showDetail();
  await renderOutcomeContent(outcome);
}

async function renderOutcomeContent(outcome) {
  const body=document.getElementById('output-body');
  body.innerHTML='<p style="color:var(--muted);font-size:13px">Loading…</p>';
  const path=(outcome.path||'').replace(/^\/|\/+$/g,'');
  try {
    const hr=await fetch(API+'/outcome/'+path+'/report.html');
    if(hr.ok){
      body.innerHTML='';
      const fr=document.createElement('iframe');
      fr.style.cssText='width:100%;min-height:480px;border:1px solid var(--border);border-radius:var(--r);display:block;background:white';
      fr.srcdoc=await hr.text();
      body.appendChild(fr);
      await showRating(outcome.run_id); return;
    }
    const mr=await fetch(API+'/outcome/'+path+'/report.md');
    if(mr.ok){ body.innerHTML=md(await mr.text()); await showRating(outcome.run_id); return; }
    const mfr=await fetch(API+'/outcome/'+path+'/manifest.json');
    if(mfr.ok){
      const mf=await mfr.json();
      if(!curRunId&&mf.run_id) curRunId=mf.run_id;
      body.innerHTML=`<pre>${esc(JSON.stringify(mf,null,2))}</pre>`;
      await showRating(curRunId); return;
    }
    body.innerHTML='<p style="color:var(--muted)">No preview available.</p>';
  } catch(e){ body.innerHTML=`<p style="color:var(--red)">Error: ${esc(e.message)}</p>`; }
}

function renderCampaign(c) {
  const data = (c && c.manifest) ? c.manifest : (c || {});
  const ms=data.milestones||[];
  if(ms.length){
    const tl=document.getElementById('ms-timeline');
    const ml=document.getElementById('ms-list');
    ml.innerHTML='';
    ms.forEach((m,i)=>{
      const milestoneStatus = m.milestone_status || '';
      const cls=
        milestoneStatus==='passed' || milestoneStatus==='skipped' ? 'done' :
        milestoneStatus==='running' ? 'active' :
        milestoneStatus==='failed' ? 'needs-review' : '';
      const row=document.createElement('div'); row.className='ms-row';
      row.innerHTML=`<div class="ms-num ${cls}">${i+1}</div>
        <div><div class="ms-name">${esc(m.title||m.name||('Milestone '+(i+1)))}</div>
        <div class="ms-sub">${esc(milestoneStatus)}${m.completed_utc?' · '+relTime(m.completed_utc):''}</div></div>`;
      ml.appendChild(row);
    });
    tl.style.display='block';
  }
  document.getElementById('output-body').innerHTML=data.summary?md(data.summary):`<pre>${esc(JSON.stringify(data,null,2))}</pre>`;
}

function setBadge(s) {
  const b=document.getElementById('det-status');
  b.textContent=sLabel(s);
  b.className='sbadge s-'+s;
}
