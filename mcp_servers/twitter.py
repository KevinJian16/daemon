#!/usr/bin/env python3
"""MCP server: Twitter/X API v2 — search and retrieve tweets.

Provides tools for searching recent tweets, getting user tweets,
and retrieving tweet details via the Twitter API v2.
Transport: stdio (launched by MCPDispatcher).

Reference: https://developer.x.com/en/docs/twitter-api
"""
from __future__ import annotations

import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

BASE = "https://api.twitter.com/2"
TWEET_FIELDS = "created_at,public_metrics,author_id,conversation_id,lang"
USER_FIELDS = "name,username,description,public_metrics,verified"

app = Server("twitter")


def _headers() -> dict[str, str]:
    token = os.environ.get("TWITTER_BEARER_TOKEN", "")
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="twitter_search_recent",
            description="Search recent tweets (last 7 days) by query string.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Twitter search query (supports operators)"},
                    "max_results": {"type": "integer", "description": "Results per page (10-100)", "default": 10},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="twitter_user_tweets",
            description="Get recent tweets by a Twitter user ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Twitter user ID (numeric)"},
                    "max_results": {"type": "integer", "description": "Results (5-100)", "default": 10},
                },
                "required": ["user_id"],
            },
        ),
        Tool(
            name="twitter_get_tweet",
            description="Get details for a single tweet by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tweet_id": {"type": "string", "description": "Tweet ID"},
                },
                "required": ["tweet_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=30, headers=_headers()) as client:
        if name == "twitter_search_recent":
            params = {
                "query": arguments["query"],
                "max_results": max(10, min(int(arguments.get("max_results", 10)), 100)),
                "tweet.fields": TWEET_FIELDS,
                "expansions": "author_id",
                "user.fields": USER_FIELDS,
            }
            resp = await client.get(f"{BASE}/tweets/search/recent", params=params)
            resp.raise_for_status()
            return [TextContent(type="text", text=json.dumps(resp.json(), ensure_ascii=False, indent=2))]

        elif name == "twitter_user_tweets":
            uid = arguments["user_id"]
            params = {
                "max_results": max(5, min(int(arguments.get("max_results", 10)), 100)),
                "tweet.fields": TWEET_FIELDS,
            }
            resp = await client.get(f"{BASE}/users/{uid}/tweets", params=params)
            resp.raise_for_status()
            return [TextContent(type="text", text=json.dumps(resp.json(), ensure_ascii=False, indent=2))]

        elif name == "twitter_get_tweet":
            tid = arguments["tweet_id"]
            params = {
                "tweet.fields": TWEET_FIELDS,
                "expansions": "author_id",
                "user.fields": USER_FIELDS,
            }
            resp = await client.get(f"{BASE}/tweets/{tid}", params=params)
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
