#!/usr/bin/env python3
"""MCP server: Strava API v3 — athlete activities and stats.

Provides tools for retrieving athlete activities, activity details,
and athlete stats via the Strava API.
Transport: stdio (launched by MCPDispatcher).

Reference: https://developers.strava.com/docs/reference/
"""
from __future__ import annotations

import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

BASE = "https://www.strava.com/api/v3"

app = Server("strava")


def _headers() -> dict[str, str]:
    token = os.environ.get("STRAVA_ACCESS_TOKEN", "")
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="strava_get_activities",
            description="Get logged-in athlete's recent activities.",
            inputSchema={
                "type": "object",
                "properties": {
                    "per_page": {"type": "integer", "description": "Results per page (1-200)", "default": 30},
                    "page": {"type": "integer", "description": "Page number", "default": 1},
                    "after": {"type": "integer", "description": "Unix epoch timestamp — only activities after this time"},
                    "before": {"type": "integer", "description": "Unix epoch timestamp — only activities before this time"},
                },
            },
        ),
        Tool(
            name="strava_get_activity",
            description="Get detailed info for a single Strava activity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "activity_id": {"type": "integer", "description": "Strava activity ID"},
                },
                "required": ["activity_id"],
            },
        ),
        Tool(
            name="strava_get_athlete_stats",
            description="Get athlete's aggregated stats (totals, recent runs/rides/swims).",
            inputSchema={
                "type": "object",
                "properties": {
                    "athlete_id": {"type": "integer", "description": "Athlete ID (use 0 or omit for authenticated athlete)"},
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=30, headers=_headers()) as client:
        if name == "strava_get_activities":
            params: dict = {
                "per_page": min(int(arguments.get("per_page", 30)), 200),
                "page": int(arguments.get("page", 1)),
            }
            if arguments.get("after"):
                params["after"] = arguments["after"]
            if arguments.get("before"):
                params["before"] = arguments["before"]
            resp = await client.get(f"{BASE}/athlete/activities", params=params)
            resp.raise_for_status()
            return [TextContent(type="text", text=json.dumps(resp.json(), ensure_ascii=False, indent=2))]

        elif name == "strava_get_activity":
            aid = arguments["activity_id"]
            resp = await client.get(f"{BASE}/activities/{aid}")
            resp.raise_for_status()
            return [TextContent(type="text", text=json.dumps(resp.json(), ensure_ascii=False, indent=2))]

        elif name == "strava_get_athlete_stats":
            # Get authenticated athlete ID first if not provided
            athlete_id = arguments.get("athlete_id", 0)
            if not athlete_id:
                me = await client.get(f"{BASE}/athlete")
                me.raise_for_status()
                athlete_id = me.json()["id"]
            resp = await client.get(f"{BASE}/athletes/{athlete_id}/stats")
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
