const portalState = {
  sidebar: { pending: [], live: [], folios: [], recent: [] },
  voiceSessionId: '',
  draftPlan: null,
  draftMessages: [],
  currentSlip: null,
  currentFolio: null,
  currentMessages: [],
  dragSlipSlug: '',
  ws: null,
  wsRetry: 0,
};

function rerenderPortal() {
  applyPortalI18n();
  renderSidebar();
  renderCurrentScreen();
}

function portalRoute() {
  const clean = location.pathname.replace(/^\/portal\/?/, '').replace(/\/+$/, '');
  if (!clean) return { kind: 'draft' };
  const parts = clean.split('/').filter(Boolean);
  if (parts[0] === 'slips' && parts[1]) return { kind: 'slip', slug: decodeURIComponent(parts.slice(1).join('/')) };
  if (parts[0] === 'folios' && parts[1]) return { kind: 'folio', slug: decodeURIComponent(parts.slice(1).join('/')) };
  return { kind: 'missing' };
}

function navigatePortal(path, replace) {
  const method = replace ? 'replaceState' : 'pushState';
  history[method]({}, '', path);
}

function openFreshDraft(replace) {
  portalState.currentSlip = null;
  portalState.currentFolio = null;
  portalState.currentMessages = [];
  portalState.draftPlan = null;
  portalState.voiceSessionId = '';
  portalState.draftMessages = [];
  navigatePortal('/portal/', !!replace);
  renderCurrentScreen();
}

async function loadSidebar() {
  portalState.sidebar = await api('/portal-api/sidebar').catch(() => ({ pending: [], live: [], folios: [], recent: [] }));
  renderSidebar();
}

function renderSidebar() {
  _renderSlipNavList('pending-list', portalState.sidebar.pending || []);
  _renderSlipNavList('live-list', portalState.sidebar.live || []);
  _renderSlipNavList('recent-slip-list', portalState.sidebar.recent || []);
  const folioList = document.getElementById('folio-list');
  const rows = Array.isArray(portalState.sidebar.folios) ? portalState.sidebar.folios : [];
  if (!rows.length) {
    folioList.innerHTML = `<div class="nav-empty">${esc(t('empty'))}</div>`;
    return;
  }
  folioList.innerHTML = rows.map((folio) => {
    const slips = Array.isArray(folio.recent_slips) ? folio.recent_slips : [];
    return `
      <div class="folio-nav-card" data-folio-slug="${esc(folio.slug || '')}" ondragover="folioDragOver(event)" ondrop="folioDrop(event,'${esc(folio.slug || '')}')">
        <button class="folio-nav-head${portalState.currentFolio?.slug === folio.slug ? ' active' : ''}" onclick="openFolioBySlug('${esc(folio.slug || '')}')">
          <span class="folio-nav-title">${esc(folio.title || '')}</span>
          <span class="folio-nav-meta">${esc(String(folio.slip_count || 0))}</span>
        </button>
        <div class="folio-nav-body">
          ${slips.map((slip) => renderSlipChip(slip)).join('')}
        </div>
      </div>
    `;
  }).join('');
}

function renderSlipChip(slip) {
  const deed = slip.deed || {};
  return `
    <button
      class="slip-chip${portalState.currentSlip?.slug === slip.slug ? ' active' : ''}"
      draggable="true"
      data-slip-slug="${esc(slip.slug || '')}"
      ondragstart="slipDragStart(event,'${esc(slip.slug || '')}')"
      ondragend="slipDragEnd()"
      onclick="openSlipBySlug('${esc(slip.slug || '')}')"
      ondragover="slipOnSlipDragOver(event)"
      ondrop="slipOnSlipDrop(event,'${esc(slip.slug || '')}')"
    >
      <span class="slip-chip-dot state-${esc(String(deed.status || 'muted'))}"></span>
      <span class="slip-chip-title">${esc(slip.title || '')}</span>
    </button>
  `;
}

