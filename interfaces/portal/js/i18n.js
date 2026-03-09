// ── i18n ──────────────────────────────────────────────────
const D = {
  zh:{
    pending:'待处理',running:'进行中',history:'历史',none:'暂无',
    composeTitle:'需要做什么？',composeHint:'描述你的目标。',
    planDetected:'检测到运行计划',submitPlan:'确认提交',rewrite:'重新描述',
    send:'发送',pause:'暂停',resume:'继续',redirect:'调整方向',cancel:'取消运行',
    retry:'重新执行',
    passages:'阶段进度',
    // §1.6 feedback: 4-level inline selection
    fbAsk:'做好了，想听听你的想法。',
    fbSatisfactory:'符合预期，质量满意',
    fbAcceptable:'基本达标，尚可接受',
    fbUnsatisfactory:'未达预期，存在明显问题',
    fbWrong:'方向偏离，需要重新审视',
    fbFollowUp:'还有什么想说的吗？',
    fbIssueMissing:'关键信息缺失',
    fbIssueDepth:'分析深度不足',
    fbIssueFactual:'存在事实性错误',
    fbIssueFormat:'格式或排版不当',
    fbIssueDirection:'偏离了原始需求方向',
    fbCommentPh:'写一段评价…',
    fbSubmitted:'已记录 ✓',
    fbExpired:'反馈期已结束',
    viewResult:'查看完整结果',
    // legacy compat
    rateTitle:'这个结果怎么样？',submitRating:'提交评价',deepFeedback:'详细评价',
    appendTitle:'追加评价',appendSubmit:'提交追加评价',
    title:'标题',status:'状态',lastTriggered:'上次触发',count:'次数',actions:'操作',
    commentPh:'可选：写一句评价…',
    submitting:'提交中…',submitOk:'已记录 ✓',cancellingMsg:'取消中…',cancelOk:'已取消',
    s_running:'进行中',s_queued:'排队中',s_paused:'已暂停',s_cancelling:'取消中',s_awaiting_eval:'待评价',s_completed:'已完成',s_done:'已完成',
    s_failed:'失败',s_cancelled:'已取消',s_pending_review:'待评价',
    hideDeep:'收起详细评价',attachTip:'添加附件',composeTip:'新建对话',
    cancelConfirm:'确认取消这个任务？',redirectPrompt:'新的方向或补充说明：',
    chatPlaceholder:'随时说点什么…',
    newChat:'新建对话',
    noMessages:'暂无消息',
  },
  en:{
    pending:'Pending',running:'Running',history:'History',none:'None',
    composeTitle:'What do you need?',composeHint:'Describe your objective.',
    planDetected:'Plan detected',submitPlan:'Submit',rewrite:'Rewrite',
    send:'Send',pause:'Pause',resume:'Resume',redirect:'Redirect',cancel:'Cancel',
    retry:'Retry',
    passages:'Stage Progress',
    // §1.6 feedback: 4-level inline selection
    fbAsk:'Done — I\'d love to hear what you think.',
    fbSatisfactory:'Met expectations, quality satisfactory',
    fbAcceptable:'Adequate, acceptable',
    fbUnsatisfactory:'Below expectations, notable issues',
    fbWrong:'Off direction, needs rethinking',
    fbFollowUp:'Anything else you\'d like to say?',
    fbIssueMissing:'Key information missing',
    fbIssueDepth:'Analysis depth insufficient',
    fbIssueFactual:'Factual errors present',
    fbIssueFormat:'Formatting issues',
    fbIssueDirection:'Deviated from original request',
    fbCommentPh:'Write a comment…',
    fbSubmitted:'Recorded ✓',
    fbExpired:'Feedback period ended',
    viewResult:'View full result',
    // legacy compat
    rateTitle:'How was this result?',submitRating:'Submit Rating',deepFeedback:'Detailed Feedback',
    appendTitle:'Additional Feedback',appendSubmit:'Submit Follow-up',
    title:'Title',status:'Status',lastTriggered:'Last Triggered',count:'Count',actions:'Actions',
    commentPh:'Optional: add a comment…',
    submitting:'Submitting…',submitOk:'Recorded ✓',cancellingMsg:'Cancelling…',cancelOk:'Cancelled',
    s_running:'Running',s_queued:'Queued',s_paused:'Paused',s_cancelling:'Cancelling',s_awaiting_eval:'Awaiting Review',s_completed:'Completed',s_done:'Completed',
    s_failed:'Failed',s_cancelled:'Cancelled',s_pending_review:'Pending Review',
    hideDeep:'Hide detailed feedback',attachTip:'Attach file',composeTip:'New conversation',
    cancelConfirm:'Cancel this task?',redirectPrompt:'New direction or instruction:',
    chatPlaceholder:'Say something anytime…',
    newChat:'New conversation',
    noMessages:'No messages',
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
  if (ta) ta.placeholder = lang === 'zh' ? ta.dataset.phZh : ta.dataset.phEn;
  document.getElementById('compose-btn').title = t('composeTip');
  const ab = document.getElementById('compose-attach-btn');
  if (ab) ab.title = t('attachTip');
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
