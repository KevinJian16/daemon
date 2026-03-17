#!/usr/bin/env python3
"""MCP server: CrossRef — search scholarly metadata and citation data.

Provides tools for querying the CrossRef API for works, DOIs, and citation counts.
Transport: stdio (launched by MCPDispatcher).

Reference: https://api.crossref.org/swagger-ui/index.html
"""
from __future__ import annotations

import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

CR_BASE = "https://api.crossref.org"
MAILTO = os.environ.get("CROSSREF_MAILTO", "daemon@kevinjian.dev")

app = Server("crossref")


def _headers() -> dict[str, str]:
    return {"User-Agent": f"daemon-mcp (mailto:{MAILTO})", "Accept": "application/json"}


def _slim_item(item: dict) -> dict:
    """Extract key fields from a CrossRef work item."""
    return {
        "doi": item.get("DOI", ""),
        "title": (item.get("title") or [""])[0],
        "type": item.get("type", ""),
        "published": item.get("published-print", item.get("published-online", {})).get("date-parts", [[]])[0],
        "container_title": (item.get("container-title") or [""])[0],
        "authors": [
            {"given": a.get("given", ""), "family": a.get("family", "")}
            for a in (item.get("author") or [])[:10]
        ],
        "is_referenced_by_count": item.get("is-referenced-by-count", 0),
        "references_count": item.get("references-count", 0),
        "url": item.get("URL", ""),
        "abstract": (item.get("abstract") or "")[:500],
    }


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="crossref_search",
            description="Search CrossRef for scholarly works by query string.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "rows": {"type": "integer", "description": "Max results (1-50)", "default": 10},
                    "sort": {"type": "string", "description": "Sort field: relevance, published, is-referenced-by-count", "default": "relevance"},
                    "filter": {"type": "string", "description": "CrossRef filter (e.g. 'from-pub-date:2023,type:journal-article')"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="crossref_get_work",
            description="Get detailed metadata for a single work by DOI.",
            inputSchema={
                "type": "object",
                "properties": {
                    "doi": {"type": "string", "description": "DOI (e.g. '10.1038/s41586-023-06647-8')"},
                },
                "required": ["doi"],
            },
        ),
        Tool(
            name="crossref_citation_count",
            description="Get the citation count for a work by DOI.",
            inputSchema={
                "type": "object",
                "properties": {
                    "doi": {"type": "string", "description": "DOI of the work"},
                },
                "required": ["doi"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=30, headers=_headers()) as client:
        if name == "crossref_search":
            params: dict = {
                "query": arguments["query"],
                "rows": min(int(arguments.get("rows", 10)), 50),
                "sort": arguments.get("sort", "relevance"),
                "order": "desc",
                "mailto": MAILTO,
            }
            if arguments.get("filter"):
                params["filter"] = arguments["filter"]
            resp = await client.get(f"{CR_BASE}/works", params=params)
            resp.raise_for_status()
            items = [_slim_item(i) for i in resp.json().get("message", {}).get("items", [])]
            return [TextContent(type="text", text=json.dumps(items, ensure_ascii=False, indent=2))]

        elif name == "crossref_get_work":
            doi = arguments["doi"]
            resp = await client.get(f"{CR_BASE}/works/{doi}", params={"mailto": MAILTO})
            resp.raise_for_status()
            item = resp.json().get("message", {})
            return [TextContent(type="text", text=json.dumps(_slim_item(item), ensure_ascii=False, indent=2))]

        elif name == "crossref_citation_count":
            doi = arguments["doi"]
            resp = await client.get(f"{CR_BASE}/works/{doi}", params={"mailto": MAILTO})
            resp.raise_for_status()
            item = resp.json().get("message", {})
            result = {
                "doi": doi,
                "title": (item.get("title") or [""])[0],
                "is_referenced_by_count": item.get("is-referenced-by-count", 0),
                "references_count": item.get("references-count", 0),
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