function _renderSlipNavList(elementId, rows) {
  const root = document.getElementById(elementId);
  if (!rows.length) {
    root.innerHTML = `<div class="nav-empty">${esc(t('empty'))}</div>`;
    return;
  }
  root.innerHTML = rows.map((slip) => `
    <button
      class="nav-slip-row${portalState.currentSlip?.slug === slip.slug ? ' active' : ''}"
      draggable="true"
      data-slip-slug="${esc(slip.slug || '')}"
      ondragstart="slipDragStart(event,'${esc(slip.slug || '')}')"
      ondragend="slipDragEnd()"
      onclick="openSlipBySlug('${esc(slip.slug || '')}')"
      ondragover="slipOnSlipDragOver(event)"
      ondrop="slipOnSlipDrop(event,'${esc(slip.slug || '')}')"
    >
      <span class="nav-slip-title">${esc(slip.title || '')}</span>
      <span class="nav-slip-time">${esc(relativeTime(slip.updated_utc || slip.created_utc))}</span>
    </button>
  `).join('');
}

async function loadRoute(replace) {
  const route = portalRoute();
  if (route.kind === 'draft') {
    openFreshDraft(replace);
    return;
  }
  if (route.kind === 'slip') {
    await openSlipBySlug(route.slug, { replace });
    return;
  }
  if (route.kind === 'folio') {
    await openFolioBySlug(route.slug, { replace });
    return;
  }
  openFreshDraft(true);
  portalState.draftMessages = [{ role: 'system', content: t('routeMissing') }];
  renderCurrentScreen();
}

async function openSlipBySlug(slug, options) {
  if (!slug) return;
  portalState.currentFolio = null;
  portalState.currentSlip = null;
  portalState.currentMessages = [];
  renderCurrentScreen({ loading: 'slip' });
  const slip = await api('/portal-api/slips/' + encodeURIComponent(slug));
  const canonical = slip.canonical_slug || slip.slug || slug;
  navigatePortal('/portal/slips/' + encodeURIComponent(canonical), !!options?.replace);
  portalState.currentSlip = slip;
  portalState.currentFolio = null;
  portalState.currentMessages = await api('/portal-api/slips/' + encodeURIComponent(canonical) + '/messages?limit=300').catch(() => []);
  renderCurrentScreen();
}

async function openFolioBySlug(slug, options) {
  if (!slug) return;
  portalState.currentSlip = null;
  portalState.currentFolio = null;
  portalState.currentMessages = [];
  renderCurrentScreen({ loading: 'folio' });
  const folio = await api('/portal-api/folios/' + encodeURIComponent(slug));
  const canonical = folio.canonical_slug || folio.slug || slug;
  navigatePortal('/portal/folios/' + encodeURIComponent(canonical), !!options?.replace);
  portalState.currentFolio = folio;
  portalState.currentSlip = null;
  renderCurrentScreen();
}

function renderCurrentScreen(options) {
  const loading = options?.loading || '';
  const empty = document.getElementById('hero-empty');
  const folioScreen = document.getElementById('folio-screen');
  const slipScreen = document.getElementById('slip-screen');
  empty.classList.add('hidden');
  folioScreen.classList.add('hidden');
  slipScreen.classList.add('hidden');
  if (loading === 'slip') {
    slipScreen.classList.remove('hidden');
    document.getElementById('slip-shell').innerHTML = `<div class="loading-shell">${esc(t('loadingSlip'))}</div>`;
    document.getElementById('slip-messages').innerHTML = '';
    document.getElementById('slip-review').classList.add('hidden');
    document.getElementById('slip-result').classList.add('hidden');
    setComposerPlaceholder(t('slipInput'));
    return;
  }
  if (loading === 'folio') {
    folioScreen.classList.remove('hidden');
    document.getElementById('folio-shell').innerHTML = `<div class="loading-shell">${esc(t('loadingFolio'))}</div>`;
    setComposerPlaceholder(t('composePlaceholder'));
    return;
  }
  if (portalState.currentSlip) {
    slipScreen.classList.remove('hidden');
    renderSlipScreen();
    setComposerPlaceholder(t('slipInput'));
    return;
  }
  if (portalState.currentFolio) {
    folioScreen.classList.remove('hidden');
    renderFolioScreen();
    setComposerPlaceholder(t('composePlaceholder'));
    return;
  }
  empty.classList.remove('hidden');
  renderDraftScreen();
  setComposerPlaceholder(t('composePlaceholder'));
}

