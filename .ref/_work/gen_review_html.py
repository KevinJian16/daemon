#!/usr/bin/env python3
"""Generate SYSTEM_DESIGN.review.html from SYSTEM_DESIGN.md + SYSTEM_DESIGN_REFERENCE.md"""

import re
import html as html_mod
from pathlib import Path

REF_DIR = Path(__file__).parent.parent

CSS = r"""
    :root {
      --bg: #f6f1e8;
      --panel: rgba(255,255,255,0.82);
      --panel-strong: rgba(255,255,255,0.93);
      --ink: #2f241d;
      --ink-soft: #5c4a3d;
      --rule: rgba(92, 74, 61, 0.18);
      --shadow: 0 18px 48px rgba(74, 52, 36, 0.10);
      --default-bg: #ead8ae;
      --default-border: #b48738;
      --default-ink: #5a3d11;
      --unresolved-bg: #ebc0b6;
      --unresolved-border: #b65e4d;
      --unresolved-ink: #61251f;
      --final-bg: #ede7dc;
      --final-ink: #46362b;
      --link: #7a4e2f;
      --code-bg: rgba(84, 63, 49, 0.08);
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body { margin: 0; color: var(--ink); background: radial-gradient(circle at top left, rgba(196, 159, 104, 0.18), transparent 26%), radial-gradient(circle at top right, rgba(182, 94, 77, 0.12), transparent 24%), linear-gradient(180deg, #f9f5ee 0%, var(--bg) 100%); font: 17px/1.72 "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif; }
    a { color: var(--link); }
    .page { width: min(1100px, calc(100vw - 32px)); margin: 24px auto 56px; }
    .legend { position: sticky; top: 0; z-index: 20; display: flex; flex-wrap: wrap; gap: 12px; align-items: center; padding: 14px 18px; margin-bottom: 20px; background: rgba(246, 241, 232, 0.92); backdrop-filter: blur(14px); border: 1px solid var(--rule); border-radius: 18px; box-shadow: var(--shadow); font-family: "Avenir Next", "Segoe UI", sans-serif; }
    .legend-title { font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--ink-soft); margin-right: 6px; }
    .legend-note { color: var(--ink-soft); font-size: 0.95rem; margin-left: auto; }
    .badge { display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.18rem 0.6rem; border-radius: 999px; font: 700 0.78rem/1.2 "Avenir Next", "Segoe UI", sans-serif; letter-spacing: 0.06em; text-transform: uppercase; vertical-align: baseline; white-space: nowrap; }
    .badge-default { background: rgba(234, 216, 174, 0.9); color: var(--default-ink); border: 1px solid rgba(180, 135, 56, 0.42); }
    .badge-unresolved { background: rgba(235, 192, 182, 0.92); color: var(--unresolved-ink); border: 1px solid rgba(182, 94, 77, 0.40); }
    .badge-final { background: rgba(237, 231, 220, 0.95); color: var(--final-ink); border: 1px solid rgba(92, 74, 61, 0.18); }
    main { background: var(--panel); border: 1px solid var(--rule); border-radius: 28px; box-shadow: var(--shadow); padding: 42px 52px 56px; }
    h1, h2, h3, h4 { color: #221913; line-height: 1.25; scroll-margin-top: 96px; }
    h1 { margin-top: 0; margin-bottom: 0.4em; font-size: clamp(2.1rem, 5vw, 3.15rem); letter-spacing: -0.02em; }
    h2 { margin-top: 2.2em; padding-top: 0.3em; border-top: 1px solid var(--rule); font-size: 1.58rem; }
    h3 { margin-top: 1.6em; font-size: 1.18rem; }
    h4 { margin-top: 1.2em; font-size: 1.05rem; }
    blockquote { margin: 1.2em 0; padding: 1rem 1.2rem; border-left: 4px solid rgba(122, 78, 47, 0.35); background: rgba(255, 255, 255, 0.62); color: var(--ink-soft); }
    hr { border: 0; border-top: 1px solid var(--rule); margin: 2rem 0; }
    p, li { margin: 0.72em 0; }
    ul, ol { padding-left: 1.35rem; }
    table { width: 100%; border-collapse: collapse; margin: 1.25rem 0 1.5rem; overflow: hidden; background: var(--panel-strong); border: 1px solid var(--rule); border-radius: 16px; display: block; overflow-x: auto; }
    thead { background: rgba(92, 74, 61, 0.07); }
    th, td { padding: 0.85rem 0.95rem; border-bottom: 1px solid rgba(92, 74, 61, 0.10); text-align: left; vertical-align: top; min-width: 120px; }
    tr:last-child td { border-bottom: 0; }
    code { padding: 0.12rem 0.36rem; border-radius: 7px; background: var(--code-bg); font: 0.92em/1.45 "SFMono-Regular", Menlo, Consolas, monospace; }
    pre { padding: 1rem 1.15rem; overflow: auto; border-radius: 16px; background: #2c231d; color: #f5eadf; box-shadow: inset 0 1px 0 rgba(255,255,255,0.04); }
    pre code { padding: 0; background: transparent; color: inherit; }
    .callout { margin: 1.25rem 0; padding: 1rem 1.15rem 1.05rem; border-radius: 18px; border: 1px solid transparent; box-shadow: 0 10px 26px rgba(74, 52, 36, 0.06); }
    .callout-default { background: linear-gradient(180deg, rgba(234, 216, 174, 0.36), rgba(234, 216, 174, 0.22)); border-color: rgba(180, 135, 56, 0.40); }
    .callout-unresolved { background: linear-gradient(180deg, rgba(235, 192, 182, 0.40), rgba(235, 192, 182, 0.24)); border-color: rgba(182, 94, 77, 0.42); }
    .callout-final { background: linear-gradient(180deg, rgba(237, 231, 220, 0.38), rgba(237, 231, 220, 0.20)); border-color: rgba(92, 74, 61, 0.22); }
    .kicker { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 1.2rem; font-family: "Avenir Next", "Segoe UI", sans-serif; color: var(--ink-soft); }
    .kicker span { padding: 0.45rem 0.7rem; border-radius: 999px; background: rgba(255, 255, 255, 0.66); border: 1px solid var(--rule); }
    .toc { margin: 1.5rem 0; padding: 1rem 1.2rem; background: rgba(255,255,255,0.5); border-radius: 16px; border: 1px solid var(--rule); }
    .toc ul { list-style: none; padding-left: 0; }
    .toc li { margin: 0.3em 0; }
    .toc a { text-decoration: none; }
    .sep { margin: 3rem 0; border-top: 3px double var(--rule); }
    @media (max-width: 760px) { .page { width: min(100vw - 18px, 1000px); margin: 12px auto 28px; } .legend { position: static; padding: 12px 14px; } .legend-note { margin-left: 0; width: 100%; } main { padding: 24px 18px 28px; border-radius: 20px; } table { border-radius: 14px; } }
    @media print { body { background: #fff; } .page { width: 100%; margin: 0; } .legend { position: static; box-shadow: none; background: #fff; } main { box-shadow: none; border: 0; padding: 0; } .callout { box-shadow: none; } a { color: inherit; text-decoration: none; } }
"""


