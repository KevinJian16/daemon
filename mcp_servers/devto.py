#!/usr/bin/env python3
"""MCP server: Dev.to (Forem) API — create and retrieve articles.

Provides tools for publishing and retrieving articles on Dev.to
via the Forem API v1.
Transport: stdio (launched by MCPDispatcher).

Reference: https://developers.forem.com/api/v1
"""
from __future__ import annotations

import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

BASE = "https://dev.to/api"

app = Server("devto")


def _headers() -> dict[str, str]:
    key = os.environ.get("DEVTO_API_KEY", "")
    return {"api-key": key, "Content-Type": "application/json", "Accept": "application/json"}


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="devto_create_article",
            description="Create or publish an article on Dev.to.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Article title"},
                    "body_markdown": {"type": "string", "description": "Article body in Markdown"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Up to 4 tags",
                    },
                    "published": {"type": "boolean", "description": "Publish immediately", "default": False},
                    "series": {"type": "string", "description": "Series name (optional)"},
                    "canonical_url": {"type": "string", "description": "Canonical URL (optional)"},
                },
                "required": ["title", "body_markdown"],
            },
        ),
        Tool(
            name="devto_get_articles",
            description="Get published articles (your own or by tag/username).",
            inputSchema={
                "type": "object",
                "properties": {
                    "tag": {"type": "string", "description": "Filter by tag"},
                    "username": {"type": "string", "description": "Filter by username"},
                    "page": {"type": "integer", "description": "Page number", "default": 1},
                    "per_page": {"type": "integer", "description": "Results per page (1-100)", "default": 10},
                    "state": {"type": "string", "enum": ["fresh", "rising", "all"], "description": "Article state"},
                },
            },
        ),
        Tool(
            name="devto_get_article",
            description="Get a single Dev.to article by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "article_id": {"type": "integer", "description": "Article ID"},
                },
                "required": ["article_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=30, headers=_headers()) as client:
        if name == "devto_create_article":
            payload = {
                "article": {
                    "title": arguments["title"],
                    "body_markdown": arguments["body_markdown"],
                    "published": arguments.get("published", False),
                }
            }
            if arguments.get("tags"):
                payload["article"]["tags"] = arguments["tags"][:4]
            if arguments.get("series"):
                payload["article"]["series"] = arguments["series"]
            if arguments.get("canonical_url"):
                payload["article"]["canonical_url"] = arguments["canonical_url"]
            resp = await client.post(f"{BASE}/articles", json=payload)
            resp.raise_for_status()
            data = resp.json()
            result = {"id": data["id"], "url": data["url"], "title": data["title"]}
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "devto_get_articles":
            params: dict = {
                "page": int(arguments.get("page", 1)),
                "per_page": min(int(arguments.get("per_page", 10)), 100),
            }
            if arguments.get("tag"):
                params["tag"] = arguments["tag"]
            if arguments.get("username"):
                params["username"] = arguments["username"]
            if arguments.get("state"):
                params["state"] = arguments["state"]
            resp = await client.get(f"{BASE}/articles", params=params)
            resp.raise_for_status()
            articles = [
                {"id": a["id"], "title": a["title"], "url": a["url"],
                 "tags": a.get("tag_list", []), "published_at": a.get("published_at", "")}
                for a in resp.json()
            ]
            return [TextContent(type="text", text=json.dumps(articles, ensure_ascii=False, indent=2))]

        elif name == "devto_get_article":
            aid = arguments["article_id"]
            resp = await client.get(f"{BASE}/articles/{aid}")
            resp.raise_for_status()
            return [TextContent(type="text", text=json.dumps(resp.json(), ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
