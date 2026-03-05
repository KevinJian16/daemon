// ── Boot ──────────────────────────────────────────────────
async function boot(){
  applyI18n();
  showCompose();
  await Promise.all([checkGate(), renderNav()]);
  // Auto-open first pending if any
  const first=document.querySelector('#pending-list .nav-item');
  if(first) first.click();
  setInterval(()=>{ checkGate(); renderNav(); }, 15000);
}
document.addEventListener('DOMContentLoaded', boot);
