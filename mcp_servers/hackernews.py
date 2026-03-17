#!/usr/bin/env python3
"""MCP server: Hacker News — browse stories and search via Algolia.
Transport: stdio (launched by MCPDispatcher).
Refs: https://github.com/HackerNews/API  https://hn.algolia.com/api
"""
from __future__ import annotations

import json

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

HN_BASE = "https://hacker-news.firebaseio.com/v0"
ALGOLIA_BASE = "https://hn.algolia.com/api/v1"

app = Server("hackernews")


async def _fetch_items(client: httpx.AsyncClient, ids: list[int], limit: int = 10) -> list[dict]:
    items = []
    for item_id in ids[:limit]:
        resp = await client.get(f"{HN_BASE}/item/{item_id}.json")
        if resp.status_code == 200 and resp.json():
            d = resp.json()
            items.append({"id": d.get("id"), "title": d.get("title", ""), "url": d.get("url", ""),
                           "by": d.get("by", ""), "score": d.get("score", 0),
                           "descendants": d.get("descendants", 0), "time": d.get("time"),
                           "type": d.get("type", ""), "text": (d.get("text") or "")[:300]})
    return items


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="hn_top_stories",
            description="Get current top/new/best stories from Hacker News.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Story category: top, new, best, ask, show, job",
                        "default": "top",
                    },
                    "limit": {"type": "integer", "description": "Number of stories (1-30)", "default": 10},
                },
                "required": [],
            },
        ),
        Tool(
            name="hn_get_item",
            description="Get details for a specific HN item (story, comment, poll) by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer", "description": "HN item ID"},
                    "include_comments": {"type": "boolean", "description": "Also fetch top-level comments", "default": False},
                },
                "required": ["item_id"],
            },
        ),
        Tool(
            name="hn_search",
            description="Search Hacker News stories and comments via Algolia full-text search.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "tags": {"type": "string", "description": "Filter tags: story, comment, poll, show_hn, ask_hn, front_page", "default": "story"},
                    "num_results": {"type": "integer", "description": "Max results (1-50)", "default": 10},
                    "sort_by_date": {"type": "boolean", "description": "Sort by date instead of relevance", "default": False},
                },
                "required": ["query"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=30) as client:
        if name == "hn_top_stories":
            category = arguments.get("category", "top")
            limit = min(int(arguments.get("limit", 10)), 30)
            valid = {"top": "topstories", "new": "newstories", "best": "beststories", "ask": "askstories", "show": "showstories", "job": "jobstories"}
            endpoint = valid.get(category, "topstories")
            resp = await client.get(f"{HN_BASE}/{endpoint}.json")
            resp.raise_for_status()
            ids = resp.json()
            items = await _fetch_items(client, ids, limit)
            return [TextContent(type="text", text=json.dumps(items, ensure_ascii=False, indent=2))]

        elif name == "hn_get_item":
            item_id = arguments["item_id"]
            resp = await client.get(f"{HN_BASE}/item/{item_id}.json")
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return [TextContent(type="text", text=json.dumps({"error": "Item not found"}))]
            result: dict = {
                "id": data.get("id"), "type": data.get("type", ""), "by": data.get("by", ""),
                "title": data.get("title", ""), "url": data.get("url", ""),
                "text": data.get("text", ""), "score": data.get("score", 0),
                "time": data.get("time"), "descendants": data.get("descendants", 0),
            }
            if arguments.get("include_comments") and data.get("kids"):
                comments = await _fetch_items(client, data["kids"], 10)
                result["comments"] = comments
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "hn_search":
            query = arguments["query"]
            tags = arguments.get("tags", "story")
            num = min(int(arguments.get("num_results", 10)), 50)
            endpoint = "search_by_date" if arguments.get("sort_by_date") else "search"
            resp = await client.get(f"{ALGOLIA_BASE}/{endpoint}", params={"query": query, "tags": tags, "hitsPerPage": num})
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
            results = [
                {
                    "objectID": h.get("objectID", ""),
                    "title": h.get("title", ""),
                    "url": h.get("url", ""),
                    "author": h.get("author", ""),
                    "points": h.get("points", 0),
                    "num_comments": h.get("num_comments", 0),
                    "created_at": h.get("created_at", ""),
                    "story_text": (h.get("story_text") or "")[:200],
                }
                for h in hits
            ]
            return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
