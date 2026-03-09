// ── Nav data ──────────────────────────────────────────────
let deeds=[], offerings=[];
let curDeedId=null;

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

function makeItem(deed_id, title, scale, deedStatus, time, onClick) {
  const el = document.createElement('div');
  el.className = 'nav-item'; el.dataset.id = deed_id;
  el.innerHTML = `<span class="n-dot ${dotCls(deedStatus)}"></span>
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
  try { offerings = await api('/offering?limit=200'); } catch(e){ offerings=[]; }
  const pending = awaitingDeeds || [];
  const running = runningDeeds || [];
  const histOut = offerings || [];

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

  // History
  histAllOfferings=histOut;
  renderHistoryGrouped(histOut);
  // Update search placeholder for current lang
  const hs=document.getElementById('history-search');
  if(hs) hs.placeholder=lang==='zh'?hs.dataset.phZh:hs.dataset.phEn;

}

// ── Open deed ─────────────────────────────────────────────
async function openDeed(deed, navEl) {
  clearActive(); if(navEl) navEl.classList.add('active');
  curDeedId=deed.deed_id;
  const deedStatus = deed.deed_status || '';
  const workScale = deed.work_scale || (deed.plan && deed.plan.work_scale) || '';
  const endeavorId = deed.endeavor_id || (deed.plan && deed.plan.endeavor_id) || deed.deed_id;
  document.getElementById('det-title').textContent = deed.deed_title||deed.title||deed.deed_type||deed.deed_id;
  setBadge(deedStatus);
  const sc=document.getElementById('det-scale');
  if(workScale){sc.textContent=workScale;sc.style.display='';}else sc.style.display='none';
  document.getElementById('det-time').textContent = relTime(deed.created_utc);

  const deedStatusLower = String(deedStatus || '').toLowerCase();
  const isRunning=['running','queued','cancelling'].includes(deedStatusLower);
  const isPaused = deedStatusLower === 'paused';
  const ctrl=document.getElementById('det-controls');
  if(isRunning || isPaused){
    ctrl.classList.remove('hidden');
    const isEndeavor = String(workScale || '').toLowerCase() === 'endeavor';
    document.getElementById('btn-resume').style.display = isPaused && !isEndeavor ? '' : 'none';
    document.getElementById('btn-pause').style.display = isRunning && !isEndeavor ? '' : 'none';
    document.getElementById('btn-redirect').style.display = isRunning && !isEndeavor ? '' : 'none';
    document.getElementById('btn-cancel').style.display = '';
  } else ctrl.classList.add('hidden');

  const pw=document.getElementById('prog-wrap');
  if(isRunning){
    pw.style.display='block';
    const pct=deed.progress_pct||(deed.move_index&&deed.total_moves?Math.round(deed.move_index/deed.total_moves*100):0);
    document.getElementById('prog-fill').style.width=pct+'%';
    document.getElementById('prog-label').textContent=deed.current_move||'';
  } else if (isPaused) {
    pw.style.display='block';
    document.getElementById('prog-fill').style.width='100%';
    document.getElementById('prog-label').textContent=lang==='zh'?'已暂停':'Paused';
  } else pw.style.display='none';

  document.getElementById('output-body').innerHTML='<p style="color:var(--muted);font-size:13px">Loading…</p>';
  document.getElementById('ms-timeline').style.display='none';
  document.getElementById('rating-wrap').style.display='none';
  showDetail();

  if(workScale==='endeavor'){
    try{ const c=await api('/endeavors/'+encodeURIComponent(endeavorId)); renderEndeavor(c); }catch(e){ document.getElementById('output-body').innerHTML=''; }
    return;
  }
  const match=offerings.find(o=>o.deed_id===deed.deed_id);
  if(match) await renderOfferingContent(match);
  else if(isRunning || isPaused) document.getElementById('output-body').innerHTML=`<p style="color:var(--muted);font-size:13px">${esc(deed.current_move|| (isPaused ? (lang==='zh'?'已暂停':'Paused') : 'Deed is active…'))}</p>`;
  else document.getElementById('output-body').innerHTML=`<p style="color:var(--muted);font-size:13px">No output yet.</p>`;
}

async function openOffering(offering, navEl) {
  clearActive(); if(navEl) navEl.classList.add('active');
  curDeedId=offering.deed_id;
  document.getElementById('det-title').textContent=offering.title||offering.deed_id;
  setBadge('completed');
  const sc=document.getElementById('det-scale');
  if(offering.deed_type){sc.textContent=offering.deed_type;sc.style.display='';}else sc.style.display='none';
  document.getElementById('det-time').textContent=relTime(offering.delivered_utc);
  document.getElementById('det-controls').classList.add('hidden');
  document.getElementById('prog-wrap').style.display='none';
  document.getElementById('ms-timeline').style.display='none';
  showDetail();
  await renderOfferingContent(offering);
}

async function renderOfferingContent(offering) {
  const body=document.getElementById('output-body');
  body.innerHTML='<p style="color:var(--muted);font-size:13px">Loading…</p>';
  const path=(offering.path||'').replace(/^\/|\/+$/g,'');
  try {
    const hr=await fetch(API+'/offering/'+path+'/report.html');
    if(hr.ok){
      body.innerHTML='';
      const fr=document.createElement('iframe');
      fr.style.cssText='width:100%;min-height:480px;border:1px solid var(--border);border-radius:var(--r);display:block;background:white';
      fr.srcdoc=await hr.text();
      body.appendChild(fr);
      await showRating(offering.deed_id); return;
    }
    const mr=await fetch(API+'/offering/'+path+'/report.md');
    if(mr.ok){ body.innerHTML=md(await mr.text()); await showRating(offering.deed_id); return; }
    body.innerHTML='<p style="color:var(--muted)">No preview available.</p>';
  } catch(e){ body.innerHTML=`<p style="color:var(--red)">Error: ${esc(e.message)}</p>`; }
}

function renderEndeavor(c) {
  const data = (c && c.manifest) ? c.manifest : (c || {});
  const ps=data.passages||[];
  if(ps.length){
    const tl=document.getElementById('ms-timeline');
    const ml=document.getElementById('ms-list');
    ml.innerHTML='';
    ps.forEach((p,i)=>{
      const passageStatus = p.passage_status || '';
      const cls=
        passageStatus==='passed' || passageStatus==='skipped' ? 'done' :
        passageStatus==='running' ? 'active' :
        passageStatus==='failed' ? 'needs-review' : '';
      const row=document.createElement('div'); row.className='ms-row';
      row.innerHTML=`<div class="ms-num ${cls}">${i+1}</div>
        <div><div class="ms-name">${esc(p.title||p.name||('Passage '+(i+1)))}</div>
        <div class="ms-sub">${esc(passageStatus)}${p.completed_utc?' · '+relTime(p.completed_utc):''}</div></div>`;
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