function renderDraftScreen() {
  document.getElementById('draft-chat').innerHTML = portalState.draftMessages.length
    ? portalState.draftMessages.map(renderMessageBubble).join('')
    : '';
  const card = document.getElementById('draft-card');
  if (!portalState.draftPlan) {
    card.classList.add('hidden');
    card.innerHTML = '';
    return;
  }
  const plan = portalState.draftPlan;
  const objective = String(plan.objective || plan.title || plan.intent || '');
  const timeline = _draftTimeline(plan);
  card.classList.remove('hidden');
  card.innerHTML = `
    <div class="draft-card">
      <div class="artifact-kicker">${esc(t('draftKicker'))}</div>
      <div class="artifact-title">${esc(t('draftTitle'))}</div>
      <div class="artifact-copy">${esc(objective || t('draftSummary'))}</div>
      <div class="artifact-note">${esc(t('draftSummary'))}</div>
      <div class="slip-timeline">
        ${timeline.map((step, index) => `
          <div class="slip-step pending">
            <span class="slip-step-dot">${index + 1}</span>
            <div class="slip-step-copy">
              <div class="slip-step-label">${esc(step.label)}</div>
            </div>
          </div>
        `).join('')}
      </div>
      <div class="draft-actions">
        <button class="primary-cta" onclick="submitDraftPlan()">${esc(t('crystallize'))}</button>
        <span class="draft-hint">${esc(t('reviseHint'))}</span>
      </div>
    </div>
  `;
}

function _draftTimeline(plan) {
  const display = plan.plan_display || {};
  const timeline = Array.isArray(display.timeline) ? display.timeline : [];
  if (timeline.length) {
    return timeline.map((step) => ({ label: String(step.label || step.instruction || '') }));
  }
  const moves = Array.isArray(plan.moves) ? plan.moves : [];
  return moves.map((move, index) => ({ label: String(move.instruction || move.message || move.title || `步骤 ${index + 1}`) }));
}

