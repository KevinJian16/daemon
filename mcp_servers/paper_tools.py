#!/usr/bin/env python3
"""MCP server: paper output tools — LaTeX, BibTeX, charts.

Provides zero-LLM tools for:
- LaTeX compilation (tex → PDF)
- BibTeX management (add/format entries)
- Chart generation (matplotlib, mermaid)

Transport: stdio (launched by MCPDispatcher).

Reference: TODO.md Phase 4E
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

app = Server("paper-tools")

DAEMON_HOME = Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))
ARTIFACTS_DIR = DAEMON_HOME / "state" / "artifacts"


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="latex_compile",
            description="Compile a LaTeX document to PDF. Returns the output PDF path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tex_content": {"type": "string", "description": "LaTeX source content"},
                    "filename": {"type": "string", "description": "Output filename (without .pdf)", "default": "output"},
                    "bibtex": {"type": "boolean", "description": "Run BibTeX pass", "default": False},
                },
                "required": ["tex_content"],
            },
        ),
        Tool(
            name="bibtex_format",
            description="Format BibTeX entries from raw data into proper .bib format.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entries": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "description": "Entry type: article, inproceedings, book, misc"},
                                "key": {"type": "string", "description": "Citation key"},
                                "title": {"type": "string"},
                                "author": {"type": "string"},
                                "year": {"type": "string"},
                                "journal": {"type": "string"},
                                "booktitle": {"type": "string"},
                                "url": {"type": "string"},
                                "doi": {"type": "string"},
                                "volume": {"type": "string"},
                                "pages": {"type": "string"},
                            },
                            "required": ["type", "key", "title", "author", "year"],
                        },
                        "description": "List of BibTeX entries",
                    },
                },
                "required": ["entries"],
            },
        ),
        Tool(
            name="chart_matplotlib",
            description="Generate a chart using matplotlib and save as PNG.",
            inputSchema={
                "type": "object",
                "properties": {
                    "script": {
                        "type": "string",
                        "description": "Python matplotlib script. Must end with plt.savefig(output_path). The variable 'output_path' is pre-defined.",
                    },
                    "filename": {"type": "string", "description": "Output filename (without .png)", "default": "chart"},
                },
                "required": ["script"],
            },
        ),
        Tool(
            name="chart_mermaid",
            description="Render a Mermaid diagram to SVG using mmdc (mermaid-cli).",
            inputSchema={
                "type": "object",
                "properties": {
                    "diagram": {"type": "string", "description": "Mermaid diagram source"},
                    "filename": {"type": "string", "description": "Output filename (without .svg)", "default": "diagram"},
                },
                "required": ["diagram"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    if name == "latex_compile":
        return [_latex_compile(arguments)]
    elif name == "bibtex_format":
        return [_bibtex_format(arguments)]
    elif name == "chart_matplotlib":
        return [_chart_matplotlib(arguments)]
    elif name == "chart_mermaid":
        return [_chart_mermaid(arguments)]
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


def _latex_compile(args: dict) -> TextContent:
    tex = args["tex_content"]
    filename = args.get("filename", "output")
    use_bibtex = args.get("bibtex", False)

    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = Path(tmpdir) / f"{filename}.tex"
        tex_path.write_text(tex, encoding="utf-8")

        # First pass
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", f"{filename}.tex"],
            cwd=tmpdir, capture_output=True, text=True, timeout=60,
        )

        if use_bibtex:
            subprocess.run(
                ["bibtex", filename], cwd=tmpdir,
                capture_output=True, text=True, timeout=30,
            )
            # Two more passes for references
            for _ in range(2):
                subprocess.run(
                    ["pdflatex", "-interaction=nonstopmode", f"{filename}.tex"],
                    cwd=tmpdir, capture_output=True, text=True, timeout=60,
                )

        pdf_path = Path(tmpdir) / f"{filename}.pdf"
        if pdf_path.exists():
            out_path = ARTIFACTS_DIR / f"{filename}.pdf"
            out_path.write_bytes(pdf_path.read_bytes())
            return TextContent(type="text", text=json.dumps({
                "status": "ok",
                "pdf_path": str(out_path),
                "size_bytes": out_path.stat().st_size,
            }))
        else:
            return TextContent(type="text", text=json.dumps({
                "status": "error",
                "log": result.stdout[-2000:] if result.stdout else result.stderr[-2000:],
            }))


def _bibtex_format(args: dict) -> TextContent:
    entries = args["entries"]
    bib_lines: list[str] = []

    for entry in entries:
        etype = entry.get("type", "misc")
        key = entry["key"]
        bib_lines.append(f"@{etype}{{{key},")
        for field in ["title", "author", "year", "journal", "booktitle", "url", "doi", "volume", "pages"]:
            if entry.get(field):
                bib_lines.append(f"  {field} = {{{entry[field]}}},")
        bib_lines.append("}")
        bib_lines.append("")

    bib_text = "\n".join(bib_lines)

    # Also save to artifacts
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    bib_path = ARTIFACTS_DIR / "references.bib"
    bib_path.write_text(bib_text, encoding="utf-8")

    return TextContent(type="text", text=json.dumps({
        "status": "ok",
        "bib_content": bib_text,
        "bib_path": str(bib_path),
        "entry_count": len(entries),
    }))


def _chart_matplotlib(args: dict) -> TextContent:
    script = args["script"]
    filename = args.get("filename", "chart")
    out_path = ARTIFACTS_DIR / f"{filename}.png"

    # Execute matplotlib script in subprocess for safety
    full_script = f"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

output_path = {str(out_path)!r}

{script}

if not any(f.endswith('.png') for f in __import__('os').listdir({str(ARTIFACTS_DIR)!r})):
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
"""
    result = subprocess.run(
        ["python3", "-c", full_script],
        capture_output=True, text=True, timeout=30,
    )

    if out_path.exists():
        return TextContent(type="text", text=json.dumps({
            "status": "ok",
            "png_path": str(out_path),
            "size_bytes": out_path.stat().st_size,
        }))
    else:
        return TextContent(type="text", text=json.dumps({
            "status": "error",
            "stderr": result.stderr[-1000:],
        }))


def _chart_mermaid(args: dict) -> TextContent:
    diagram = args["diagram"]
    filename = args.get("filename", "diagram")
    out_path = ARTIFACTS_DIR / f"{filename}.svg"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False) as f:
        f.write(diagram)
        mmd_path = f.name

    try:
        result = subprocess.run(
            ["npx", "-y", "@mermaid-js/mermaid-cli", "mmdc", "-i", mmd_path, "-o", str(out_path)],
            capture_output=True, text=True, timeout=60,
        )
        if out_path.exists():
            return TextContent(type="text", text=json.dumps({
                "status": "ok",
                "svg_path": str(out_path),
                "size_bytes": out_path.stat().st_size,
            }))
        else:
            return TextContent(type="text", text=json.dumps({
                "status": "error",
                "stderr": result.stderr[-1000:],
            }))
    finally:
        Path(mmd_path).unlink(missing_ok=True)


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
