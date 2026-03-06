// ── i18n ──────────────────────────────────────────────────
const D = {
  zh:{
    pending:'待处理',running:'进行中',history:'历史',none:'暂无',
    composeTitle:'需要做什么？',composeHint:'描述你的目标，系统自动判断为 Pulse/Thread/Campaign 并分配 agent。',
    planDetected:'检测到运行计划',submitPlan:'确认提交',rewrite:'重新描述',
    send:'发送',pause:'暂停',redirect:'调整方向',cancel:'取消运行',
    milestones:'Milestone 进度',
    rateTitle:'这个结果怎么样？',submitRating:'提交评价',deepFeedback:'详细评价',
    appendTitle:'追加评价',appendSubmit:'提交追加评价',
    commentPh:'可选：写一句评价…',
    dimAlign:'意图对齐 — 结果符合你最初的要求吗？',
    dimDepth:'质量深度 — 内容的深度和密度满足需求吗？',
    dimImprove:'最想改进的地方（选填）',
    alignFull:'完全符合',alignMostly:'基本符合',alignPartial:'部分符合',alignMiss:'偏差较大',
    depthEx:'超出预期',depthGood:'满足需求',depthShallow:'偏浅',depthPoor:'不足',
    submitting:'提交中…',submitOk:'已记录 ✓',cancellingMsg:'取消中…',cancelOk:'已取消',
    s_running:'进行中',s_queued:'排队中',s_completed:'已完成',s_done:'已完成',
    s_failed:'失败',s_cancelled:'已取消',s_pending_review:'待评价',
    hideDeep:'收起详细评价',attachTip:'添加附件',composeTip:'新建运行',
    cancelConfirm:'确认取消这次运行？',redirectPrompt:'新的方向或补充说明：',
  },
  en:{
    pending:'Pending',running:'Running',history:'History',none:'None',
    composeTitle:'What do you need?',composeHint:'Describe your objective. Daemon will classify Pulse/Thread/Campaign and assign agents.',
    planDetected:'Run plan detected',submitPlan:'Submit',rewrite:'Rewrite',
    send:'Send',pause:'Pause',redirect:'Redirect',cancel:'Cancel Run',
    milestones:'Milestone Progress',
    rateTitle:'How was this result?',submitRating:'Submit Rating',deepFeedback:'Detailed Feedback',
    appendTitle:'Additional Feedback',appendSubmit:'Submit Follow-up',
    commentPh:'Optional: add a comment…',
    dimAlign:'Intent Alignment — did the result match your original request?',
    dimDepth:'Quality Depth — was the depth and density sufficient?',
    dimImprove:'What would you most want improved? (optional)',
    alignFull:'Fully aligned',alignMostly:'Mostly aligned',alignPartial:'Partially',alignMiss:'Missed',
    depthEx:'Exceeded expectations',depthGood:'Met needs',depthShallow:'Too shallow',depthPoor:'Insufficient',
    submitting:'Submitting…',submitOk:'Recorded ✓',cancellingMsg:'Cancelling…',cancelOk:'Cancelled',
    s_running:'Running',s_queued:'Queued',s_completed:'Completed',s_done:'Completed',
    s_failed:'Failed',s_cancelled:'Cancelled',s_pending_review:'Pending Review',
    hideDeep:'Hide detailed feedback',attachTip:'Attach file',composeTip:'New run',
    cancelConfirm:'Cancel this run?',redirectPrompt:'New direction or instruction:',
  },
};
const SHARED_LANG_KEY = 'd_lang';
const LEGACY_CONSOLE_LANG_KEY = 'c_lang';
function normLang(v){ return String(v||'').toLowerCase()==='en' ? 'en' : 'zh'; }
function readSharedLang(){
  return normLang(localStorage.getItem(SHARED_LANG_KEY) || localStorage.getItem(LEGACY_CONSOLE_LANG_KEY) || 'zh');
}
function writeSharedLang(v){
  const n = normLang(v);
  localStorage.setItem(SHARED_LANG_KEY, n);
  localStorage.setItem(LEGACY_CONSOLE_LANG_KEY, n);
  return n;
}
let lang = readSharedLang();
writeSharedLang(lang);
const t = k => D[lang][k] || D.zh[k] || k;

function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => el.textContent = t(el.dataset.i18n));
  document.querySelectorAll('[data-i18n-ph]').forEach(el => el.placeholder = t(el.dataset.i18nPh));
  document.getElementById('lang-btn').textContent = lang === 'zh' ? 'EN' : '中';
  document.querySelector('html').lang = lang;
  const ta = document.getElementById('compose-textarea');
  ta.placeholder = lang === 'zh' ? ta.dataset.phZh : ta.dataset.phEn;
  const dn = document.getElementById('deep-note');
  dn.placeholder = lang === 'zh' ? dn.dataset.phZh : dn.dataset.phEn;
  const an = document.getElementById('append-note');
  an.placeholder = lang === 'zh' ? an.dataset.phZh : an.dataset.phEn;
  document.getElementById('compose-btn').title = t('composeTip');
  document.getElementById('compose-attach-btn').title = t('attachTip');
  document.querySelectorAll('.q-choice').forEach(b => {
    b.textContent = lang === 'zh' ? b.dataset.zh : b.dataset.en;
  });
}
function toggleLang() {
  lang = writeSharedLang(lang === 'zh' ? 'en' : 'zh');
  applyI18n();
  renderNav();
}
window.addEventListener('storage', (event) => {
  if (event.key !== SHARED_LANG_KEY && event.key !== LEGACY_CONSOLE_LANG_KEY) return;
  const next = readSharedLang();
  if (next === lang) return;
  lang = next;
  applyI18n();
  renderNav();
});
