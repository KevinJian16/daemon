#!/usr/bin/env python3
"""MCP server: NewsData.io — latest news and search.
Transport: stdio (launched by MCPDispatcher).
"""
from __future__ import annotations

import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

BASE_URL = "https://newsdata.io/api/1"

app = Server("newsdata")


def _params_base() -> dict[str, str]:
    key = os.environ.get("NEWSDATA_API_KEY", "")
    if not key:
        raise RuntimeError("NEWSDATA_API_KEY not set")
    return {"apikey": key}


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_latest_news",
            description="Get latest news articles, optionally filtered by country, category, or language.",
            inputSchema={
                "type": "object",
                "properties": {
                    "country": {
                        "type": "string",
                        "description": "Country code (e.g. 'us', 'cn', 'gb'). Comma-separated for multiple.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category: business, entertainment, environment, food, health, politics, science, sports, technology, top, world.",
                    },
                    "language": {
                        "type": "string",
                        "description": "Language code (e.g. 'en', 'zh'). Comma-separated for multiple.",
                    },
                    "size": {
                        "type": "integer",
                        "description": "Number of results (1-50)",
                        "default": 10,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="search_news",
            description="Search news articles by keyword query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query keywords"},
                    "country": {
                        "type": "string",
                        "description": "Country code filter (e.g. 'us'). Comma-separated for multiple.",
                    },
                    "language": {
                        "type": "string",
                        "description": "Language code (e.g. 'en'). Comma-separated for multiple.",
                    },
                    "from_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format.",
                    },
                    "to_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format.",
                    },
                    "size": {
                        "type": "integer",
                        "description": "Number of results (1-50)",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        ),
    ]


_ARTICLE_KEYS = ("title", "description", "link", "pubDate", "source_name", "category", "country")


def _extract_articles(data: dict) -> list[dict]:
    return [{k: a.get(k) for k in _ARTICLE_KEYS} for a in data.get("results", [])]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=30) as client:
        if name == "get_latest_news":
            params = _params_base()
            if arguments.get("country"):
                params["country"] = arguments["country"]
            if arguments.get("category"):
                params["category"] = arguments["category"]
            if arguments.get("language"):
                params["language"] = arguments["language"]
            params["size"] = str(min(int(arguments.get("size", 10)), 50))
            resp = await client.get(f"{BASE_URL}/latest", params=params)
            resp.raise_for_status()
            articles = _extract_articles(resp.json())
            return [TextContent(type="text", text=json.dumps(articles, ensure_ascii=False, indent=2))]

        elif name == "search_news":
            params = _params_base()
            params["q"] = arguments["query"]
            if arguments.get("country"):
                params["country"] = arguments["country"]
            if arguments.get("language"):
                params["language"] = arguments["language"]
            if arguments.get("from_date"):
                params["from_date"] = arguments["from_date"]
            if arguments.get("to_date"):
                params["to_date"] = arguments["to_date"]
            params["size"] = str(min(int(arguments.get("size", 10)), 50))
            resp = await client.get(f"{BASE_URL}/news", params=params)
            resp.raise_for_status()
            articles = _extract_articles(resp.json())
            return [TextContent(type="text", text=json.dumps(articles, ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
