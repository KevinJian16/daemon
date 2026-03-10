const API = '';

async function api(path, options) {
  const response = await fetch(API + path, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(_friendlyError(text || String(response.status)));
  }
  return response.json();
}

function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function autoResize(element) {
  element.style.height = 'auto';
  element.style.height = Math.min(element.scrollHeight, 180) + 'px';
}

function md(value) {
  let html = String(value || '');
  html = html.replace(/```[\w-]*\n?([\s\S]*?)```/g, (_, code) => `<pre><code>${esc(code.trim())}</code></pre>`);
  html = html.replace(/`([^`]+)`/g, (_, code) => `<code>${esc(code)}</code>`);
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>');
  html = html.replace(/^[-*] (.+)$/gm, '<li>$1</li>').replace(/(<li>[\s\S]*<\/li>)/, '<ul>$1</ul>');
  html = html.replace(/\n\n+/g, '</p><p>');
  return '<p>' + html + '</p>';
}

function _friendlyError(raw) {
  const text = String(raw || '');
  if (!text) return t('genericError');
  if (text.includes('404')) return t('routeMissing');
  if (text.includes('message_required')) return lang === 'zh' ? '你还没有写下要补充的内容。' : 'You have not written anything yet.';
  if (text.includes('slip_not_found') || text.includes('folio_not_found') || text.includes('deed_not_found')) return t('routeMissing');
  if (text.includes('slip_has_no_design')) return lang === 'zh' ? '这张签札还没有可供再行的结构。' : 'This slip has no structure to re-run yet.';
  if (text.includes('slips_in_different_folios')) return lang === 'zh' ? '这两张签札已经分属不同的卷，不能直接并到一起。' : 'These slips already belong to different folios and cannot be merged directly.';
  if (text.includes('invalid_stance_target')) return lang === 'zh' ? '这个对象动作目前还不支持。' : 'That object action is not supported yet.';
  if (text.includes('temporal_unavailable')) return lang === 'zh' ? '行事引擎暂时不可用，请稍后再试。' : 'The deed engine is temporarily unavailable.';
  if (/(traceback|exception|stack|sqlite|json|errno|openclaw|workflow|temporal)/i.test(text)) return t('genericError');
  return text.replace(/^Error:\s*/i, '').replace(/^"|"$/g, '').trim() || t('genericError');
}
