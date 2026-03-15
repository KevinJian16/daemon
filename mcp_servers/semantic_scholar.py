#!/usr/bin/env python3
"""MCP server: Semantic Scholar API — paper search and retrieval.

Provides tools for academic paper search via the Semantic Scholar Graph API.
Transport: stdio (launched by MCPDispatcher).

Reference: https://api.semanticscholar.org/api-docs/graph
"""
from __future__ import annotations

import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

S2_BASE = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "title,authors,year,abstract,citationCount,url,externalIds,tldr"

app = Server("semantic-scholar")


def _headers() -> dict[str, str]:
    key = os.environ.get("S2_API_KEY", "")
    h: dict[str, str] = {"Accept": "application/json"}
    if key:
        h["x-api-key"] = key
    return h


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="semantic_scholar_search",
            description="Search Semantic Scholar for academic papers by query string.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results (1-100)", "default": 10},
                    "year": {"type": "string", "description": "Year filter, e.g. '2020-' or '2018-2022'"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="semantic_scholar_paper",
            description="Get detailed info for a single paper by Semantic Scholar ID, DOI, or arXiv ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paper_id": {
                        "type": "string",
                        "description": "Paper identifier: S2 ID, DOI (e.g. 'DOI:10.1234/...'), or arXiv ID (e.g. 'ARXIV:2301.00001')",
                    },
                },
                "required": ["paper_id"],
            },
        ),
        Tool(
            name="semantic_scholar_citations",
            description="Get papers that cite a given paper.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string", "description": "Paper identifier"},
                    "limit": {"type": "integer", "description": "Max results (1-100)", "default": 10},
                },
                "required": ["paper_id"],
            },
        ),
        Tool(
            name="semantic_scholar_references",
            description="Get papers referenced by a given paper.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string", "description": "Paper identifier"},
                    "limit": {"type": "integer", "description": "Max results (1-100)", "default": 10},
                },
                "required": ["paper_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=30, headers=_headers()) as client:
        if name == "semantic_scholar_search":
            params: dict = {
                "query": arguments["query"],
                "limit": min(int(arguments.get("limit", 10)), 100),
                "fields": S2_FIELDS,
            }
            if arguments.get("year"):
                params["year"] = arguments["year"]
            resp = await client.get(f"{S2_BASE}/paper/search", params=params)
            resp.raise_for_status()
            data = resp.json()
            papers = data.get("data", [])
            return [TextContent(type="text", text=json.dumps(papers, ensure_ascii=False, indent=2))]

        elif name == "semantic_scholar_paper":
            pid = arguments["paper_id"]
            resp = await client.get(f"{S2_BASE}/paper/{pid}", params={"fields": S2_FIELDS})
            resp.raise_for_status()
            return [TextContent(type="text", text=json.dumps(resp.json(), ensure_ascii=False, indent=2))]

        elif name == "semantic_scholar_citations":
            pid = arguments["paper_id"]
            limit = min(int(arguments.get("limit", 10)), 100)
            resp = await client.get(
                f"{S2_BASE}/paper/{pid}/citations",
                params={"fields": "title,authors,year,citationCount,url", "limit": limit},
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]

        elif name == "semantic_scholar_references":
            pid = arguments["paper_id"]
            limit = min(int(arguments.get("limit", 10)), 100)
            resp = await client.get(
                f"{S2_BASE}/paper/{pid}/references",
                params={"fields": "title,authors,year,citationCount,url", "limit": limit},
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
