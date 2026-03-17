#!/usr/bin/env python3
"""MCP server: Kroki — render diagrams as SVG from text source.

Supports PlantUML, Mermaid, GraphViz (dot), D2, DBML, Excalidraw,
BlockDiag, Ditaa, ERD, Nomnoml, Pikchr, Structurizr, Vega, WaveDrom, etc.

Transport: stdio (launched by MCPDispatcher).
Uses public https://kroki.io or self-hosted instance via KROKI_URL env var.

Reference: https://docs.kroki.io/
"""
from __future__ import annotations

import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

KROKI_URL = os.environ.get("KROKI_URL", "https://kroki.io")

SUPPORTED_TYPES = [
    "plantuml", "mermaid", "graphviz", "dot", "d2", "dbml",
    "ditaa", "erd", "excalidraw", "nomnoml", "pikchr",
    "structurizr", "svgbob", "vega", "vegalite", "wavedrom",
    "blockdiag", "seqdiag", "actdiag", "nwdiag", "packetdiag", "rackdiag",
    "bytefield", "umlet", "wireviz",
]

app = Server("kroki")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="render_diagram",
            description=(
                "Render a diagram from text source code to SVG. "
                "Supports PlantUML, Mermaid, GraphViz/dot, D2, DBML, Ditaa, ERD, "
                "Nomnoml, Pikchr, Structurizr, Vega, WaveDrom, and more."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "diagram_type": {
                        "type": "string",
                        "description": f"Diagram type: {', '.join(SUPPORTED_TYPES[:12])}...",
                        "enum": SUPPORTED_TYPES,
                    },
                    "source": {
                        "type": "string",
                        "description": "Diagram source code in the specified language",
                    },
                    "output_format": {
                        "type": "string",
                        "description": "Output format: svg (default), png, pdf",
                        "default": "svg",
                        "enum": ["svg", "png", "pdf"],
                    },
                },
                "required": ["diagram_type", "source"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "render_diagram":
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    diagram_type = arguments["diagram_type"]
    source = arguments["source"]
    output_format = arguments.get("output_format", "svg")

    # Normalize: "dot" is an alias for "graphviz" in Kroki
    if diagram_type == "dot":
        diagram_type = "graphviz"

    if diagram_type not in SUPPORTED_TYPES and diagram_type != "graphviz":
        return [TextContent(type="text", text=json.dumps({
            "error": f"Unsupported diagram type: {diagram_type}",
            "supported": SUPPORTED_TYPES,
        }))]

    async with httpx.AsyncClient(timeout=60) as client:
        url = f"{KROKI_URL}/{diagram_type}/{output_format}"
        resp = await client.post(
            url,
            json={"diagram_source": source},
            headers={"Accept": f"image/{output_format}" if output_format != "svg" else "image/svg+xml"},
        )
        resp.raise_for_status()

        if output_format == "svg":
            result = {
                "diagram_type": diagram_type,
                "format": "svg",
                "svg": resp.text,
                "length": len(resp.text),
            }
        else:
            # For binary formats, return base64-encoded data
            import base64
            encoded = base64.b64encode(resp.content).decode("ascii")
            result = {
                "diagram_type": diagram_type,
                "format": output_format,
                "data_base64": encoded,
                "length": len(resp.content),
            }

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
