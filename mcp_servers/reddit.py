#!/usr/bin/env python3
"""MCP server: Reddit — read subreddit posts and comments via JSON API.

Provides tools for browsing Reddit content using the public JSON API
(append .json to any Reddit URL). No authentication required for read-only.
Transport: stdio (launched by MCPDispatcher).

Reference: https://www.reddit.com/dev/api/
"""
from __future__ import annotations

import json

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

app = Server("reddit")

# Reddit requires a descriptive User-Agent; generic ones get 429'd.
HEADERS = {"User-Agent": "daemon-mcp:v1.0 (by /u/daemon-bot)", "Accept": "application/json"}


def _slim_post(p: dict) -> dict:
    d = p.get("data", p)
    return {
        "title": d.get("title", ""),
        "author": d.get("author", ""),
        "subreddit": d.get("subreddit", ""),
        "score": d.get("score", 0),
        "upvote_ratio": d.get("upvote_ratio", 0),
        "num_comments": d.get("num_comments", 0),
        "url": d.get("url", ""),
        "permalink": f"https://www.reddit.com{d.get('permalink', '')}",
        "created_utc": d.get("created_utc"),
        "selftext": (d.get("selftext") or "")[:500],
        "is_self": d.get("is_self", False),
        "link_flair_text": d.get("link_flair_text", ""),
    }


def _slim_comment(c: dict) -> dict:
    d = c.get("data", c)
    return {
        "author": d.get("author", ""),
        "score": d.get("score", 0),
        "body": (d.get("body") or "")[:500],
        "created_utc": d.get("created_utc"),
        "permalink": f"https://www.reddit.com{d.get('permalink', '')}",
    }


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="reddit_subreddit",
            description="Get hot or top posts from a subreddit.",
            inputSchema={
                "type": "object",
                "properties": {
                    "subreddit": {"type": "string", "description": "Subreddit name (without r/)"},
                    "sort": {"type": "string", "description": "Sort: hot, new, top, rising", "default": "hot"},
                    "time": {"type": "string", "description": "Time filter for 'top': hour, day, week, month, year, all", "default": "week"},
                    "limit": {"type": "integer", "description": "Number of posts (1-25)", "default": 10},
                },
                "required": ["subreddit"],
            },
        ),
        Tool(
            name="reddit_post_comments",
            description="Get comments for a specific Reddit post by its permalink or post ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "permalink": {
                        "type": "string",
                        "description": "Post permalink path (e.g. '/r/python/comments/abc123/title/') or full URL",
                    },
                    "sort": {"type": "string", "description": "Sort: best, top, new, controversial", "default": "best"},
                    "limit": {"type": "integer", "description": "Number of top-level comments (1-25)", "default": 10},
                },
                "required": ["permalink"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=30, headers=HEADERS, follow_redirects=True) as client:
        if name == "reddit_subreddit":
            sub = arguments["subreddit"].strip("/").removeprefix("r/")
            sort = arguments.get("sort", "hot")
            limit = min(int(arguments.get("limit", 10)), 25)
            params: dict = {"limit": limit, "raw_json": 1}
            if sort == "top":
                params["t"] = arguments.get("time", "week")
            resp = await client.get(f"https://www.reddit.com/r/{sub}/{sort}.json", params=params)
            resp.raise_for_status()
            children = resp.json().get("data", {}).get("children", [])
            posts = [_slim_post(c) for c in children]
            return [TextContent(type="text", text=json.dumps(posts, ensure_ascii=False, indent=2))]

        elif name == "reddit_post_comments":
            permalink = arguments["permalink"]
            # Normalize: strip domain, ensure trailing slash
            if "reddit.com" in permalink:
                permalink = permalink.split("reddit.com")[-1]
            if not permalink.endswith("/"):
                permalink += "/"
            sort = arguments.get("sort", "best")
            limit = min(int(arguments.get("limit", 10)), 25)
            resp = await client.get(
                f"https://www.reddit.com{permalink}.json",
                params={"sort": sort, "limit": limit, "raw_json": 1},
            )
            resp.raise_for_status()
            data = resp.json()
            # Reddit returns [post_listing, comment_listing]
            post_data = data[0]["data"]["children"][0] if data and data[0].get("data", {}).get("children") else {}
            comments_data = data[1]["data"]["children"] if len(data) > 1 else []
            result = {
                "post": _slim_post(post_data) if post_data else {},
                "comments": [
                    _slim_comment(c) for c in comments_data
                    if c.get("kind") == "t1"  # skip "more" stubs
                ][:limit],
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
