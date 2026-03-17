#!/usr/bin/env python3
"""MCP server: Mermaid diagram renderer — Mermaid code to SVG.

Renders Mermaid diagram definitions to SVG using the mermaid.ink public API.
Transport: stdio (launched by MCPDispatcher).

Reference: https://mermaid.ink
"""
from __future__ import annotations

import base64
import json

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

app = Server("mermaid-render")

MERMAID_INK_BASE = "https://mermaid.ink"


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="render_mermaid",
            description="Render a Mermaid diagram definition to SVG string.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Mermaid diagram code (e.g. 'graph TD; A-->B;')",
                    },
                    "theme": {
                        "type": "string",
                        "enum": ["default", "dark", "forest", "neutral"],
                        "description": "Mermaid theme",
                        "default": "default",
                    },
                },
                "required": ["code"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "render_mermaid":
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    code = arguments["code"]
    theme = arguments.get("theme", "default")

    # mermaid.ink accepts JSON config wrapped in base64
    payload = json.dumps({"code": code, "mermaid": {"theme": theme}})
    encoded = base64.urlsafe_b64encode(payload.encode()).decode()

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{MERMAID_INK_BASE}/svg/{encoded}")
        resp.raise_for_status()
        svg = resp.text

    result = {"svg": svg, "length": len(svg)}
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