function renderSlipScreen() {
  const slip = portalState.currentSlip;
  const folio = slip.folio;
  const deed = slip.current_deed || {};
  const timeline = Array.isArray(slip.plan?.timeline) ? slip.plan.timeline : [];
  document.getElementById('slip-shell').innerHTML = `
    <div
      class="slip-hero"
      draggable="true"
      data-slip-slug="${esc(slip.slug || '')}"
      ondragstart="slipDragStart(event,'${esc(slip.slug || '')}')"
      ondragend="slipDragEnd()"
    >
      <div class="slip-hero-head">
        <div class="artifact-kicker">${esc(t('slip'))}</div>
        <div class="slip-statuses">
          <span class="meta-pill">${esc(slipStateLabel(slip.stance))}</span>
          <span class="meta-pill">${esc(deedStateLabel(deed.status))}</span>
          ${slip.standing ? `<span class="meta-pill">${esc(t('standingSlip'))}</span>` : ''}
        </div>
      </div>
      <div class="artifact-title">${esc(slip.title || '')}</div>
      <div class="artifact-copy">${esc(slip.objective || '')}</div>
      <div class="hero-meta">
        ${folio ? `<button class="ghost-link" onclick="openFolioBySlug('${esc(folio.slug || '')}')">${esc(folio.title || '')}</button>` : `<span class="hero-subtle">${esc(t('standaloneSlip'))}</span>`}
        ${deed.updated_utc ? `<span class="hero-subtle">${esc(relativeTime(deed.updated_utc))}</span>` : ''}
      </div>
      <div class="slip-timeline">
        ${timeline.map((step, index) => `
          <div class="slip-step ${_timelineStateClass(index, deed.status)}">
            <span class="slip-step-dot">${index + 1}</span>
            <div class="slip-step-copy">
              <div class="slip-step-label">${esc(step.label || '')}</div>
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `;
  document.getElementById('slip-messages').innerHTML = portalState.currentMessages.length
    ? portalState.currentMessages.map(renderMessageBubble).join('')
    : `<div class="empty-line">${esc(t('noMessages'))}</div>`;
  renderReviewBlock(slip);
  renderResultBlock(slip);
}

function _timelineStateClass(index, deedStatus) {
  const status = String(deedStatus || '').toLowerCase();
  if (['completed', 'awaiting_eval', 'cancelled'].includes(status)) return 'done';
  if (['running', 'paused', 'cancelling'].includes(status)) return index === 0 ? 'active' : 'pending';
  if (status === 'failed') return index === 0 ? 'failed' : 'pending';
  if (status === 'queued') return index === 0 ? 'next' : 'pending';
  return 'pending';
}

function renderFolioScreen() {
  const folio = portalState.currentFolio;
  const slips = Array.isArray(folio.slips) ? folio.slips : [];
  const writs = Array.isArray(folio.writs) ? folio.writs : [];
  const recentResults = Array.isArray(folio.recent_results) ? folio.recent_results : [];
  document.getElementById('folio-shell').innerHTML = `
    <div class="folio-hero" data-folio-slug="${esc(folio.slug || '')}" ondragover="folioDragOver(event)" ondrop="folioDrop(event,'${esc(folio.slug || '')}')">
      <div class="artifact-kicker">${esc(t('folio'))}</div>
      <div class="artifact-title">${esc(folio.title || '')}</div>
      <div class="artifact-copy">${esc(folio.summary || t('folioSummaryFallback'))}</div>
      <div class="hero-meta">
        <span class="meta-pill">${esc(slipStateLabel(folio.status))}</span>
        <span class="hero-subtle">${esc(String(folio.slip_count || 0))} ${esc(t('slip'))}</span>
        <span class="hero-subtle">${esc(String(folio.writ_count || 0))} ${esc(t('writ'))}</span>
      </div>
    </div>
    <div class="folio-map-block">
      <div class="section-title">${esc(t('folioMapTitle'))}</div>
      <div class="section-copy">${esc(t('folioMapHint'))}</div>
      <div class="writ-lanes">
        ${writs.length ? writs.map(renderWritLane).join('') : `<div class="empty-line">${esc(t('empty'))}</div>`}
      </div>
    </div>
    <div class="folio-slip-grid">
      ${slips.length ? slips.map((slip) => renderFolioSlipCard(slip)).join('') : `<div class="empty-line">${esc(t('noSlips'))}</div>`}
    </div>
    <div class="folio-results-block">
      <div class="section-title">${esc(t('folioResultsTitle'))}</div>
      <div class="section-copy">${esc(t('folioResultsHint'))}</div>
      <div class="folio-result-list">
        ${recentResults.length ? recentResults.map(renderFolioResultRow).join('') : `<div class="empty-line">${esc(t('folioResultsEmpty'))}</div>`}
      </div>
    </div>
  `;
}

function renderWritLane(writ) {
  const recent = Array.isArray(writ.recent_deeds) ? writ.recent_deeds : [];
  return `
    <div class="writ-lane">
      <div class="writ-lane-head">
        <div class="writ-title">${esc(writ.title || '')}</div>
        <span class="meta-pill">${esc(writ.status || '')}</span>
      </div>
      <div class="writ-sub">${writ.last_triggered_utc ? esc(relativeTime(writ.last_triggered_utc)) : esc(t('empty'))}</div>
      <div class="writ-chip-row">
        ${recent.map((row) => `<span class="writ-chip">${esc(row.title || row.deed_id || '')}</span>`).join('')}
      </div>
    </div>
  `;
}

function renderFolioSlipCard(slip) {
  const deed = slip.deed || {};
  return `
    <button
      class="folio-slip-card"
      draggable="true"
      data-slip-slug="${esc(slip.slug || '')}"
      onclick="openSlipBySlug('${esc(slip.slug || '')}')"
      ondragstart="slipDragStart(event,'${esc(slip.slug || '')}')"
      ondragend="slipDragEnd()"
      ondragover="slipOnSlipDragOver(event)"
      ondrop="slipOnSlipDrop(event,'${esc(slip.slug || '')}')"
    >
      <div class="folio-slip-top">
        <span class="slip-chip-dot state-${esc(String(deed.status || 'muted'))}"></span>
        <span class="folio-slip-time">${esc(relativeTime(slip.updated_utc || ''))}</span>
      </div>
      <div class="folio-slip-title">${esc(slip.title || '')}</div>
      <div class="folio-slip-copy">${esc(slip.objective || '')}</div>
    </button>
  `;
}

function renderFolioResultRow(result) {
  return `
    <button class="folio-result-row" onclick="openSlipBySlug('${esc(result.slip_slug || '')}')">
      <div class="folio-result-main">
        <div class="folio-result-title">${esc(result.title || result.slip_title || '')}</div>
        <div class="folio-result-sub">${esc(result.slip_title || '')}</div>
      </div>
      <div class="folio-result-meta">${esc(relativeTime(result.updated_utc || ''))}</div>
    </button>
  `;
}

function renderMessageBubble(message) {
  const role = String(message.role || '').toLowerCase();
  const cls = role === 'user' ? 'user' : role === 'assistant' ? 'assistant' : 'system';
  return `<div class="bubble ${cls}">${cls === 'assistant' ? md(message.content || '') : esc(message.content || '')}</div>`;
}

function renderReviewBlock(slip) {
  const review = document.getElementById('slip-review');
  const state = slip.feedback || {};
  const deedStatus = String(slip.current_deed?.status || '').toLowerCase();
  if (!['awaiting_eval', 'completed'].includes(deedStatus)) {
    review.classList.add('hidden');
    review.innerHTML = '';
    return;
  }
  const response = state.response || {};
  const submitted = String(state.status || '').toLowerCase() === 'submitted' || response.rating != null;
  review.classList.remove('hidden');
  review.innerHTML = `
    <div class="review-card">
      <div class="section-title">${esc(t('reviewAsk'))}</div>
      <div class="review-choices ${submitted ? 'submitted' : ''}">
        ${['satisfactory', 'acceptable', 'unsatisfactory', 'wrong'].map((key) => `
          <button class="review-choice${String(response.choice || '') === key ? ' active' : ''}" onclick="chooseReview('${key}')">${esc(t('reviewChoice_' + key))}</button>
        `).join('')}
      </div>
      <div class="review-issues">
        ${['missing_info', 'depth_insufficient', 'factual_error', 'format_issue', 'wrong_direction'].map((key) => `
          <label><input type="checkbox" value="${esc(key)}" ${Array.isArray(response.issues) && response.issues.includes(key) ? 'checked' : ''}><span>${esc(t('reviewIssue_' + key))}</span></label>
        `).join('')}
      </div>
      <textarea id="review-comment" placeholder="${esc(t('reviewCommentPlaceholder'))}">${esc(response.comment || '')}</textarea>
      <div class="review-actions">
        <button class="primary-cta" onclick="submitReview()">${esc(submitted ? t('reviewAppend') : t('reviewSubmit'))}</button>
        <span id="review-status">${submitted ? esc(t('reviewSent')) : ''}</span>
      </div>
    </div>
  `;
}

function renderResultBlock(slip) {
  const root = document.getElementById('slip-result');
  if (!slip.result_ready) {
    root.classList.add('hidden');
    root.innerHTML = '';
    return;
  }
  root.classList.remove('hidden');
  root.innerHTML = `<div class="result-card"><div class="section-title">${esc(t('deed'))}</div><div id="result-files" class="result-files"><div class="empty-line">${esc(t('loadingSlip'))}</div></div></div>`;
  api('/portal-api/slips/' + encodeURIComponent(slip.slug) + '/result/files').then((payload) => {
    const rows = Array.isArray(payload.files) ? payload.files : [];
    document.getElementById('result-files').innerHTML = rows.length
      ? rows.map((row) => `<a class="result-file" href="${esc(row.download || '')}" target="_blank" rel="noreferrer">${esc(row.name || row.relative_path || '')}</a>`).join('')
      : `<div class="empty-line">${esc(t('resultEmpty'))}</div>`;
  }).catch(() => {
    document.getElementById('result-files').innerHTML = `<div class="empty-line">${esc(t('resultEmpty'))}</div>`;
  });
}

function setComposerPlaceholder(text) {
  const input = document.getElementById('composer-input');
  input.placeholder = text;
}

async function portalSend() {
  const input = document.getElementById('composer-input');
  const button = document.getElementById('composer-send');
  const text = String(input.value || '').trim();
  if (!text) return;
  input.value = '';
  autoResize(input);
  button.disabled = true;
  try {
    if (portalState.currentSlip?.slug) {
      portalState.currentMessages.push({ role: 'user', content: text });
      renderSlipScreen();
      await api('/portal-api/slips/' + encodeURIComponent(portalState.currentSlip.slug) + '/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      await openSlipBySlug(portalState.currentSlip.slug, { replace: true });
    } else {
      portalState.draftMessages.push({ role: 'user', content: text });
      renderDraftScreen();
      if (!portalState.voiceSessionId) {
        const session = await api('/voice/session', { method: 'POST' });
        portalState.voiceSessionId = session.session_id;
      }
      const data = await api('/voice/' + encodeURIComponent(portalState.voiceSessionId), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      if (data.content) portalState.draftMessages.push({ role: 'assistant', content: data.content });
      if (data.plan) portalState.draftPlan = data.plan;
      renderDraftScreen();
    }
  } catch (error) {
    if (portalState.currentSlip) {
      portalState.currentMessages.push({ role: 'system', content: String(error.message || t('genericError')) });
      renderSlipScreen();
    } else {
      portalState.draftMessages.push({ role: 'system', content: String(error.message || t('genericError')) });
      renderDraftScreen();
    }
  } finally {
    button.disabled = false;
    input.focus();
  }
}

async function submitDraftPlan() {
  if (!portalState.draftPlan) return;
  try {
    const result = await api('/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(portalState.draftPlan),
    });
    portalState.draftPlan = null;
    portalState.voiceSessionId = '';
    await loadSidebar();
    const lookup = await api('/portal-api/slips/by-deed/' + encodeURIComponent(result.deed_id || result.id || ''));
    if (lookup.slug) {
      await openSlipBySlug(lookup.slug);
    }
  } catch (error) {
    portalState.draftMessages.push({ role: 'system', content: String(error.message || t('genericError')) });
    renderDraftScreen();
  }
}

let reviewChoice = '';

function chooseReview(choice) {
  reviewChoice = choice;
  document.querySelectorAll('.review-choice').forEach((element) => {
    element.classList.toggle('active', element.textContent === t('reviewChoice_' + choice));
  });
}

async function submitReview() {
  if (!portalState.currentSlip?.slug) return;
  const comment = String(document.getElementById('review-comment')?.value || '').trim();
  const issues = Array.from(document.querySelectorAll('.review-issues input:checked')).map((input) => input.value);
  const payload = { source: 'portal' };
  if (reviewChoice) {
    payload.choice = reviewChoice;
    payload.rating = { satisfactory: 5, acceptable: 4, unsatisfactory: 2, wrong: 1 }[reviewChoice] || 3;
  }
  if (issues.length) payload.issues = issues;
  if (comment) payload.comment = comment;
  try {
    await api('/portal-api/slips/' + encodeURIComponent(portalState.currentSlip.slug) + '/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    document.getElementById('review-status').textContent = t('reviewSent');
    await openSlipBySlug(portalState.currentSlip.slug, { replace: true });
    await loadSidebar();
  } catch (error) {
    document.getElementById('review-status').textContent = String(error.message || t('genericError'));
  }
}

function relativeTime(value) {
  const raw = String(value || '').trim();
  if (!raw) return '—';
  const parsed = Date.parse(raw.includes('T') ? raw : raw.replace(' ', 'T') + 'Z');
  if (!Number.isFinite(parsed)) return '—';
  let diff = Math.floor((Date.now() - parsed) / 1000);
  if (diff < 0) diff = 0;
  if (diff < 60) return '<1m';
  if (diff < 3600) return Math.floor(diff / 60) + 'm';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h';
  return Math.floor(diff / 86400) + 'd';
}

function slipDragStart(event, slipSlug) {
  portalState.dragSlipSlug = slipSlug;
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', slipSlug);
  document.getElementById('drag-dock').classList.remove('hidden');
}

function slipDragEnd() {
  portalState.dragSlipSlug = '';
  document.getElementById('drag-dock').classList.add('hidden');
  document.querySelectorAll('.drag-over').forEach((element) => element.classList.remove('drag-over'));
}

function folioDragOver(event) {
  event.preventDefault();
  event.currentTarget.classList.add('drag-over');
}

async function folioDrop(event, folioSlug) {
  event.preventDefault();
  event.currentTarget.classList.remove('drag-over');
  const slipSlug = portalState.dragSlipSlug || event.dataTransfer.getData('text/plain');
  if (!slipSlug || !folioSlug) return;
  await api('/portal-api/folios/' + encodeURIComponent(folioSlug) + '/adopt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slip_slug: slipSlug }),
  });
  slipDragEnd();
  await Promise.all([loadSidebar(), openFolioBySlug(folioSlug, { replace: true })]);
}

function slipOnSlipDragOver(event) {
  event.preventDefault();
  event.currentTarget.classList.add('drag-over');
}

async function slipOnSlipDrop(event, targetSlug) {
  event.preventDefault();
  event.currentTarget.classList.remove('drag-over');
  const sourceSlug = portalState.dragSlipSlug || event.dataTransfer.getData('text/plain');
  if (!sourceSlug || !targetSlug || sourceSlug === targetSlug) return;
  const result = await api('/portal-api/folios/from-slips', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_slug: sourceSlug, target_slug: targetSlug }),
  });
  slipDragEnd();
  await loadSidebar();
  if (result.folio?.slug) {
    await openFolioBySlug(result.folio.slug);
  }
}

document.addEventListener('dragover', (event) => {
  const zone = event.target.closest('.dock-zone');
  if (zone) {
    event.preventDefault();
    zone.classList.add('drag-over');
  }
});

document.addEventListener('dragleave', (event) => {
  const zone = event.target.closest('.dock-zone');
  if (zone) zone.classList.remove('drag-over');
});

document.addEventListener('drop', async (event) => {
  const zone = event.target.closest('.dock-zone');
  if (!zone) return;
  event.preventDefault();
  const slipSlug = portalState.dragSlipSlug || event.dataTransfer.getData('text/plain');
  const target = zone.dataset.target;
  zone.classList.remove('drag-over');
  if (!slipSlug || !target) return;
  await api('/portal-api/slips/' + encodeURIComponent(slipSlug) + '/stance', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target }),
  });
  slipDragEnd();
  await loadSidebar();
  if (portalState.currentSlip?.slug === slipSlug) {
    await openSlipBySlug(slipSlug, { replace: true });
  }
});

function connectPortalWs() {
  if (portalState.ws && (portalState.ws.readyState === WebSocket.OPEN || portalState.ws.readyState === WebSocket.CONNECTING)) return;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = proto + '//' + location.host + '/ws';
  try {
    portalState.ws = new WebSocket(url);
  } catch (_) {
    schedulePortalWsRetry();
    return;
  }
  portalState.ws.onopen = () => {
    portalState.wsRetry = 0;
  };
  portalState.ws.onmessage = async (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (_) {
      return;
    }
    const name = String(message.event || '');
    if (name === 'ping') {
      try { portalState.ws.send('ping'); } catch (_) {}
      return;
    }
    if (name === 'connected' || name === 'pong') return;
    if (['deed_completed', 'deed_failed', 'deed_message', 'deed_progress', 'eval_expiring'].includes(name)) {
      await loadSidebar();
      if (portalState.currentSlip?.slug) {
        await openSlipBySlug(portalState.currentSlip.slug, { replace: true });
      }
    }
  };
  portalState.ws.onclose = () => schedulePortalWsRetry();
  portalState.ws.onerror = () => {
    try { portalState.ws.close(); } catch (_) {}
  };
}

function schedulePortalWsRetry() {
  if (portalState.wsRetry >= 8) return;
  const delay = Math.min(1000 * (2 ** portalState.wsRetry), 30000);
  portalState.wsRetry += 1;
  setTimeout(connectPortalWs, delay);
}

async function bootPortal() {
  applyPortalI18n();
  setComposerPlaceholder(t('composePlaceholder'));
  await loadSidebar();
  await loadRoute(true);
  connectPortalWs();
  setInterval(() => {
    loadSidebar().catch(() => {});
  }, 30000);
}

document.addEventListener('DOMContentLoaded', bootPortal);
window.addEventListener('popstate', () => { loadRoute(true); });
