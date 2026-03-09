// ── Controls ──────────────────────────────────────────────
async function deedCancel(){
  if(!currentDeedId||!confirm(t('cancelConfirm'))) return;
  const btn=document.getElementById('btn-cancel');
  btn.disabled=true; btn.textContent=t('cancellingMsg');
  try{
    await api('/deeds/'+encodeURIComponent(currentDeedId)+'/cancel',{method:'POST'});
    btn.textContent=t('cancelOk');
    setTimeout(renderNav,800);
  }catch(e){ btn.textContent=t('cancel'); btn.disabled=false; alert('Error: '+e.message); }
}
async function deedPause(){
  if(!currentDeedId) return;
  try{
    await api('/deeds/'+encodeURIComponent(currentDeedId)+'/pause',{method:'POST'});
    document.getElementById('btn-pause').style.display='none';
    document.getElementById('btn-resume').style.display='';
    renderNav();
  }catch(e){ alert('Error: '+e.message); }
}
async function deedResume(){
  if(!currentDeedId) return;
  try{
    await api('/deeds/'+encodeURIComponent(currentDeedId)+'/resume',{method:'POST'});
    document.getElementById('btn-resume').style.display='none';
    document.getElementById('btn-pause').style.display='';
    renderNav();
  }catch(e){ alert('Error: '+e.message); }
}
async function deedRedirect(){
  if(!currentDeedId) return;
  const ins=prompt(t('redirectPrompt')); if(!ins) return;
  try{
    await api('/deeds/'+encodeURIComponent(currentDeedId)+'/append',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({requirement:ins,source:'portal'})
    });
    renderNav();
  }catch(e){ alert('Error: '+e.message); }
}
async function deedRetry(){
  if(!currentDeedId) return;
  try{
    const d=await api('/deeds/'+encodeURIComponent(currentDeedId)+'/retry',{method:'POST'});
    addChatMsg('system','✓ ' + (d.deed_id || ''));
    setTimeout(renderNav,600);
  }catch(e){ alert('Error: '+e.message); }
}
