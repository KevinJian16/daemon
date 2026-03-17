#!/usr/bin/env python3
"""MCP server: LaTeX compilation — LaTeX source to PDF.

Compiles LaTeX source code into PDF using tectonic (preferred) or pdflatex.
Output files are saved to /tmp/.
Transport: stdio (launched by MCPDispatcher).
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import uuid

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

app = Server("latex")


def _find_compiler() -> tuple[str, list[str]]:
    """Find available LaTeX compiler. Prefer tectonic, fall back to pdflatex."""
    if shutil.which("tectonic"):
        return "tectonic", ["tectonic", "--outdir", "{outdir}", "{texfile}"]
    if shutil.which("pdflatex"):
        return "pdflatex", [
            "pdflatex", "-interaction=nonstopmode",
            "-output-directory={outdir}", "{texfile}",
        ]
    raise RuntimeError("No LaTeX compiler found. Install tectonic or pdflatex.")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="compile_latex",
            description="Compile LaTeX source code into a PDF file. Returns the path to the generated PDF.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Complete LaTeX source code to compile.",
                    },
                    "filename": {
                        "type": "string",
                        "description": "Output filename (without extension). Defaults to a random name.",
                    },
                },
                "required": ["source"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "compile_latex":
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    source = arguments["source"]
    base_name = arguments.get("filename", f"latex_{uuid.uuid4().hex[:8]}")
    outdir = "/tmp/daemon_latex"
    os.makedirs(outdir, exist_ok=True)

    # Write source to temp .tex file
    tex_path = os.path.join(outdir, f"{base_name}.tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(source)

    # Find compiler and build command
    compiler_name, cmd_template = _find_compiler()
    cmd = [
        part.format(outdir=outdir, texfile=tex_path) for part in cmd_template
    ]

    # Run compilation
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=outdir,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

    pdf_path = os.path.join(outdir, f"{base_name}.pdf")

    if proc.returncode != 0:
        result = {
            "success": False,
            "compiler": compiler_name,
            "error": stderr.decode(errors="replace")[-3000:],
            "stdout": stdout.decode(errors="replace")[-3000:],
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    if not os.path.exists(pdf_path):
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": "Compilation completed but PDF not found.",
            "stdout": stdout.decode(errors="replace")[-3000:],
        }, ensure_ascii=False, indent=2))]

    result = {
        "success": True,
        "compiler": compiler_name,
        "pdf_path": pdf_path,
        "pdf_size_bytes": os.path.getsize(pdf_path),
    }
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