def escape(text: str) -> str:
    return html_mod.escape(text, quote=False)


def inline_format(text: str) -> str:
    """Handle inline markdown: bold, italic, code, links, strikethrough."""
    # code spans first (protect from other processing)
    parts = []
    pos = 0
    for m in re.finditer(r'`([^`]+)`', text):
        parts.append(process_inline_no_code(text[pos:m.start()]))
        parts.append(f'<code>{escape(m.group(1))}</code>')
        pos = m.end()
    parts.append(process_inline_no_code(text[pos:]))
    return ''.join(parts)


def process_inline_no_code(text: str) -> str:
    t = escape(text)
    # strikethrough
    t = re.sub(r'~~(.+?)~~', r'<s>\1</s>', t)
    # bold
    t = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
    # italic
    t = re.sub(r'\*(.+?)\*', r'<em>\1</em>', t)
    # links
    t = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', t)
    return t


def make_id(text: str) -> str:
    clean = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]+', '-', text).strip('-').lower()
    return clean or 'section'


def md_to_html(md_text: str) -> tuple[str, int, int, int]:
    """Convert markdown to HTML body content. Returns (html, final_count, default_count, unresolved_count)."""
    lines = md_text.split('\n')
    out = []
    in_code = False
    code_buf = []
    in_table = False
    table_buf = []
    in_blockquote = False
    bq_buf = []
    in_list = False
    list_type = None  # 'ul' or 'ol'
    list_buf = []

    final_count = 0
    default_count = 0
    unresolved_count = 0

    def flush_list():
        nonlocal in_list, list_type, list_buf
        if in_list and list_buf:
            tag = list_type
            out.append(f'<{tag}>')
            for item in list_buf:
                out.append(f'  <li>{item}</li>')
            out.append(f'</{tag}>')
            list_buf = []
            in_list = False
            list_type = None

    def flush_blockquote():
        nonlocal in_blockquote, bq_buf
        if in_blockquote and bq_buf:
            content = '<br>\n'.join(bq_buf)
            out.append(f'<blockquote>{content}</blockquote>')
            bq_buf = []
            in_blockquote = False

    def flush_table():
        nonlocal in_table, table_buf
        if in_table and table_buf:
            out.append(render_table(table_buf))
            table_buf = []
            in_table = False

    def render_table(rows):
        if len(rows) < 2:
            return ''
        html_parts = ['<table>']
        # header
        header_cells = [c.strip() for c in rows[0].strip('|').split('|')]
        html_parts.append('<thead><tr>')
        for c in header_cells:
            html_parts.append(f'<th>{inline_format(c)}</th>')
        html_parts.append('</tr></thead>')
        # body (skip separator row)
        html_parts.append('<tbody>')
        for row in rows[2:]:
            cells = [c.strip() for c in row.strip('|').split('|')]
            html_parts.append('<tr>')
            for c in cells:
                html_parts.append(f'<td>{inline_format(c)}</td>')
            html_parts.append('</tr>')
        html_parts.append('</tbody></table>')
        return '\n'.join(html_parts)

    def annotate_line(text: str) -> str:
        """Add badge callouts for FINAL/DEFAULT/UNRESOLVED lines."""
        nonlocal final_count, default_count, unresolved_count
        result = text

        if re.search(r'FINAL\s*(规则|规则：|：)', text) or text.strip().startswith('FINAL'):
            final_count += 1
            badge = '<span class="badge badge-final">FINAL</span> '
            result = re.sub(r'FINAL\s*(规则：|规则|：)?', badge, result, count=1)

        if '**[DEFAULT]**' in text or text.strip().startswith('**[DEFAULT]**'):
            default_count += 1
            badge = '<span class="badge badge-default">DEFAULT</span> '
            result = result.replace('**[DEFAULT]**', badge)

        if '**[UNRESOLVED]**' in text or text.strip().startswith('**[UNRESOLVED]**'):
            unresolved_count += 1
            badge = '<span class="badge badge-unresolved">UNRESOLVED</span> '
            result = result.replace('**[UNRESOLVED]**', badge)

        if '[DEFAULT]' in result and 'badge-default' not in result:
            default_count += 1
            badge = '<span class="badge badge-default">DEFAULT</span> '
            result = result.replace('[DEFAULT]', badge)

        if '[UNRESOLVED]' in result and 'badge-unresolved' not in result:
            unresolved_count += 1
            badge = '<span class="badge badge-unresolved">UNRESOLVED</span> '
            result = result.replace('[UNRESOLVED]', badge)

        return result

    def wrap_callout(html_line: str) -> str:
        """Wrap lines with badges in callout divs."""
        if 'badge-default' in html_line:
            return f'<div class="callout callout-default">{html_line}</div>'
        if 'badge-unresolved' in html_line:
            return f'<div class="callout callout-unresolved">{html_line}</div>'
        if 'badge-final' in html_line:
            return f'<div class="callout callout-final">{html_line}</div>'
        return html_line

    i = 0
    while i < len(lines):
        line = lines[i]

        # Code blocks
        if line.strip().startswith('```'):
            if not in_code:
                flush_list()
                flush_blockquote()
                flush_table()
                in_code = True
                lang = line.strip()[3:].strip()
                code_buf = []
                i += 1
                continue
            else:
                in_code = False
                code_text = escape('\n'.join(code_buf))
                out.append(f'<pre><code>{code_text}</code></pre>')
                code_buf = []
                i += 1
                continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # Table rows
        if '|' in line and line.strip().startswith('|'):
            flush_list()
            flush_blockquote()
            if not in_table:
                in_table = True
                table_buf = []
            table_buf.append(line)
            i += 1
            continue
        else:
            flush_table()

        # Blockquotes
        if line.strip().startswith('>'):
            flush_list()
            if not in_blockquote:
                in_blockquote = True
                bq_buf = []
            content = line.strip()[1:].strip()
            bq_buf.append(inline_format(content))
            i += 1
            continue
        else:
            flush_blockquote()

        # Horizontal rules
        if line.strip() in ('---', '***', '___'):
            flush_list()
            out.append('<hr>')
            i += 1
            continue

        # Headers
        m = re.match(r'^(#{1,4})\s+(.*)', line)
        if m:
            flush_list()
            level = len(m.group(1))
            text = m.group(2)
            hid = make_id(text)
            formatted = inline_format(text)
            formatted = annotate_line(formatted)
            out.append(f'<h{level} id="{hid}">{formatted}</h{level}>')
            i += 1
            continue

        # List items
        m_ul = re.match(r'^(\s*)[*\-]\s+(.*)', line)
        m_ol = re.match(r'^(\s*)\d+\.\s+(.*)', line)
        if m_ul or m_ol:
            if not in_list:
                in_list = True
                list_type = 'ul' if m_ul else 'ol'
                list_buf = []
            m_item = m_ul or m_ol
            content = m_item.group(2)
            content = inline_format(content)
            content = annotate_line(content)
            list_buf.append(content)
            i += 1
            continue
        else:
            flush_list()

        # Empty lines
        if not line.strip():
            i += 1
            continue

        # Regular paragraphs
        para = inline_format(line)
        para = annotate_line(para)
        wrapped = wrap_callout(f'<p>{para}</p>')
        out.append(wrapped)
        i += 1

    flush_list()
    flush_blockquote()
    flush_table()

    return '\n'.join(out), final_count, default_count, unresolved_count


