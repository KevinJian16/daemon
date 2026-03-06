// ── Controls ──────────────────────────────────────────────
async function runCancel(){
  if(!curRunId||!confirm(t('cancelConfirm'))) return;
  const btn=document.getElementById('btn-cancel');
  btn.disabled=true; btn.textContent=t('cancellingMsg');
  try{ await api('/runs/'+curRunId+'/cancel',{method:'POST'}); btn.textContent=t('cancelOk'); setTimeout(renderNav,800); }
  catch(e){ btn.textContent=t('cancel'); btn.disabled=false; alert('Error: '+e.message); }
}
async function runPause(){
  if(!curRunId) return;
  try{ await api('/runs/'+curRunId+'/pause',{method:'POST'}); renderNav(); }
  catch(e){ alert('Error: '+e.message); }
}
async function runResume(){
  if(!curRunId) return;
  try{ await api('/runs/'+curRunId+'/resume',{method:'POST'}); renderNav(); }
  catch(e){ alert('Error: '+e.message); }
}
async function runRedirect(){
  if(!curRunId) return;
  const ins=prompt(t('redirectPrompt')); if(!ins) return;
  try{ await api('/runs/'+curRunId+'/append',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({requirement:ins,source:'portal'})}); renderNav(); }
  catch(e){ alert('Error: '+e.message); }
}
