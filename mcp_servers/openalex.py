#!/usr/bin/env python3
"""MCP server: OpenAlex — search academic works, authors, and institutions.

Provides tools for querying the OpenAlex API (free, no auth required).
Transport: stdio (launched by MCPDispatcher).

Reference: https://docs.openalex.org/
"""
from __future__ import annotations

import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

OA_BASE = "https://api.openalex.org"
MAILTO = os.environ.get("OPENALEX_MAILTO", "daemon@kevinjian.dev")

app = Server("openalex")


def _headers() -> dict[str, str]:
    return {"Accept": "application/json", "User-Agent": f"daemon-mcp (mailto:{MAILTO})"}


def _slim_work(w: dict) -> dict:
    """Extract key fields from an OpenAlex work object."""
    return {
        "id": w.get("id", ""),
        "doi": w.get("doi", ""),
        "title": w.get("title", ""),
        "publication_year": w.get("publication_year"),
        "cited_by_count": w.get("cited_by_count", 0),
        "type": w.get("type", ""),
        "open_access": w.get("open_access", {}),
        "authors": [
            {"name": a.get("author", {}).get("display_name", ""), "institution": (a.get("institutions") or [{}])[0].get("display_name", "") if a.get("institutions") else ""}
            for a in (w.get("authorships") or [])[:10]
        ],
        "abstract": w.get("abstract_inverted_index") and "(available)" or None,
        "primary_location": {
            "source": (w.get("primary_location") or {}).get("source", {}).get("display_name", "") if w.get("primary_location") else "",
            "landing_page_url": (w.get("primary_location") or {}).get("landing_page_url", ""),
        },
    }


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="openalex_search_works",
            description="Search OpenAlex for academic works (papers, articles, books) by query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "filter": {"type": "string", "description": "OpenAlex filter string (e.g. 'publication_year:2023,type:article')"},
                    "sort": {"type": "string", "description": "Sort field (e.g. 'cited_by_count:desc')", "default": "relevance_score:desc"},
                    "per_page": {"type": "integer", "description": "Results per page (1-50)", "default": 10},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="openalex_get_work",
            description="Get a single work by DOI or OpenAlex ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "doi": {"type": "string", "description": "DOI (e.g. '10.1038/s41586-023-06647-8') or OpenAlex ID (e.g. 'W2741809807')"},
                },
                "required": ["doi"],
            },
        ),
        Tool(
            name="openalex_search_authors",
            description="Search OpenAlex for authors by name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Author name to search"},
                    "per_page": {"type": "integer", "description": "Results per page (1-50)", "default": 10},
                },
                "required": ["query"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=30, headers=_headers()) as client:
        if name == "openalex_search_works":
            params: dict = {
                "search": arguments["query"],
                "sort": arguments.get("sort", "relevance_score:desc"),
                "per_page": min(int(arguments.get("per_page", 10)), 50),
                "mailto": MAILTO,
            }
            if arguments.get("filter"):
                params["filter"] = arguments["filter"]
            resp = await client.get(f"{OA_BASE}/works", params=params)
            resp.raise_for_status()
            works = [_slim_work(w) for w in resp.json().get("results", [])]
            return [TextContent(type="text", text=json.dumps(works, ensure_ascii=False, indent=2))]

        elif name == "openalex_get_work":
            doi = arguments["doi"]
            identifier = doi if doi.startswith("W") else f"https://doi.org/{doi}"
            resp = await client.get(f"{OA_BASE}/works/{identifier}", params={"mailto": MAILTO})
            resp.raise_for_status()
            return [TextContent(type="text", text=json.dumps(_slim_work(resp.json()), ensure_ascii=False, indent=2))]

        elif name == "openalex_search_authors":
            params = {
                "search": arguments["query"],
                "per_page": min(int(arguments.get("per_page", 10)), 50),
                "mailto": MAILTO,
            }
            resp = await client.get(f"{OA_BASE}/authors", params=params)
            resp.raise_for_status()
            authors = [
                {
                    "id": a.get("id", ""),
                    "display_name": a.get("display_name", ""),
                    "works_count": a.get("works_count", 0),
                    "cited_by_count": a.get("cited_by_count", 0),
                    "affiliations": [i.get("display_name", "") for i in (a.get("affiliations") or [])[:3]],
                }
                for a in resp.json().get("results", [])
            ]
            return [TextContent(type="text", text=json.dumps(authors, ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
