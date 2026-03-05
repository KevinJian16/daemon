// ── Controls ──────────────────────────────────────────────
async function taskCancel(){
  if(!curTaskId||!confirm(t('cancelConfirm'))) return;
  const btn=document.getElementById('btn-cancel');
  btn.disabled=true; btn.textContent=t('cancellingMsg');
  try{ await api('/tasks/'+curTaskId+'/cancel',{method:'POST'}); btn.textContent=t('cancelOk'); setTimeout(renderNav,800); }
  catch(e){ btn.textContent=t('cancel'); btn.disabled=false; alert('Error: '+e.message); }
}
async function taskPause(){
  if(!curTaskId) return;
  try{ await api('/tasks/'+curTaskId+'/pause',{method:'POST'}); renderNav(); }
  catch(e){ alert('Error: '+e.message); }
}
async function taskRedirect(){
  if(!curTaskId) return;
  const ins=prompt(t('redirectPrompt')); if(!ins) return;
  try{ await api('/tasks/'+curTaskId+'/redirect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({instruction:ins})}); renderNav(); }
  catch(e){ alert('Error: '+e.message); }
}

