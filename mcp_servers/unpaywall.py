#!/usr/bin/env python3
"""MCP server: Unpaywall — find open access versions of papers by DOI.

Provides tools for querying the Unpaywall API to locate free-to-read versions
of scholarly articles.
Transport: stdio (launched by MCPDispatcher).

Reference: https://unpaywall.org/products/api
"""
from __future__ import annotations

import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

UNPAYWALL_BASE = "https://api.unpaywall.org/v2"
EMAIL = os.environ.get("UNPAYWALL_EMAIL", "daemon@kevinjian.dev")

app = Server("unpaywall")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="unpaywall_find_oa",
            description="Find open access version of a paper by DOI. Returns OA locations with PDF/HTML URLs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "doi": {"type": "string", "description": "DOI of the paper (e.g. '10.1038/s41586-023-06647-8')"},
                },
                "required": ["doi"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=30) as client:
        if name == "unpaywall_find_oa":
            doi = arguments["doi"]
            resp = await client.get(f"{UNPAYWALL_BASE}/{doi}", params={"email": EMAIL})
            resp.raise_for_status()
            data = resp.json()
            best = data.get("best_oa_location") or {}
            oa_locations = data.get("oa_locations") or []
            result = {
                "doi": data.get("doi", ""),
                "title": data.get("title", ""),
                "is_oa": data.get("is_oa", False),
                "oa_status": data.get("oa_status", ""),
                "journal_name": data.get("journal_name", ""),
                "published_date": data.get("published_date", ""),
                "best_oa_location": {
                    "url": best.get("url", ""),
                    "url_for_pdf": best.get("url_for_pdf", ""),
                    "url_for_landing_page": best.get("url_for_landing_page", ""),
                    "host_type": best.get("host_type", ""),
                    "version": best.get("version", ""),
                    "license": best.get("license", ""),
                } if best else None,
                "oa_locations_count": len(oa_locations),
                "oa_locations": [
                    {
                        "url": loc.get("url", ""),
                        "url_for_pdf": loc.get("url_for_pdf", ""),
                        "host_type": loc.get("host_type", ""),
                        "version": loc.get("version", ""),
                    }
                    for loc in oa_locations[:5]
                ],
            }
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
