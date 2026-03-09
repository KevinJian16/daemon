// ── WebSocket ─────────────────────────────────────────────
let _ws = null;
let _wsRetry = 0;
const _wsMaxRetry = 8;
const _wsHandlers = {};

function wsOn(event, fn) {
  if (!_wsHandlers[event]) _wsHandlers[event] = [];
  _wsHandlers[event].push(fn);
}

function _wsDispatch(event, payload) {
  const fns = _wsHandlers[event];
  if (fns) fns.forEach(fn => { try { fn(payload); } catch (e) { console.warn('ws handler error:', e); } });
}

function wsConnect() {
  if (_ws && (_ws.readyState === WebSocket.OPEN || _ws.readyState === WebSocket.CONNECTING)) return;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = proto + '//' + location.host + '/ws';
  try { _ws = new WebSocket(url); } catch (e) { _wsScheduleRetry(); return; }

  _ws.onopen = () => {
    _wsRetry = 0;
    _wsDispatch('_connected', {});
  };

  _ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (_) { return; }
    const event = msg.event || '';
    if (event === 'ping') { try { _ws.send('ping'); } catch (_) {} return; }
    if (event === 'pong' || event === 'connected') return;
    _wsDispatch(event, msg.payload || {});
  };

  _ws.onclose = () => { _wsScheduleRetry(); };
  _ws.onerror = () => { try { _ws.close(); } catch (_) {} };
}

function _wsScheduleRetry() {
  if (_wsRetry >= _wsMaxRetry) return;
  const delay = Math.min(1000 * Math.pow(2, _wsRetry), 30000);
  _wsRetry++;
  setTimeout(wsConnect, delay);
}

// ── Default event handlers ───────────────────────────────

// Ward changes → update dot
wsOn('ward_changed', (p) => {
  const dot = document.getElementById('ward-dot');
  if (!dot) return;
  const level = String(p.level || p.ward_level || '').toLowerCase();
  dot.className = level === 'yellow' ? 'yellow' : level === 'red' ? 'red' : '';
  dot.title = 'Ward: ' + (level || 'GREEN').toUpperCase();
});

// Deed messages → add to chat if viewing that deed
wsOn('deed_message', (p) => {
  if (typeof onWsDeedMessage === 'function') onWsDeedMessage(p);
});

// Deed status changes → refresh nav
wsOn('deed_completed', (p) => {
  if (typeof onWsDeedCompleted === 'function') onWsDeedCompleted(p);
  setTimeout(renderNav, 300);
});
wsOn('deed_failed', (p) => {
  if (typeof onWsDeedFailed === 'function') onWsDeedFailed(p);
  setTimeout(renderNav, 300);
});
wsOn('deed_progress', (p) => {
  if (typeof onWsDeedProgress === 'function') onWsDeedProgress(p);
});
wsOn('passage_completed', (p) => {
  if (typeof onWsPassageCompleted === 'function') onWsPassageCompleted(p);
});
wsOn('eval_expiring', (p) => {
  if (typeof onWsEvalExpiring === 'function') onWsEvalExpiring(p);
});