def generate():
    main_md = (REF_DIR / 'SYSTEM_DESIGN.md').read_text(encoding='utf-8')
    ref_md = (REF_DIR / 'SYSTEM_DESIGN_REFERENCE.md').read_text(encoding='utf-8')

    main_html, f1, d1, u1 = md_to_html(main_md)
    ref_html, f2, d2, u2 = md_to_html(ref_md)

    total_final = f1 + f2
    total_default = d1 + d2
    total_unresolved = u1 + u2

    full_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Daemon 系统设计七稿（两层 agent 架构）— 审阅版</title>
  <style>{CSS}
  </style>
</head>
<body>
  <div class="page">
    <div class="legend">
      <span class="legend-title">Review Legend</span>
      <span class="badge badge-final">FINAL</span>
      <span class="badge badge-default">DEFAULT</span>
      <span class="badge badge-unresolved">UNRESOLVED</span>
      <span class="legend-note">标记统计：FINAL {total_final} · DEFAULT {total_default} · UNRESOLVED {total_unresolved}</span>
    </div>
    <main>
      <div class="kicker">
        <span>七稿（两层 agent 架构）· 2026-03-15</span>
        <span>唯一权威源：SYSTEM_DESIGN.md</span>
        <span>审阅副本：SYSTEM_DESIGN.review.html</span>
      </div>

      {main_html}

      <div class="sep"></div>

      <h1>配套参考文档</h1>
      <p><em>以下内容来自 SYSTEM_DESIGN_REFERENCE.md（附录 B-I）</em></p>

      {ref_html}

    </main>
  </div>
</body>
</html>"""

    out_path = REF_DIR / 'SYSTEM_DESIGN.review.html'
    out_path.write_text(full_html, encoding='utf-8')
    print(f"Generated {out_path}")
    print(f"  FINAL: {total_final}, DEFAULT: {total_default}, UNRESOLVED: {total_unresolved}")
    print(f"  Size: {len(full_html):,} bytes")


if __name__ == '__main__':
    generate()
