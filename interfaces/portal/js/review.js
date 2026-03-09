// ── Feedback: 4-level inline selection (INTERACTION_DESIGN §1.6) ──────
let _fbChoice = null;
let _fbDeedId = null;

function showFeedbackInline(deedId) {
  _fbDeedId = deedId;
  _fbChoice = null;
  const wrap = document.getElementById('fb-inline');
  wrap.classList.remove('hidden');

  // Reset state
  const choices = document.getElementById('fb-choices');
  choices.style.display = '';
  document.querySelectorAll('.fb-choice').forEach(b => b.classList.remove('sel'));
  document.getElementById('fb-issues').classList.add('hidden');
  document.getElementById('fb-comment-wrap').classList.add('hidden');
  document.getElementById('fb-actions').classList.add('hidden');
  document.getElementById('fb-status').textContent = '';
  document.getElementById('fb-status').className = '';
  const comment = document.getElementById('fb-comment');
  if (comment) comment.value = '';
  document.querySelectorAll('#fb-issues input[type=checkbox]').forEach(cb => { cb.checked = false; });

  // Apply i18n
  document.getElementById('fb-ask').textContent = t('fbAsk');
  document.querySelectorAll('.fb-choice').forEach(b => {
    b.textContent = t('fb' + b.dataset.v.charAt(0).toUpperCase() + b.dataset.v.slice(1));
  });

  // Check if already submitted
  _loadFeedbackState(deedId);

  // T5: slide in animation
  wrap.classList.add('entering');
  setTimeout(() => { wrap.classList.remove('entering'); wrap.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, 400);
}

async function _loadFeedbackState(deedId) {
  let state = {};
  try { state = await api('/feedback/' + encodeURIComponent(deedId) + '/state'); } catch (_) {}
  const response = (state && state.response) || {};
  const submitted = String((state && state.status) || '').toLowerCase() === 'submitted';
  const hasMain = submitted || (response && response.rating != null && response.rating !== '');

  if (hasMain) {
    document.getElementById('fb-choices').style.display = 'none';
    document.getElementById('fb-issues').classList.add('hidden');
    document.getElementById('fb-ask').textContent = t('fbSubmitted');
    document.getElementById('fb-comment-wrap').classList.remove('hidden');
    document.getElementById('fb-comment').placeholder = lang === 'zh' ? '补充评价…' : 'Add follow-up…';
    document.getElementById('fb-actions').classList.remove('hidden');
    const btn = document.getElementById('fb-submit-btn');
    btn.textContent = t('appendSubmit');
    btn.onclick = submitFeedbackAppend;
  }
}

// §1.6: "离开 = 反馈已提交（选择部分）" — auto-save on selection
async function pickFeedback(el) {
  document.querySelectorAll('.fb-choice').forEach(b => b.classList.remove('sel'));
  el.classList.add('sel');
  _fbChoice = el.dataset.v;

  // Auto-save selection immediately
  _autoSaveFeedback();

  // Show issues for unsatisfactory/wrong
  const showIssues = _fbChoice === 'unsatisfactory' || _fbChoice === 'wrong';
  document.getElementById('fb-issues').classList.toggle('hidden', !showIssues);

  // Show follow-up: "还有什么想说的吗？"
  document.getElementById('fb-comment-wrap').classList.remove('hidden');
  document.getElementById('fb-actions').classList.remove('hidden');
  const btn = document.getElementById('fb-submit-btn');
  btn.textContent = t('submitRating');
  btn.onclick = submitFeedbackFollowUp;
  btn.disabled = false;
}

async function _autoSaveFeedback() {
  if (!_fbDeedId || !_fbChoice) return;
  try {
    await api('/deeds/' + encodeURIComponent(_fbDeedId) + '/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source: 'portal',
        rating: _fbRatingMap[_fbChoice] || 3,
        choice: _fbChoice,
        type: 'quick',
      }),
    });
  } catch (_) {}
}

function refreshFbSubmit() {}

const _fbRatingMap = { satisfactory: 5, acceptable: 4, unsatisfactory: 2, wrong: 1 };

// Follow-up: overwrites auto-save with full data (§1.7: "新反馈覆盖旧反馈")
async function submitFeedbackFollowUp() {
  if (!_fbDeedId || !_fbChoice) return;
  const btn = document.getElementById('fb-submit-btn');
  const st = document.getElementById('fb-status');
  btn.disabled = true; st.textContent = t('submitting');

  const comment = (document.getElementById('fb-comment').value || '').trim();
  const issues = [];
  document.querySelectorAll('#fb-issues input[type=checkbox]:checked').forEach(cb => {
    issues.push(cb.value);
  });

  const payload = {
    source: 'portal',
    rating: _fbRatingMap[_fbChoice] || 3,
    choice: _fbChoice,
    type: (comment || issues.length) ? 'deep' : 'quick',
  };
  if (comment) payload.comment = comment;
  if (issues.length) payload.issues = issues;

  try {
    await api('/deeds/' + encodeURIComponent(_fbDeedId) + '/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    st.textContent = t('fbSubmitted');
    st.className = 'ok';
    document.getElementById('fb-choices').style.display = 'none';
    document.getElementById('fb-issues').classList.add('hidden');
    document.getElementById('fb-ask').textContent = t('fbSubmitted');
    btn.textContent = t('appendSubmit');
    btn.onclick = submitFeedbackAppend;
    btn.disabled = false;
    document.getElementById('fb-comment').value = '';
    setTimeout(renderNav, 500);
  } catch (e) {
    st.textContent = 'Error: ' + e.message;
    btn.disabled = false;
  }
}

async function submitFeedbackAppend() {
  if (!_fbDeedId) return;
  const comment = (document.getElementById('fb-comment').value || '').trim();
  if (!comment) return;
  const btn = document.getElementById('fb-submit-btn');
  const st = document.getElementById('fb-status');
  btn.disabled = true; st.textContent = t('submitting');

  try {
    await api('/deeds/' + encodeURIComponent(_fbDeedId) + '/feedback/append', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ comment, source: 'portal' }),
    });
    st.textContent = t('fbSubmitted');
    st.className = 'ok';
    document.getElementById('fb-comment').value = '';
  } catch (e) {
    st.textContent = 'Error: ' + e.message;
  }
  btn.disabled = false;
}
