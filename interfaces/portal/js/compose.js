// ── Compose ───────────────────────────────────────────────
let sessId=null, detPlan=null, attachFiles=[];

function addMsg(role, text) {
  const hist=document.getElementById('chat-history');
  // Hide empty state once messages appear
  document.getElementById('compose-empty').style.display='none';
  const div=document.createElement('div'); div.className='cmsg '+role;
  if(role==='assistant') div.innerHTML=md(text); else div.textContent=text;
  hist.appendChild(div);
  div.scrollIntoView({behavior:'smooth',block:'end'});
  return div;
}

async function composeSend(){
  const ta=document.getElementById('compose-textarea');
  const msg=ta.value.trim(); if(!msg) return;
  const btn=document.getElementById('compose-send-btn');
  btn.disabled=true; ta.value=''; ta.style.height='auto';
  addMsg('user',msg);
  const thinking=addMsg('system','…');
  try{
    let running=[];
    try{ running=await api('/deeds?phase=running&limit=5'); }catch(_){}
    const active=(running&&running[0])||null;
    const lower=msg.toLowerCase();
    const isCancel=lower==='cancel'||msg==='取消';
    const isPause=lower==='pause'||msg==='暂停';
    const isResume=lower==='resume'||msg==='继续';
    if(active&&active.deed_id){
      if(isCancel){
        await api('/deeds/'+encodeURIComponent(active.deed_id)+'/cancel',{method:'POST'});
        thinking.remove(); addMsg('assistant',`已发送取消请求：${active.deed_title||active.title||active.deed_id}`);
        setTimeout(renderNav,500);
        return;
      }
      if(isPause){
        try{
          await api('/deeds/'+encodeURIComponent(active.deed_id)+'/pause',{method:'POST'});
          thinking.remove(); addMsg('assistant',`已发送暂停请求：${active.deed_title||active.title||active.deed_id}`);
        }catch(e){
          thinking.remove(); addMsg('assistant','暂停暂不支持，建议直接使用取消。');
        }
        setTimeout(renderNav,500);
        return;
      }
      if(isResume){
        try{
          await api('/deeds/'+encodeURIComponent(active.deed_id)+'/resume',{method:'POST'});
          thinking.remove(); addMsg('assistant',`已发送继续请求：${active.deed_title||active.title||active.deed_id}`);
        }catch(e){
          thinking.remove(); addMsg('assistant','继续暂不支持，建议在 Portal 面板中继续操作。');
        }
        setTimeout(renderNav,500);
        return;
      }
      await api('/deeds/'+encodeURIComponent(active.deed_id)+'/append',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({requirement:msg,source:'portal'})
      });
      thinking.remove();
      addMsg('assistant',`已追加到运行：${active.deed_title||active.title||active.deed_id}`);
      setTimeout(renderNav,500);
      return;
    }

    if(!sessId){ const s=await api('/voice/session',{method:'POST'}); sessId=s.session_id; }
    const d=await api('/voice/'+sessId,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg})});
    thinking.remove(); addMsg('assistant',d.content||'');
    if(d.plan) showPlanCard(d.plan);
  }catch(e){ thinking.remove(); addMsg('system','✗ '+e.message); }
  finally{ btn.disabled=false; ta.focus(); }
}
function showPlanCard(plan){
  detPlan=plan;
  const c=document.getElementById('plan-card'); c.style.display='block';
  document.getElementById('plan-summary').textContent=plan.objective||plan.intent||plan.deed_type||JSON.stringify(plan).slice(0,120);
  document.getElementById('plan-scale').textContent=(plan.work_scale||plan.work_scale)?'Scale: '+(plan.work_scale||plan.work_scale):'';
}
function dismissPlan(){ detPlan=null; document.getElementById('plan-card').style.display='none'; }
async function submitPlan(){
  if(!detPlan) return;
  const btn=document.getElementById('plan-ok-btn'); btn.disabled=true; btn.textContent='…';
  try{
    const d=await api('/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(detPlan)});
    dismissPlan(); addMsg('system','✓ Submitted — '+(d.deed_id||''));
    sessId=null; setTimeout(renderNav,600);
  }catch(e){ addMsg('system','✗ '+e.message); btn.disabled=false; btn.textContent=t('submitPlan'); }
}
function onFilesSelected(inp){
  Array.from(inp.files).forEach(f=>{ if(!attachFiles.find(x=>x.name===f.name)) attachFiles.push(f); });
  inp.value=''; renderChips();
}
function renderChips(){
  document.getElementById('compose-file-chips').innerHTML=attachFiles.map((f,i)=>`
    <div class="fchip"><span>${esc(f.name)}</span><button onclick="rmFile(${i})">×</button></div>`).join('');
}
function rmFile(i){ attachFiles.splice(i,1); renderChips(); }
