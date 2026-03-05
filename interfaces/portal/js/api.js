// ── API ───────────────────────────────────────────────────
const API = '';
async function api(path, opts) {
  const r = await fetch(API + path, opts);
  if (!r.ok) { const txt = await r.text(); throw new Error(txt || r.status); }
  return r.json();
}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function autoResize(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,140)+'px'}

// ── Markdown ──────────────────────────────────────────────
function md(s) {
  let h = String(s||'');
  h = h.replace(/```[\w]*\n?([\s\S]*?)```/g,(_,c)=>`<pre><code>${esc(c.trim())}</code></pre>`);
  h = h.replace(/`([^`]+)`/g,(_,c)=>`<code>${esc(c)}</code>`);
  h = h.replace(/^### (.+)$/gm,'<h3>$1</h3>');
  h = h.replace(/^## (.+)$/gm,'<h2>$1</h2>');
  h = h.replace(/^# (.+)$/gm,'<h1>$1</h1>');
  h = h.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
  h = h.replace(/^> (.+)$/gm,'<blockquote>$1</blockquote>');
  h = h.replace(/^[-*] (.+)$/gm,'<li>$1</li>').replace(/(<li>[\s\S]*<\/li>)/,'<ul>$1</ul>');
  h = h.replace(/\n\n+/g,'</p><p>');
  return '<p>'+h+'</p>';
}

