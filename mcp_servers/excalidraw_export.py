#!/usr/bin/env python3
"""MCP server: Excalidraw export — Excalidraw JSON to SVG via kroki.io.

Converts Excalidraw JSON diagrams to SVG using the kroki.io Excalidraw endpoint.
Transport: stdio (launched by MCPDispatcher).

Reference: https://kroki.io/#how (Excalidraw support)
"""
from __future__ import annotations

import json
import os
import uuid

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

KROKI_URL = os.environ.get("KROKI_URL", "https://kroki.io")

app = Server("excalidraw-export")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="export_excalidraw",
            description="Export an Excalidraw diagram to SVG. Accepts Excalidraw JSON and returns the SVG content and saved file path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "excalidraw_json": {
                        "type": "string",
                        "description": "Excalidraw diagram as a JSON string (the full .excalidraw file content).",
                    },
                    "filename": {
                        "type": "string",
                        "description": "Output filename (without extension). Defaults to a random name.",
                    },
                },
                "required": ["excalidraw_json"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "export_excalidraw":
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    excalidraw_json = arguments["excalidraw_json"]
    base_name = arguments.get("filename", f"excalidraw_{uuid.uuid4().hex[:8]}")
    outdir = "/tmp/daemon_excalidraw"
    os.makedirs(outdir, exist_ok=True)

    # Validate JSON
    try:
        json.loads(excalidraw_json)
    except json.JSONDecodeError as e:
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": f"Invalid JSON: {e}",
        }, ensure_ascii=False, indent=2))]

    # POST to kroki.io Excalidraw endpoint
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{KROKI_URL}/excalidraw/svg",
            content=excalidraw_json,
            headers={"Content-Type": "application/json", "Accept": "image/svg+xml"},
        )
        if resp.status_code != 200:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "status_code": resp.status_code,
                "error": resp.text[:2000],
            }, ensure_ascii=False, indent=2))]

        svg_content = resp.text

    # Save SVG to file
    svg_path = os.path.join(outdir, f"{base_name}.svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(svg_content)

    result = {
        "success": True,
        "svg_path": svg_path,
        "svg_size_bytes": len(svg_content.encode("utf-8")),
        "svg_preview": svg_content[:500],
    }
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
