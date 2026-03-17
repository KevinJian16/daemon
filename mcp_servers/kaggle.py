#!/usr/bin/env python3
"""MCP server: Kaggle — dataset and competition search.
Transport: stdio (launched by MCPDispatcher).
"""
from __future__ import annotations

import base64
import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

BASE_URL = "https://www.kaggle.com/api/v1"

app = Server("kaggle")


def _auth_headers() -> dict[str, str]:
    username = os.environ.get("KAGGLE_USERNAME", "")
    key = os.environ.get("KAGGLE_KEY", "")
    if not username or not key:
        raise RuntimeError("KAGGLE_USERNAME and KAGGLE_KEY must be set")
    creds = base64.b64encode(f"{username}:{key}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Accept": "application/json"}


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_datasets",
            description="Search Kaggle datasets by keyword.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "page": {"type": "integer", "description": "Page number (1-based)", "default": 1},
                    "page_size": {"type": "integer", "description": "Results per page (max 20)", "default": 10},
                    "sort_by": {
                        "type": "string",
                        "description": "Sort: hottest, votes, updated, active, published",
                        "default": "hottest",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="search_competitions",
            description="Search Kaggle competitions by keyword.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "page": {"type": "integer", "description": "Page number (1-based)", "default": 1},
                    "category": {
                        "type": "string",
                        "description": "Category: all, featured, research, getting-started, playground, analytics",
                        "default": "all",
                    },
                    "sort_by": {
                        "type": "string",
                        "description": "Sort: grouped, prize, earliestDeadline, latestDeadline, numberOfTeams, recentlyCreated",
                        "default": "latestDeadline",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_dataset_info",
            description="Get detailed info about a specific Kaggle dataset by owner/dataset-slug.",
            inputSchema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "Dataset owner username"},
                    "dataset": {"type": "string", "description": "Dataset slug name"},
                },
                "required": ["owner", "dataset"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=30, headers=_auth_headers()) as client:
        if name == "search_datasets":
            params = {
                "search": arguments["query"],
                "page": arguments.get("page", 1),
                "pageSize": min(int(arguments.get("page_size", 10)), 20),
                "sortBy": arguments.get("sort_by", "hottest"),
            }
            resp = await client.get(f"{BASE_URL}/datasets/list", params=params)
            resp.raise_for_status()
            _dk = ("ref", "title", "subtitle", "totalBytes", "downloadCount", "voteCount", "usabilityRating", "lastUpdated")
            datasets = [{**{k: d.get(k) for k in _dk}, "url": f"https://www.kaggle.com/datasets/{d.get('ref')}"} for d in resp.json()]
            return [TextContent(type="text", text=json.dumps(datasets, ensure_ascii=False, indent=2))]

        elif name == "search_competitions":
            params = {
                "search": arguments["query"],
                "page": arguments.get("page", 1),
                "category": arguments.get("category", "all"),
                "sortBy": arguments.get("sort_by", "latestDeadline"),
            }
            resp = await client.get(f"{BASE_URL}/competitions/list", params=params)
            resp.raise_for_status()
            _ck = ("ref", "title", "deadline", "reward", "teamCount", "category")
            comps = [{**{k: c.get(k) for k in _ck}, "description": c.get("description", "")[:300],
                       "url": f"https://www.kaggle.com/competitions/{c.get('ref')}"} for c in resp.json()]
            return [TextContent(type="text", text=json.dumps(comps, ensure_ascii=False, indent=2))]

        elif name == "get_dataset_info":
            owner = arguments["owner"]
            dataset = arguments["dataset"]
            resp = await client.get(f"{BASE_URL}/datasets/view/{owner}/{dataset}")
            resp.raise_for_status()
            data = resp.json()
            _ik = ("ref", "title", "subtitle", "totalBytes", "downloadCount", "voteCount",
                   "usabilityRating", "lastUpdated", "licenseName", "ownerName")
            info = {**{k: data.get(k) for k in _ik}, "description": data.get("description", "")[:2000],
                    "url": f"https://www.kaggle.com/datasets/{data.get('ref')}"}
            return [TextContent(type="text", text=json.dumps(info, ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
