#!/usr/bin/env python3
"""MCP server: intervals.icu — training/wellness data from Intervals.icu.

Provides tools for retrieving activities, wellness data, and athlete info
via the Intervals.icu REST API.
Transport: stdio (launched by MCPDispatcher).

Reference: https://intervals.icu/api/v1
"""
from __future__ import annotations

import base64
import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

BASE = "https://intervals.icu/api/v1"

app = Server("intervals-icu")


def _headers() -> dict[str, str]:
    api_key = os.environ.get("INTERVALS_API_KEY", "")
    # Intervals.icu uses HTTP Basic auth: API_KEY as username, api_key as password
    creds = base64.b64encode(f"API_KEY:{api_key}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Accept": "application/json"}


def _athlete_id() -> str:
    return os.environ.get("INTERVALS_ATHLETE_ID", "")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="intervals_get_activities",
            description="Get activities from Intervals.icu for a date range.",
            inputSchema={
                "type": "object",
                "properties": {
                    "oldest": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                    "newest": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                },
                "required": ["oldest", "newest"],
            },
        ),
        Tool(
            name="intervals_get_wellness",
            description="Get daily wellness data (sleep, HRV, weight, mood, etc.) for a date range.",
            inputSchema={
                "type": "object",
                "properties": {
                    "oldest": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                    "newest": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                },
                "required": ["oldest", "newest"],
            },
        ),
        Tool(
            name="intervals_get_athlete",
            description="Get athlete profile and settings from Intervals.icu.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    aid = _athlete_id()
    async with httpx.AsyncClient(timeout=30, headers=_headers()) as client:
        if name == "intervals_get_activities":
            params = {"oldest": arguments["oldest"], "newest": arguments["newest"]}
            resp = await client.get(f"{BASE}/athlete/{aid}/activities", params=params)
            resp.raise_for_status()
            return [TextContent(type="text", text=json.dumps(resp.json(), ensure_ascii=False, indent=2))]

        elif name == "intervals_get_wellness":
            resp = await client.get(
                f"{BASE}/athlete/{aid}/wellness",
                params={"oldest": arguments["oldest"], "newest": arguments["newest"]},
            )
            resp.raise_for_status()
            return [TextContent(type="text", text=json.dumps(resp.json(), ensure_ascii=False, indent=2))]

        elif name == "intervals_get_athlete":
            resp = await client.get(f"{BASE}/athlete/{aid}")
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
