// ── History grouped + search ──────────────────────────────
let histAllOfferings=[];
// Group collapse state: key=groupKey, value=bool collapsed
const histGroupState={};

function timeGroupKey(utcStr){
  if(!utcStr) return 'older';
  const d=new Date(utcStr.replace(' ','T').replace(/(?<!\+\d{2})$/,'Z'));
  const now=new Date(); const diff=(now-d)/86400000;
  if(diff<1) return 'today';
  if(diff<7) return 'week';
  if(diff<30) return 'month';
  return 'older';
}
function timeGroupLabel(key){
  const m={today:lang==='zh'?'今天':'Today',week:lang==='zh'?'本周':'This Week',month:lang==='zh'?'本月':'This Month',older:lang==='zh'?'更早':'Older'};
  return m[key]||key;
}

function renderHistoryGrouped(items){
  const container=document.getElementById('history-groups');
  container.innerHTML='';
  if(!items.length){
    container.innerHTML=`<div class="nav-empty" style="padding:6px 14px">${t('none')}</div>`;
    return;
  }
  const groups={today:[],week:[],month:[],older:[]};
  items.forEach(o=>groups[timeGroupKey(o.delivered_utc)].push(o));
  ['today','week','month','older'].forEach(key=>{
    const grpItems=groups[key]; if(!grpItems.length) return;
    // Default: 'older' is collapsed; restore saved state
    const savedKey='d_hg_'+key;
    const defCollapsed=key==='older';
    if(!(savedKey in histGroupState)){
      histGroupState[savedKey]=localStorage.getItem(savedKey)==='1'||(localStorage.getItem(savedKey)===null&&defCollapsed);
    }
    const grp=document.createElement('div'); grp.className='time-group'+(histGroupState[savedKey]?' collapsed':'');
    const lbl=document.createElement('div'); lbl.className='time-group-label';
    lbl.innerHTML=`<span>${timeGroupLabel(key)}</span><span style="color:var(--muted);font-weight:400;font-size:10px">${grpItems.length}</span><span class="tg-chevron">▾</span>`;
    lbl.onclick=()=>{
      const c=grp.classList.toggle('collapsed');
      histGroupState[savedKey]=c;
      localStorage.setItem(savedKey,c?'1':'0');
    };
    const body=document.createElement('div'); body.className='time-group-body';
    grpItems.forEach(o=>{
      const el=makeItem(o.deed_id,o.title||o.deed_id,o.deed_type,'completed',o.delivered_utc,()=>openOffering(o,el));
      body.appendChild(el);
    });
    grp.appendChild(lbl); grp.appendChild(body);
    container.appendChild(grp);
  });
}

function filterHistory(q){
  const query=(q||'').trim().toLowerCase();
  const container=document.getElementById('history-groups');
  if(!query){ renderHistoryGrouped(histAllOfferings); return; }
  const filtered=histAllOfferings.filter(o=>(o.title||o.deed_id||'').toLowerCase().includes(query));
  container.innerHTML='';
  if(!filtered.length){ container.innerHTML=`<div class="nav-empty" style="padding:6px 14px">${t('none')}</div>`; return; }
  filtered.forEach(o=>{
    const el=makeItem(o.deed_id,o.title||o.deed_id,o.deed_type,'completed',o.delivered_utc,()=>openOffering(o,el));
    container.appendChild(el);
  });
}
