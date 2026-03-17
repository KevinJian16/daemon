#!/usr/bin/env python3
"""MCP server: RSS Reader — parse RSS/Atom feeds and OPML subscription lists.

Provides tools for fetching and parsing RSS/Atom feeds into structured data,
and for reading OPML files to extract feed lists.
Transport: stdio (launched by MCPDispatcher).

Dependencies: feedparser, httpx
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import feedparser
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

app = Server("rss-reader")


def _slim_entry(entry: dict) -> dict:
    """Extract key fields from a feedparser entry."""
    return {
        "title": entry.get("title", ""),
        "link": entry.get("link", ""),
        "published": entry.get("published", entry.get("updated", "")),
        "author": entry.get("author", ""),
        "summary": (entry.get("summary") or "")[:500],
        "tags": [t.get("term", "") for t in (entry.get("tags") or [])],
        "id": entry.get("id", ""),
    }


def _parse_opml_outlines(element: ET.Element) -> list[dict]:
    """Recursively parse OPML outline elements."""
    feeds = []
    for outline in element.findall("outline"):
        xml_url = outline.get("xmlUrl", "")
        if xml_url:
            feeds.append({
                "title": outline.get("title", outline.get("text", "")),
                "xml_url": xml_url,
                "html_url": outline.get("htmlUrl", ""),
                "type": outline.get("type", ""),
                "category": outline.get("category", ""),
            })
        # Recurse into folders
        children = _parse_opml_outlines(outline)
        if children and not xml_url:
            folder_name = outline.get("title", outline.get("text", ""))
            for child in children:
                child["folder"] = folder_name
            feeds.extend(children)
        elif children:
            feeds.extend(children)
    return feeds


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="rss_parse_feed",
            description="Fetch and parse an RSS/Atom feed URL, returning structured entries.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "RSS/Atom feed URL"},
                    "limit": {"type": "integer", "description": "Max entries to return (1-50)", "default": 20},
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="rss_parse_opml",
            description="Parse an OPML file (local path or URL) and return the list of feed subscriptions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "OPML file path or URL"},
                },
                "required": ["source"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "rss_parse_feed":
        url = arguments["url"]
        limit = min(int(arguments.get("limit", 20)), 50)
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content = resp.text
        feed = feedparser.parse(content)
        result = {
            "feed": {
                "title": feed.feed.get("title", ""),
                "link": feed.feed.get("link", ""),
                "description": feed.feed.get("description", ""),
                "updated": feed.feed.get("updated", ""),
                "language": feed.feed.get("language", ""),
            },
            "entries_count": len(feed.entries),
            "entries": [_slim_entry(e) for e in feed.entries[:limit]],
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "rss_parse_opml":
        source = arguments["source"]
        if source.startswith("http://") or source.startswith("https://"):
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(source)
                resp.raise_for_status()
                content = resp.text
        else:
            with open(source, "r", encoding="utf-8") as f:
                content = f.read()
        root = ET.fromstring(content)
        body = root.find("body")
        if body is None:
            return [TextContent(type="text", text=json.dumps({"error": "No <body> element found in OPML"}))]
        feeds = _parse_opml_outlines(body)
        result = {"feed_count": len(feeds), "feeds": feeds}
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
