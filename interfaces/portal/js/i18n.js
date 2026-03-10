const DICT = {
  zh: {
    brand: 'Daemon',
    pending: '待你阅看',
    live: '正在行事',
    folios: '卷',
    recentSlips: '近来离散签札',
    empty: '暂无',
    composeTitle: '你要让我办什么事？',
    composeHint: '先说出目标。我会把它收敛成一张草稿，确认后落札行事。',
    composePlaceholder: '写下目标、背景或你想推进的方向…',
    send: '送出',
    draftKicker: '草稿',
    draftTitle: '已经成形，可以落札',
    draftSummary: '若方向无误，我会将这份草稿落成签札，并据此生出第一次行事；若要改，直接继续说。',
    crystallize: '落札并行',
    reviseHint: '若要改，直接继续说。',
    slip: '签札',
    folio: '卷',
    writ: '成文',
    deed: '行事',
    slipState_active: '续办中',
    slipState_parked: '已搁置',
    slipState_settled: '已收束',
    slipState_archived: '已收起',
    slipState_absorbed: '已并入',
    deedState_running: '正在行事',
    deedState_queued: '待行',
    deedState_paused: '已停驻',
    deedState_cancelling: '正在收束',
    deedState_awaiting_eval: '待你阅看',
    deedState_completed: '已做成',
    deedState_cancelled: '已止住',
    deedState_failed: '未做成',
    deedState_failed_submission: '未能起行',
    deedState_replay_exhausted: '再行用尽',
    status_unknown: '未定',
    openFolio: '开卷',
    openSlip: '开札',
    backToFolio: '回到卷页',
    resultEmpty: '这一札还没有正式成品。',
    reviewAsk: '这一回行事已经送达。你怎么看？',
    reviewSubmit: '交回评语',
    reviewAppend: '续写评语',
    reviewSent: '已收下',
    reviewExpired: '这回行事已经封存，不能再补评。',
    reviewIssue_missing_info: '关键信息缺失',
    reviewIssue_depth_insufficient: '分析深度不足',
    reviewIssue_factual_error: '存在事实错误',
    reviewIssue_format_issue: '格式或排版不妥',
    reviewIssue_wrong_direction: '方向偏离原意',
    reviewChoice_satisfactory: '符合预期',
    reviewChoice_acceptable: '基本达标',
    reviewChoice_unsatisfactory: '明显不足',
    reviewChoice_wrong: '方向不对',
    reviewCommentPlaceholder: '补写一段说明…',
    slipInput: '继续补写这张签札的方向、约束或修订…',
    routeMissing: '没有找到这张签札或这卷。',
    genericError: '出了点问题，请稍后再试。',
    dockContinue: '续办',
    dockPark: '搁置',
    dockArchive: '收起',
    dockHint: '拖动签札，到下方改变它的去向与姿态。',
    folioMapTitle: '卷中脉络',
    folioMapHint: '把签札拖进这卷，或把签札拖到另一张签札上，让系统自动开卷。',
    folioResultsTitle: '最近结果',
    folioResultsHint: '近来在这卷里送达的成品，会在这里收拢。',
    folioResultsEmpty: '这卷还没有送达的结果。',
    folioSummaryFallback: '这卷还没有写下摘要。',
    standaloneSlip: '未入卷',
    standingSlip: '常札',
    currentDeed: '当前行事',
    deedHistory: '历次行事',
    noMessages: '这一札还没有消息。',
    noFolios: '眼下还没有卷。',
    noSlips: '眼下还没有签札。',
    loadingSlip: '正在展开签札…',
    loadingFolio: '正在展开卷…',
    loadingSidebar: '正在整理案桌…',
    linkConsole: 'Console',
    newDraft: '新草稿',
  },
  en: {
    brand: 'Daemon',
    pending: 'Needs You',
    live: 'In Motion',
    folios: 'Folios',
    recentSlips: 'Recent Loose Slips',
    empty: 'None',
    composeTitle: 'What should I take up?',
    composeHint: 'State the objective first. I will condense it into a draft, then crystallize it into a slip when you confirm.',
    composePlaceholder: 'Write the goal, context, or the direction you want to advance…',
    send: 'Send',
    draftKicker: 'Draft',
    draftTitle: 'Formed and ready to crystallize',
    draftSummary: 'If the direction is right, I will crystallize this draft into a slip and let it give rise to the first deed. If not, keep talking.',
    crystallize: 'Crystallize and Begin',
    reviseHint: 'If you want changes, just keep talking.',
    slip: 'Slip',
    folio: 'Folio',
    writ: 'Writ',
    deed: 'Deed',
    slipState_active: 'Active',
    slipState_parked: 'Parked',
    slipState_settled: 'Settled',
    slipState_archived: 'Archived',
    slipState_absorbed: 'Absorbed',
    deedState_running: 'Running',
    deedState_queued: 'Queued',
    deedState_paused: 'Paused',
    deedState_cancelling: 'Stopping',
    deedState_awaiting_eval: 'Needs Review',
    deedState_completed: 'Completed',
    deedState_cancelled: 'Cancelled',
    deedState_failed: 'Failed',
    deedState_failed_submission: 'Could Not Start',
    deedState_replay_exhausted: 'Retries Exhausted',
    status_unknown: 'Unknown',
    openFolio: 'Open Folio',
    openSlip: 'Open Slip',
    backToFolio: 'Back to folio',
    resultEmpty: 'No formal artifact yet.',
    reviewAsk: 'This deed has landed. How did it go?',
    reviewSubmit: 'Submit Review',
    reviewAppend: 'Add Note',
    reviewSent: 'Recorded',
    reviewExpired: 'This deed has been archived and no longer accepts review.',
    reviewIssue_missing_info: 'Missing key information',
    reviewIssue_depth_insufficient: 'Not deep enough',
    reviewIssue_factual_error: 'Contains factual errors',
    reviewIssue_format_issue: 'Formatting issues',
    reviewIssue_wrong_direction: 'Went in the wrong direction',
    reviewChoice_satisfactory: 'Met expectations',
    reviewChoice_acceptable: 'Acceptable',
    reviewChoice_unsatisfactory: 'Below expectations',
    reviewChoice_wrong: 'Wrong direction',
    reviewCommentPlaceholder: 'Add a note…',
    slipInput: 'Add direction, constraints, or revisions to this slip…',
    routeMissing: 'That slip or folio could not be found.',
    genericError: 'Something went wrong. Please try again shortly.',
    dockContinue: 'Continue',
    dockPark: 'Park',
    dockArchive: 'Archive',
    dockHint: 'Drag a slip to the dock to change its posture or placement.',
    folioMapTitle: 'Folio Threads',
    folioMapHint: 'Drop slips into this folio, or onto another slip to open a new folio automatically.',
    folioResultsTitle: 'Recent Results',
    folioResultsHint: 'Recent completed artifacts in this folio gather here.',
    folioResultsEmpty: 'No delivered artifacts in this folio yet.',
    folioSummaryFallback: 'No summary has been written for this folio yet.',
    standaloneSlip: 'Loose slip',
    standingSlip: 'Standing slip',
    currentDeed: 'Current deed',
    deedHistory: 'Deed history',
    noMessages: 'No messages yet.',
    noFolios: 'No folios yet.',
    noSlips: 'No slips yet.',
    loadingSlip: 'Opening slip…',
    loadingFolio: 'Opening folio…',
    loadingSidebar: 'Setting the desk…',
    linkConsole: 'Console',
    newDraft: 'New Draft',
  },
};

