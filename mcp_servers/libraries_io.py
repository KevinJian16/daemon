#!/usr/bin/env python3
"""MCP server: Libraries.io — package search, info, and dependency lookup.
Requires LIBRARIES_IO_API_KEY env var. Reference: https://libraries.io/api
Transport: stdio (launched by MCPDispatcher).
"""
from __future__ import annotations

import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

LIBS_BASE = "https://libraries.io/api"

app = Server("libraries-io")


def _api_key() -> str:
    if key := os.environ.get("LIBRARIES_IO_API_KEY"):
        return key
    raise RuntimeError("LIBRARIES_IO_API_KEY env var not set")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_packages",
            description="Search Libraries.io for open-source packages across all platforms.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "platforms": {
                        "type": "string",
                        "description": "Filter by platform (e.g. 'pypi', 'npm', 'cargo', 'maven')",
                    },
                    "sort": {
                        "type": "string",
                        "description": "Sort by: 'rank', 'stars', 'dependents_count', 'latest_release_published_at'",
                        "default": "rank",
                    },
                    "page": {"type": "integer", "description": "Page number", "default": 1},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_package",
            description="Get detailed info about a specific package on a platform.",
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": {"type": "string", "description": "Package platform (e.g. 'pypi', 'npm')"},
                    "name": {"type": "string", "description": "Package name"},
                },
                "required": ["platform", "name"],
            },
        ),
        Tool(
            name="get_dependencies",
            description="Get the dependency tree for a specific package version.",
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": {"type": "string", "description": "Package platform (e.g. 'pypi', 'npm')"},
                    "name": {"type": "string", "description": "Package name"},
                    "version": {"type": "string", "description": "Version string (defaults to 'latest')"},
                },
                "required": ["platform", "name"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        key = _api_key()
    except RuntimeError as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    async with httpx.AsyncClient(timeout=30) as client:
        if name == "search_packages":
            params: dict = {
                "q": arguments["query"],
                "api_key": key,
                "sort": arguments.get("sort", "rank"),
                "page": arguments.get("page", 1),
            }
            if arguments.get("platforms"):
                params["platforms"] = arguments["platforms"]
            resp = await client.get(f"{LIBS_BASE}/search", params=params)
            resp.raise_for_status()
            _keys = ("name", "platform", "homepage", "repository_url",
                     "stars", "rank", "latest_release_number", "dependents_count")
            packages = [
                {**{k: p.get(k) for k in _keys},
                 "description": (p.get("description") or "")[:200]}
                for p in resp.json()
            ]
            return [TextContent(type="text", text=json.dumps(packages, ensure_ascii=False, indent=2))]

        elif name == "get_package":
            platform = arguments["platform"]
            pkg_name = arguments["name"]
            resp = await client.get(
                f"{LIBS_BASE}/{platform}/{pkg_name}",
                params={"api_key": key},
            )
            resp.raise_for_status()
            data = resp.json()
            _pk = ("name", "platform", "description", "homepage", "repository_url",
                   "stars", "forks", "rank", "latest_release_number",
                   "latest_release_published_at", "dependents_count", "licenses", "language")
            info = {k: data.get(k) for k in _pk}
            info["versions_count"] = len(data.get("versions", []))
            return [TextContent(type="text", text=json.dumps(info, ensure_ascii=False, indent=2))]

        elif name == "get_dependencies":
            platform = arguments["platform"]
            pkg_name = arguments["name"]
            version = arguments.get("version", "latest")
            resp = await client.get(
                f"{LIBS_BASE}/{platform}/{pkg_name}/{version}/dependencies",
                params={"api_key": key},
            )
            resp.raise_for_status()
            data = resp.json()
            _dk = ("name", "platform", "requirements", "kind", "optional")
            deps = [{k: d.get(k) for k in _dk} for d in data.get("dependencies", [])]
            result = {"package": pkg_name, "version": version,
                      "dependencies_count": len(deps), "dependencies": deps}
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
