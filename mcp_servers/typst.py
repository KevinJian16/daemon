#!/usr/bin/env python3
"""MCP server: Typst compilation — Typst source to PDF.

Compiles Typst source code into PDF using the typst CLI.
Output files are saved to /tmp/.
Transport: stdio (launched by MCPDispatcher).
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

app = Server("typst")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="compile_typst",
            description="Compile Typst source code into a PDF file. Returns the path to the generated PDF.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Complete Typst source code to compile.",
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
    if name != "compile_typst":
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    source = arguments["source"]
    base_name = arguments.get("filename", f"typst_{uuid.uuid4().hex[:8]}")
    outdir = "/tmp/daemon_typst"
    os.makedirs(outdir, exist_ok=True)

    # Write source to temp .typ file
    typ_path = os.path.join(outdir, f"{base_name}.typ")
    pdf_path = os.path.join(outdir, f"{base_name}.pdf")
    with open(typ_path, "w", encoding="utf-8") as f:
        f.write(source)

    # Run typst compile
    cmd = ["typst", "compile", typ_path, pdf_path]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=outdir,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

    if proc.returncode != 0:
        result = {
            "success": False,
            "error": stderr.decode(errors="replace")[-3000:],
            "stdout": stdout.decode(errors="replace")[-3000:],
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    if not os.path.exists(pdf_path):
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": "Compilation completed but PDF not found.",
        }, ensure_ascii=False, indent=2))]

    result = {
        "success": True,
        "pdf_path": pdf_path,
        "pdf_size_bytes": os.path.getsize(pdf_path),
    }
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
