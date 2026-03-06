// ── Views ─────────────────────────────────────────────────
function showCompose() {
  clearActive();
  document.getElementById('view-compose').style.display = 'flex';
  document.getElementById('view-detail').style.display = 'none';
  document.getElementById('view-circuits').style.display = 'none';
  setTimeout(()=>document.getElementById('compose-textarea').focus(),50);
}
function showDetail() {
  document.getElementById('view-compose').style.display = 'none';
  document.getElementById('view-detail').style.display = 'flex';
  document.getElementById('view-circuits').style.display = 'none';
}
function clearActive() {
  document.querySelectorAll('.nav-item').forEach(el=>el.classList.remove('active'));
}
