#!/usr/bin/env python3
"""MCP server: arXiv Search — search and retrieve academic papers from arXiv.

Provides tools for querying the arXiv API by keyword, category, or paper ID.
Transport: stdio (launched by MCPDispatcher).

Reference: https://info.arxiv.org/help/api/basics.html
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

ARXIV_BASE = "https://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

app = Server("arxiv")


def _parse_entries(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    results = []
    for entry in root.findall("atom:entry", NS):
        paper: dict = {}
        paper["title"] = (entry.findtext("atom:title", "", NS) or "").strip().replace("\n", " ")
        paper["id"] = (entry.findtext("atom:id", "", NS) or "").strip()
        paper["published"] = entry.findtext("atom:published", "", NS)
        paper["updated"] = entry.findtext("atom:updated", "", NS)
        paper["summary"] = (entry.findtext("atom:summary", "", NS) or "").strip().replace("\n", " ")
        paper["authors"] = [
            a.findtext("atom:name", "", NS) for a in entry.findall("atom:author", NS)
        ]
        cats = entry.findall("atom:category", NS)
        paper["categories"] = [c.get("term", "") for c in cats]
        pdf_links = [l for l in entry.findall("atom:link", NS) if l.get("title") == "pdf"]
        paper["pdf_url"] = pdf_links[0].get("href", "") if pdf_links else ""
        results.append(paper)
    return results


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="arxiv_search",
            description="Search arXiv papers by query string and optional category filter.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (e.g. 'transformer attention')"},
                    "category": {"type": "string", "description": "arXiv category filter (e.g. 'cs.AI', 'math.CO')"},
                    "max_results": {"type": "integer", "description": "Max results (1-50)", "default": 10},
                    "sort_by": {
                        "type": "string",
                        "description": "Sort: relevance, lastUpdatedDate, submittedDate",
                        "default": "relevance",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="arxiv_get_paper",
            description="Get details for a specific arXiv paper by its ID (e.g. '2301.00001').",
            inputSchema={
                "type": "object",
                "properties": {
                    "arxiv_id": {"type": "string", "description": "arXiv paper ID (e.g. '2301.00001' or '2301.00001v2')"},
                },
                "required": ["arxiv_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=30) as client:
        if name == "arxiv_search":
            query = arguments["query"]
            cat = arguments.get("category")
            search_query = f"all:{query}"
            if cat:
                search_query = f"cat:{cat} AND all:{query}"
            params = {
                "search_query": search_query,
                "start": 0,
                "max_results": min(int(arguments.get("max_results", 10)), 50),
                "sortBy": arguments.get("sort_by", "relevance"),
                "sortOrder": "descending",
            }
            resp = await client.get(ARXIV_BASE, params=params)
            resp.raise_for_status()
            papers = _parse_entries(resp.text)
            return [TextContent(type="text", text=json.dumps(papers, ensure_ascii=False, indent=2))]

        elif name == "arxiv_get_paper":
            arxiv_id = arguments["arxiv_id"].replace("arXiv:", "")
            params = {"id_list": arxiv_id}
            resp = await client.get(ARXIV_BASE, params=params)
            resp.raise_for_status()
            papers = _parse_entries(resp.text)
            if not papers:
                return [TextContent(type="text", text=json.dumps({"error": "Paper not found"}))]
            return [TextContent(type="text", text=json.dumps(papers[0], ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
