#!/usr/bin/env python3
"""MCP server: CORE API — search and retrieve open access academic papers.

Provides tools for querying the CORE aggregation API for OA research outputs.
Transport: stdio (launched by MCPDispatcher).

Reference: https://api.core.ac.uk/docs/v3
"""
from __future__ import annotations

import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

CORE_BASE = "https://api.core.ac.uk/v3"

app = Server("core")


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Accept": "application/json"}
    key = os.environ.get("CORE_API_KEY", "")
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def _slim_work(w: dict) -> dict:
    """Extract key fields from a CORE work object."""
    return {
        "id": w.get("id", ""),
        "title": w.get("title", ""),
        "authors": [a.get("name", "") for a in (w.get("authors") or [])[:10]],
        "year": w.get("yearPublished"),
        "doi": w.get("doi", ""),
        "abstract": (w.get("abstract") or "")[:500],
        "download_url": w.get("downloadUrl", ""),
        "source_fulltext_urls": w.get("sourceFulltextUrls", []),
        "language": w.get("language", {}).get("code", "") if isinstance(w.get("language"), dict) else w.get("language", ""),
        "publisher": w.get("publisher", ""),
        "journals": [j.get("title", "") for j in (w.get("journals") or [])],
    }


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="core_search",
            description="Search CORE for open access academic papers by query string.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results (1-50)", "default": 10},
                    "year_from": {"type": "integer", "description": "Filter: minimum publication year"},
                    "year_to": {"type": "integer", "description": "Filter: maximum publication year"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="core_get_fulltext_url",
            description="Get the full text download URL for a CORE work by its ID or DOI.",
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {"type": "string", "description": "CORE work ID (numeric) or DOI"},
                },
                "required": ["identifier"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=30, headers=_headers()) as client:
        if name == "core_search":
            query = arguments["query"]
            limit = min(int(arguments.get("limit", 10)), 50)
            params: dict = {"q": query, "limit": limit}
            year_from = arguments.get("year_from")
            year_to = arguments.get("year_to")
            if year_from or year_to:
                yf = year_from or 1900
                yt = year_to or 2100
                params["q"] = f"({query}) AND yearPublished>={yf} AND yearPublished<={yt}"
            resp = await client.get(f"{CORE_BASE}/search/works", params=params)
            resp.raise_for_status()
            data = resp.json()
            works = [_slim_work(w) for w in data.get("results", [])]
            result = {"total_hits": data.get("totalHits", 0), "works": works}
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "core_get_fulltext_url":
            identifier = arguments["identifier"]
            # Try as CORE ID first, then as DOI
            if identifier.isdigit():
                resp = await client.get(f"{CORE_BASE}/works/{identifier}")
            else:
                # Search by DOI
                resp = await client.get(f"{CORE_BASE}/search/works", params={"q": f'doi:"{identifier}"', "limit": 1})
            resp.raise_for_status()
            data = resp.json()
            if "results" in data:
                works = data.get("results", [])
                if not works:
                    return [TextContent(type="text", text=json.dumps({"error": "No work found for identifier"}))]
                work = works[0]
            else:
                work = data
            result = {
                "id": work.get("id", ""),
                "title": work.get("title", ""),
                "doi": work.get("doi", ""),
                "download_url": work.get("downloadUrl", ""),
                "source_fulltext_urls": work.get("sourceFulltextUrls", []),
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
