// ── Compose / Chat Send ───────────────────────────────────
let sessId=null, detPlan=null, attachFiles=[];

// Unified send: new conversation (Voice) or existing deed (message)
async function chatSend(){
  const ta=document.getElementById('compose-textarea');
  const msg=ta.value.trim(); if(!msg) return;
  const btn=document.getElementById('compose-send-btn');
  btn.disabled=true; ta.value=''; ta.style.height='auto';

  // T1: dissolve empty state
  const empty=document.getElementById('chat-empty');
  if(empty && empty.style.display!=='none'){
    empty.classList.add('dissolving');
    setTimeout(()=>{ empty.style.display='none'; empty.classList.remove('dissolving'); },400);
  }

  // If viewing an existing deed, send message to that deed
  if(currentDeedId){
    addChatMsg('user',msg);
    const thinking=addChatMsg('system','\u2026');
    try{
      await api('/deeds/'+encodeURIComponent(currentDeedId)+'/message',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({text:msg,source:'portal'})
      });
      thinking.remove();
    }catch(e){
      thinking.remove();
      addChatMsg('system','Error: '+e.message);
    }
    btn.disabled=false; ta.focus();
    return;
  }

  // New conversation: Voice flow
  addChatMsg('user',msg);
  const thinking=addChatMsg('system','\u2026');
  try{
    if(!sessId){
      const s=await api('/voice/session',{method:'POST'});
      sessId=s.session_id;
    }
    const d=await api('/voice/'+sessId,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:msg})
    });
    thinking.remove();
    addChatMsg('assistant',d.content||'');
    if(d.plan) showPlanCard(d.plan);
  }catch(e){
    thinking.remove();
    addChatMsg('system','Error: '+e.message);
  }
  btn.disabled=false; ta.focus();
}

// Legacy alias
function composeSend(){ chatSend(); }

// ── Plan Card: three forms per INTERACTION_DESIGN §1.2 ───
function showPlanCard(plan){
  detPlan=plan;
  const pd=plan.plan_display||{};
  const mode=pd.mode||plan.work_scale||(plan.brief&&plan.brief.complexity)||'';
  const c=document.getElementById('plan-card');
  const objective=plan.objective||plan.intent||plan.deed_type||'';

  // Errand: no plan card (§1.2: "无计划组件")
  if(mode==='errand'){
    c.style.display='none';
    return;
  }

  let html=`<div id="plan-card-hdr">
    <span>\u26A1</span><span>${esc(t('planDetected'))}</span>
  </div><div class="plan-body">`;

  if(objective) html+=`<div class="plan-objective">${esc(objective)}</div>`;

  if(mode==='charge'&&pd.timeline&&pd.timeline.length){
    // Charge: vertical timeline
    html+=_renderTimeline(pd.timeline,'pending');
  }else if(mode==='endeavor'&&pd.passages&&pd.passages.length){
    // Endeavor: segmented passages
    html+=_renderPassages(pd.passages,null);
  }else{
    html+=`<div class="plan-objective">${esc(objective||JSON.stringify(plan).slice(0,120))}</div>`;
  }

  const scale=plan.work_scale||mode||'';
  if(scale) html+=`<div class="plan-scale">${esc(scale)}</div>`;

  html+=`<div class="plan-actions">
    <button class="btn btn-primary btn-sm" id="plan-ok-btn" onclick="submitPlan()">${esc(t('submitPlan'))}</button>
    <button class="btn btn-ghost btn-sm" onclick="dismissPlan()">${esc(t('rewrite'))}</button>
  </div></div>`;

  c.innerHTML=html;
  c.style.display='block';
  c.classList.add('entering');
  setTimeout(()=>c.classList.remove('entering'),500);
  c.scrollIntoView({behavior:'smooth',block:'end'});
}

// Render plan progress component for existing running/completed deeds
function showDeedPlan(deed){
  const plan=deed.plan||{};
  const pd=plan.plan_display||{};
  const mode=pd.mode||plan.work_scale||(plan.brief&&plan.brief.complexity)||'';
  if(mode==='errand'||(!pd.timeline&&!pd.passages)) return;

  const container=document.getElementById('chat-messages');
  const el=document.createElement('div');
  el.className='deed-plan-component';
  el.id='deed-plan-live';

  const deedStatus=_deedStatus(deed);
  const isComplete=['completed','done','cancelled'].includes(deedStatus);

  if(mode==='charge'&&pd.timeline&&pd.timeline.length){
    const allState=isComplete?'done':'pending';
    el.innerHTML=_renderTimeline(pd.timeline,allState);
  }else if(mode==='endeavor'&&pd.passages&&pd.passages.length){
    el.innerHTML=_renderPassages(pd.passages,isComplete?pd.passages.length:null);
  }

  if(el.innerHTML) container.appendChild(el);
}

