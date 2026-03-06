// ── Nav data ──────────────────────────────────────────────
let runs=[], outcomes=[];
let curRunId=null;

function dotCls(s){ return s==='pending_review'?'d-amber':s==='running'?'d-blue':s==='completed'||s==='done'?'d-green':'d-muted'; }
function sLabel(s){ return t('s_'+(s||'').replace('-','_')) || s; }
function relTime(u){
  if(!u) return '';
  const diff=(Date.now()-new Date(u.replace(' ','T').replace(/(?<!\+\d{2})$/,'Z')))/1000;
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
  try { runs = await api('/runs?limit=200'); } catch(e){ runs=[]; }
  try { outcomes = await api('/outcome?limit=200'); } catch(e){ outcomes=[]; }
  let pendFb = [];
  try { pendFb = await api('/feedback/pending?limit=50'); } catch(e){}
  const fbIds = new Set((pendFb||[]).map(x=>x.run_id));

  const pending = runs.filter(t=>{
    const runStatus = t.run_status || '';
    return fbIds.has(t.run_id) || runStatus === 'pending_review';
  });
  const pendIds = new Set(pending.map(t=>t.run_id));
  const running = runs.filter(t=>{
    const runStatus = t.run_status || '';
    return ['running','queued'].includes(runStatus) && !pendIds.has(t.run_id);
  });
  const histOut = outcomes.filter(o=>!pendIds.has(o.run_id));

  // Pending
  const pb = document.getElementById('pending-badge');
  const pl = document.getElementById('pending-list');
  if(pending.length){
    pb.textContent=pending.length; pb.style.display='';
    pl.innerHTML='';
    pending.forEach(tk=>{
      const scale=tk.work_scale||(tk.plan&&tk.plan.work_scale)||'';
      const el=makeItem(tk.run_id,tk.title||tk.run_type||tk.run_id,scale,'pending_review',tk.created_utc,()=>openRun(tk,el));
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
      const el=makeItem(tk.run_id,tk.title||tk.run_type||tk.run_id,scale,runStatus,tk.created_utc,()=>openRun(tk,el));
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
}

// ── Open run ─────────────────────────────────────────────
async function openRun(run, navEl) {
  clearActive(); if(navEl) navEl.classList.add('active');
  curRunId=run.run_id;
  const runStatus = run.run_status || '';
  const workScale = run.work_scale || (run.plan && run.plan.work_scale) || '';
  const campaignId = run.campaign_id || (run.plan && run.plan.campaign_id) || run.run_id;
  document.getElementById('det-title').textContent = run.title||run.run_type||run.run_id;
  setBadge(runStatus);
  const sc=document.getElementById('det-scale');
  if(workScale){sc.textContent=workScale;sc.style.display='';}else sc.style.display='none';
  document.getElementById('det-time').textContent = relTime(run.created_utc);

  const isRunning=['running','queued'].includes(runStatus);
  const ctrl=document.getElementById('det-controls');
  if(isRunning){
    ctrl.classList.remove('hidden');
    ['btn-pause','btn-redirect','btn-cancel'].forEach(id=>document.getElementById(id).style.display='');
  } else ctrl.classList.add('hidden');

  const pw=document.getElementById('prog-wrap');
  if(isRunning){
    pw.style.display='block';
    const pct=run.progress_pct||(run.step_index&&run.total_steps?Math.round(run.step_index/run.total_steps*100):0);
    document.getElementById('prog-fill').style.width=pct+'%';
    document.getElementById('prog-label').textContent=run.current_step||'';
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
  else if(isRunning) document.getElementById('output-body').innerHTML=`<p style="color:var(--muted);font-size:13px">${esc(run.current_step||'Run is active…')}</p>`;
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
