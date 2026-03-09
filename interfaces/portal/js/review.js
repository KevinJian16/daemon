// ── Rating ────────────────────────────────────────────────
let quickChoice=null; // {v, label}
function refreshRatingSubmitEnabled(){
  const btn=document.getElementById('rating-ok-btn');
  if(!btn) return;
  const note=(document.getElementById('deep-note')?.value||'').trim();
  btn.disabled=!(quickChoice||note);
}
function pickChoice(el){
  document.querySelectorAll('.q-choice').forEach(b=>b.classList.remove('sel'));
  el.classList.add('sel');
  quickChoice={v:parseInt(el.dataset.v,10), label:el.textContent.trim()};
  refreshRatingSubmitEnabled();
}
function choiceLabel(v){
  const target=String(v||'').trim();
  const btn=[...document.querySelectorAll('.q-choice')].find(b=>String(b.dataset.v||'')===target);
  return btn ? btn.textContent.trim() : target;
}
function renderFeedbackHistory(rows){
  const box=document.getElementById('rating-history');
  if(!rows || !rows.length){ box.innerHTML=''; return; }
  box.innerHTML=rows.map(r=>{
    const when=relTime(r.created_utc||'');
    const label=(lang==='zh'?'来源':'Source')+': '+esc(r.source||'user');
    const rating=(r.rating!=null&&r.rating!=='')?`<strong>${esc(choiceLabel(r.rating))}</strong>`:'';
    const comment=r.comment?` ${esc(r.comment)}`:'';
    return `<div class="rating-h-row">${when} · ${label} ${rating}${comment}</div>`;
  }).join('');
}
async function showRating(tid){
  curDeedId=tid||curDeedId;
  if(!curDeedId) return;
  const w=document.getElementById('rating-wrap'); w.style.display='block';
  const qWrap=document.getElementById('q-choices');
  const deepBtn=document.getElementById('rating-deep-btn');
  const deepWrap=document.getElementById('deep-wrap');
  const appendWrap=document.getElementById('append-wrap');
  const appendStatus=document.getElementById('append-status');
  const appendNote=document.getElementById('append-note');
  const ratingBtn=document.getElementById('rating-ok-btn');
  quickChoice=null;
  document.querySelectorAll('.q-choice').forEach(b=>b.classList.remove('sel'));
  ratingBtn.disabled=true;
  deepWrap.classList.remove('open');
  document.getElementById('deep-note').value='';
  document.getElementById('rating-status').textContent='';
  document.getElementById('rating-status').className='';
  appendStatus.textContent='';
  appendStatus.className='';
  appendNote.value='';
  const ex=document.getElementById('rating-existing');
  ex.textContent='';

  let state={};
  try{ state=await api('/feedback/'+curDeedId+'/state'); }catch(e){ state={}; }
  const response=(state&&state.response)||{};
  const history=(state&&Array.isArray(state.history))?state.history:[];
  const submitted=String((state&&state.status)||'').toLowerCase()==='submitted';
  const hasMain=submitted||(
    response &&
    (
      (response.rating!=null && response.rating!=='') ||
      String(response.comment||'').trim().length>0
    )
  );

  if(hasMain){
    if(response.rating!=null && response.rating!==''){
      ex.textContent=(lang==='zh'?'已评价：':'Rated: ')+choiceLabel(response.rating)+(response.comment?` · ${response.comment}`:'');
    }else{
      ex.textContent=(lang==='zh'?'已提交详细评价':'Detailed feedback submitted')+(response.comment?` · ${response.comment}`:'');
    }
    qWrap.style.display='none';
    ratingBtn.style.display='none';
    deepBtn.style.display='none';
    deepWrap.classList.remove('open');
    deepWrap.style.display='none';
    appendWrap.style.display='block';
    renderFeedbackHistory(history);
  }else{
    qWrap.style.display='flex';
    ratingBtn.style.display='inline-flex';
    deepBtn.style.display='inline';
    deepWrap.classList.remove('open');
    deepWrap.style.display='';
    appendWrap.style.display='none';
    renderFeedbackHistory([]);
    refreshRatingSubmitEnabled();
  }
}
function toggleDeep(){
  const el=document.getElementById('deep-wrap');
  el.classList.toggle('open');
  refreshRatingSubmitEnabled();
}
async function submitRating(){
  if(!curDeedId) return;
  const btn=document.getElementById('rating-ok-btn');
  const st=document.getElementById('rating-status');
  btn.disabled=true; st.textContent=t('submitting'); st.className='';
  const note=document.getElementById('deep-note').value.trim();
  const payload={source:'portal'};
  if(quickChoice){
    payload.rating=quickChoice.v;
    payload.type=note?'deep':'quick';
  }else if(note){
    payload.type='deep';
  }else{
    st.textContent=''; btn.disabled=false; return;
  }
  if(note) payload.comment=note;
  try{
    await api('/deeds/'+curDeedId+'/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    st.textContent=t('submitOk'); st.className='ok';
    await showRating(curDeedId);
    setTimeout(renderNav,500);
  }catch(e){ st.textContent='✗ '+e.message; btn.disabled=false; }
}
async function submitAppend(){
  if(!curDeedId) return;
  const note=document.getElementById('append-note').value.trim();
  if(!note) return;
  const btn=document.getElementById('append-ok-btn');
  const st=document.getElementById('append-status');
  btn.disabled=true; st.textContent=t('submitting'); st.className='';
  try{
    await api('/deeds/'+curDeedId+'/feedback/append',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({comment:note, source:'portal'}),
    });
    st.textContent=t('submitOk'); st.className='ok';
    document.getElementById('append-note').value='';
    await showRating(curDeedId);
  }catch(e){
    st.textContent='✗ '+e.message;
  }finally{
    btn.disabled=false;
  }
}
