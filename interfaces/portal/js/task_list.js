// ── Nav data ──────────────────────────────────────────────
let tasks=[], outcomes=[];
let curTaskId=null;

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

function makeItem(task_id, title, scale, status, time, onClick) {
  const el = document.createElement('div');
  el.className = 'nav-item'; el.dataset.id = task_id;
  el.innerHTML = `<span class="n-dot ${dotCls(status)}"></span>
    <span class="n-title">${esc(title||task_id)}</span>
    ${scale?`<span class="n-scale">${esc(scale)}</span>`:''}
    <span class="n-time">${esc(relTime(time))}</span>`;
  el.onclick = onClick;
  return el;
}

async function renderNav() {
  try { tasks = await api('/tasks?limit=200'); } catch(e){ tasks=[]; }
  try { outcomes = await api('/outcome?limit=200'); } catch(e){ outcomes=[]; }
  let pendFb = [];
  try { pendFb = await api('/feedback/pending?limit=50'); } catch(e){}
  const fbIds = new Set((pendFb||[]).map(x=>x.task_id));

  const pending = tasks.filter(t=>fbIds.has(t.task_id)||t.status==='pending_review');
  const pendIds = new Set(pending.map(t=>t.task_id));
  const running = tasks.filter(t=>['running','queued'].includes(t.status)&&!pendIds.has(t.task_id));
  const histOut = outcomes.filter(o=>!pendIds.has(o.task_id));

  // Pending
  const pb = document.getElementById('pending-badge');
  const pl = document.getElementById('pending-list');
  if(pending.length){
    pb.textContent=pending.length; pb.style.display='';
    pl.innerHTML='';
    pending.forEach(tk=>{
      const el=makeItem(tk.task_id,tk.title||tk.task_type||tk.task_id,tk.task_scale,'pending_review',tk.created_utc,()=>openTask(tk,el));
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
      const el=makeItem(tk.task_id,tk.title||tk.task_type||tk.task_id,tk.task_scale,tk.status,tk.created_utc,()=>openTask(tk,el));
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

// ── Open task ─────────────────────────────────────────────
async function openTask(task, navEl) {
  clearActive(); if(navEl) navEl.classList.add('active');
  curTaskId=task.task_id;
  document.getElementById('det-title').textContent = task.title||task.task_type||task.task_id;
  setBadge(task.status);
  const sc=document.getElementById('det-scale');
  if(task.task_scale){sc.textContent=task.task_scale;sc.style.display='';}else sc.style.display='none';
  document.getElementById('det-time').textContent = relTime(task.created_utc);

  const isRunning=['running','queued'].includes(task.status);
  const ctrl=document.getElementById('det-controls');
  if(isRunning){
    ctrl.classList.remove('hidden');
    ['btn-pause','btn-redirect','btn-cancel'].forEach(id=>document.getElementById(id).style.display='');
  } else ctrl.classList.add('hidden');

  const pw=document.getElementById('prog-wrap');
  if(isRunning){
    pw.style.display='block';
    const pct=task.progress_pct||(task.step_index&&task.total_steps?Math.round(task.step_index/task.total_steps*100):0);
    document.getElementById('prog-fill').style.width=pct+'%';
    document.getElementById('prog-label').textContent=task.current_step||'';
  } else pw.style.display='none';

  document.getElementById('output-body').innerHTML='<p style="color:var(--muted);font-size:13px">Loading…</p>';
  document.getElementById('ms-timeline').style.display='none';
  document.getElementById('rating-wrap').style.display='none';
  showDetail();

  if(task.task_scale==='campaign'){
    try{ const c=await api('/campaigns/'+task.task_id); renderCampaign(c); }catch(e){ document.getElementById('output-body').innerHTML=''; }
    return;
  }
  const match=outcomes.find(o=>o.task_id===task.task_id);
  if(match) await renderOutcomeContent(match);
  else if(isRunning) document.getElementById('output-body').innerHTML=`<p style="color:var(--muted);font-size:13px">${esc(task.current_step||'Task is running…')}</p>`;
  else document.getElementById('output-body').innerHTML=`<p style="color:var(--muted);font-size:13px">No output yet.</p>`;
}

async function openOutcome(outcome, navEl) {
  clearActive(); if(navEl) navEl.classList.add('active');
  curTaskId=outcome.task_id;
  document.getElementById('det-title').textContent=outcome.title||outcome.task_id;
  setBadge('completed');
  const sc=document.getElementById('det-scale');
  if(outcome.task_type){sc.textContent=outcome.task_type;sc.style.display='';}else sc.style.display='none';
  document.getElementById('det-time').textContent=relTime(outcome.delivered_utc||outcome.archived_utc);
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
      await showRating(outcome.task_id); return;
    }
    const mr=await fetch(API+'/outcome/'+path+'/report.md');
    if(mr.ok){ body.innerHTML=md(await mr.text()); await showRating(outcome.task_id); return; }
    const mfr=await fetch(API+'/outcome/'+path+'/manifest.json');
    if(mfr.ok){
      const mf=await mfr.json();
      if(!curTaskId&&mf.task_id) curTaskId=mf.task_id;
      body.innerHTML=`<pre>${esc(JSON.stringify(mf,null,2))}</pre>`;
      await showRating(curTaskId); return;
    }
    body.innerHTML='<p style="color:var(--muted)">No preview available.</p>';
  } catch(e){ body.innerHTML=`<p style="color:var(--red)">Error: ${esc(e.message)}</p>`; }
}

function renderCampaign(c) {
  const ms=c.milestones||[];
  if(ms.length){
    const tl=document.getElementById('ms-timeline');
    const ml=document.getElementById('ms-list');
    ml.innerHTML='';
    ms.forEach((m,i)=>{
      const cls=m.status==='completed'?'done':m.status==='running'?'active':m.status==='pending_review'?'needs-review':'';
      const row=document.createElement('div'); row.className='ms-row';
      row.innerHTML=`<div class="ms-num ${cls}">${i+1}</div>
        <div><div class="ms-name">${esc(m.name||'Milestone '+(i+1))}</div>
        <div class="ms-sub">${esc(m.status||'')}${m.completed_utc?' · '+relTime(m.completed_utc):''}</div></div>`;
      ml.appendChild(row);
    });
    tl.style.display='block';
  }
  document.getElementById('output-body').innerHTML=c.summary?md(c.summary):'';
}

function setBadge(s) {
  const b=document.getElementById('det-status');
  b.textContent=sLabel(s);
  b.className='sbadge s-'+s;
}

