#!/usr/bin/env python3
"""MCP server: Firecrawl web scraping — URL → clean Markdown.

Provides tools to scrape web pages via the local Firecrawl instance
and return clean Markdown content.

Transport: stdio (launched by MCPDispatcher).
"""
from __future__ import annotations

import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

FIRECRAWL_URL = os.environ.get("FIRECRAWL_URL", "http://127.0.0.1:3002")

app = Server("firecrawl-scrape")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="firecrawl_scrape",
            description="Scrape a web page and return clean Markdown content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to scrape"},
                    "formats": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Output formats: 'markdown', 'html', 'rawHtml'",
                        "default": ["markdown"],
                    },
                    "only_main_content": {
                        "type": "boolean",
                        "description": "Extract only main content (remove nav, footer, etc.)",
                        "default": True,
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="firecrawl_crawl",
            description="Crawl a website starting from a URL, following links up to a depth limit.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Starting URL to crawl"},
                    "max_depth": {"type": "integer", "description": "Max crawl depth", "default": 2},
                    "limit": {"type": "integer", "description": "Max pages to crawl", "default": 10},
                },
                "required": ["url"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(base_url=FIRECRAWL_URL, timeout=120) as client:
        if name == "firecrawl_scrape":
            payload = {
                "url": arguments["url"],
                "formats": arguments.get("formats", ["markdown"]),
                "onlyMainContent": arguments.get("only_main_content", True),
            }
            resp = await client.post("/v1/scrape", json=payload)
            resp.raise_for_status()
            data = resp.json()

            # Extract markdown from response
            result = data.get("data", {})
            md = result.get("markdown", "")
            metadata = result.get("metadata", {})
            output = {
                "title": metadata.get("title", ""),
                "url": arguments["url"],
                "markdown": md[:50000],  # Cap at 50k chars
                "word_count": len(md.split()),
            }
            return [TextContent(type="text", text=json.dumps(output, ensure_ascii=False, indent=2))]

        elif name == "firecrawl_crawl":
            payload = {
                "url": arguments["url"],
                "maxDepth": arguments.get("max_depth", 2),
                "limit": arguments.get("limit", 10),
            }
            resp = await client.post("/v1/crawl", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