const SHARED_LANG_KEY = 'd_lang';
const LEGACY_CONSOLE_LANG_KEY = 'c_lang';

function normLang(value) {
  return String(value || '').toLowerCase() === 'en' ? 'en' : 'zh';
}

function readSharedLang() {
  return normLang(localStorage.getItem(SHARED_LANG_KEY) || localStorage.getItem(LEGACY_CONSOLE_LANG_KEY) || 'zh');
}

function writeSharedLang(value) {
  const next = normLang(value);
  localStorage.setItem(SHARED_LANG_KEY, next);
  localStorage.setItem(LEGACY_CONSOLE_LANG_KEY, next);
  return next;
}

let lang = readSharedLang();
writeSharedLang(lang);

function t(key) {
  return DICT[lang]?.[key] || DICT.zh[key] || key;
}

function slipStateLabel(value) {
  return t('slipState_' + String(value || '').replace(/-/g, '_')) || t('status_unknown');
}

function deedStateLabel(value) {
  return t('deedState_' + String(value || '').replace(/-/g, '_')) || t('status_unknown');
}

function applyPortalI18n() {
  document.documentElement.lang = lang;
  document.title = 'Daemon';
  const langBtn = document.getElementById('lang-btn');
  if (langBtn) langBtn.textContent = lang === 'zh' ? 'EN' : '中';
  const consoleLink = document.getElementById('console-link');
  if (consoleLink) consoleLink.textContent = t('linkConsole');
  document.querySelectorAll('[data-i18n]').forEach((element) => {
    element.textContent = t(element.dataset.i18n);
  });
}

function toggleLang() {
  lang = writeSharedLang(lang === 'zh' ? 'en' : 'zh');
  applyPortalI18n();
  if (typeof rerenderPortal === 'function') rerenderPortal();
}

window.addEventListener('storage', (event) => {
  if (event.key !== SHARED_LANG_KEY && event.key !== LEGACY_CONSOLE_LANG_KEY) return;
  const next = readSharedLang();
  if (next === lang) return;
  lang = next;
  applyPortalI18n();
  if (typeof rerenderPortal === 'function') rerenderPortal();
});