// ── Shared renderers ─────────────────────────────────────
function _renderTimeline(steps,defaultState){
  const total=steps.length;
  const doneCount=steps.filter((_,i)=>defaultState==='done'||(typeof defaultState==='number'&&i<defaultState)).length;
  const pct=total?Math.round(doneCount/total*100):0;
  let html=`<div class="plan-timeline">
    <div class="plan-pbar"><div class="plan-pbar-fill" style="width:${pct}%"></div></div>
    <div class="plan-steps">`;
  steps.forEach((step,i)=>{
    const state=(defaultState==='done')?'done':
      (typeof defaultState==='number'&&i<defaultState)?'done':
      (typeof defaultState==='number'&&i===defaultState)?'active':'pending';
    html+=`<div class="plan-step ${state}" data-step-id="${esc(step.id||'')}" data-idx="${i}">
      <div class="step-dot"><svg class="step-check" viewBox="0 0 12 12"><polyline points="2,6 5,9 10,3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
      <div class="step-label">${esc(step.label||step.instruction||'')}</div>
    </div>`;
  });
  html+=`</div></div>`;
  return html;
}

function _renderPassages(passages,currentIdx){
  let html=`<div class="plan-passages">
    <div class="passage-pbar">`;
  passages.forEach((_,i)=>{
    const state=(currentIdx!=null&&i<currentIdx)?'done':
      (currentIdx!=null&&i===currentIdx)?'current':'pending';
    html+=`<div class="passage-seg ${state}" data-pidx="${i}"></div>`;
  });
  html+=`</div><div class="passage-list">`;
  passages.forEach((p,i)=>{
    const state=(currentIdx!=null&&i<currentIdx)?'done':
      (currentIdx!=null&&i===currentIdx)?'current':'pending';
    const detail=p.move_count?(p.move_count+(lang==='zh'?' \u6B65':' steps')):'';
    html+=`<div class="passage-item ${state}" data-pidx="${i}">
      <div class="passage-hdr">
        <span class="passage-dot"></span>
        <span class="passage-title">${esc(p.title||((lang==='zh'?'\u9636\u6BB5 ':'Phase ')+(i+1)))}</span>
        ${detail?`<span class="passage-detail">${esc(detail)}</span>`:''}
      </div>
    </div>`;
  });
  html+=`</div></div>`;
  return html;
}

function dismissPlan(){
  detPlan=null;
  document.getElementById('plan-card').style.display='none';
}

async function submitPlan(){
  if(!detPlan) return;
  const btn=document.getElementById('plan-ok-btn');
  btn.disabled=true; btn.textContent='\u2026';

  // T3: light up first step
  const firstStep=document.querySelector('#plan-card .plan-step');
  if(firstStep){ firstStep.classList.remove('pending'); firstStep.classList.add('active'); }

  try{
    const d=await api('/submit',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(detPlan)
    });
    dismissPlan();
    const deedId=d.deed_id||'';
    addChatMsg('system','\u2713 '+(d.deed_title||deedId));
    sessId=null;

    // T3: update placeholder
    const ta=document.getElementById('compose-textarea');
    ta.placeholder=t('chatPlaceholder');

    if(deedId){
      setTimeout(async ()=>{
        await renderNav();
        const deed=deeds.find(dk=>dk.deed_id===deedId);
        if(deed){
          const navEl=document.querySelector('.nav-item[data-id="'+CSS.escape(deedId)+'"]');
          openDeed(deed,navEl);
        }
      },600);
    }else{
      setTimeout(renderNav,600);
    }
  }catch(e){
    addChatMsg('system','Error: '+e.message);
    btn.disabled=false; btn.textContent=t('submitPlan');
  }
}

function onFilesSelected(inp){
  Array.from(inp.files).forEach(f=>{ if(!attachFiles.find(x=>x.name===f.name)) attachFiles.push(f); });
  inp.value=''; renderChips();
}
function renderChips(){
  document.getElementById('compose-file-chips').innerHTML=attachFiles.map((f,i)=>`
    <div class="fchip"><span>${esc(f.name)}</span><button onclick="rmFile(${i})">\u00d7</button></div>`).join('');
}
function rmFile(i){ attachFiles.splice(i,1); renderChips(); }
