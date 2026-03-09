// ── Controls ──────────────────────────────────────────────
async function deedCancel(){
  if(!curDeedId||!confirm(t('cancelConfirm'))) return;
  const btn=document.getElementById('btn-cancel');
  btn.disabled=true; btn.textContent=t('cancellingMsg');
  try{ await api('/deeds/'+curDeedId+'/cancel',{method:'POST'}); btn.textContent=t('cancelOk'); setTimeout(renderNav,800); }
  catch(e){ btn.textContent=t('cancel'); btn.disabled=false; alert('Error: '+e.message); }
}
async function deedPause(){
  if(!curDeedId) return;
  try{ await api('/deeds/'+curDeedId+'/pause',{method:'POST'}); renderNav(); }
  catch(e){ alert('Error: '+e.message); }
}
async function deedResume(){
  if(!curDeedId) return;
  try{ await api('/deeds/'+curDeedId+'/resume',{method:'POST'}); renderNav(); }
  catch(e){ alert('Error: '+e.message); }
}
async function deedRedirect(){
  if(!curDeedId) return;
  const ins=prompt(t('redirectPrompt')); if(!ins) return;
  try{ await api('/deeds/'+curDeedId+'/append',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({requirement:ins,source:'portal'})}); renderNav(); }
  catch(e){ alert('Error: '+e.message); }
}
