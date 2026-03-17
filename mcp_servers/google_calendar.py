#!/usr/bin/env python3
"""MCP server: Google Calendar — list, create, get events.
Transport: stdio (launched by MCPDispatcher).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from google_auth_helper import get_service

app = Server("google-calendar")
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _svc():
    return get_service("calendar", "v3", SCOPES)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_events",
            description="List upcoming Google Calendar events.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Days ahead to look", "default": 7},
                    "max_results": {"type": "integer", "description": "Max events", "default": 20},
                },
            },
        ),
        Tool(
            name="create_event",
            description="Create a Google Calendar event.",
            inputSchema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Event title"},
                    "start": {"type": "string", "description": "Start ISO 8601"},
                    "end": {"type": "string", "description": "End ISO 8601"},
                    "description": {"type": "string", "description": "Event description"},
                },
                "required": ["summary", "start", "end"],
            },
        ),
        Tool(
            name="get_event",
            description="Get a Google Calendar event by ID.",
            inputSchema={
                "type": "object",
                "properties": {"event_id": {"type": "string"}},
                "required": ["event_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        svc = _svc()
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    if name == "list_events":
        now = datetime.now(timezone.utc).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=arguments.get("days", 7))).isoformat()
        resp = svc.events().list(
            calendarId="primary", timeMin=now, timeMax=end,
            maxResults=arguments.get("max_results", 20), singleEvents=True, orderBy="startTime",
        ).execute()
        events = [{
            "id": e["id"], "summary": e.get("summary", ""),
            "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "")),
            "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date", "")),
        } for e in resp.get("items", [])]
        return [TextContent(type="text", text=json.dumps(events, ensure_ascii=False))]

    elif name == "create_event":
        body = {
            "summary": arguments["summary"],
            "start": {"dateTime": arguments["start"]},
            "end": {"dateTime": arguments["end"]},
        }
        if arguments.get("description"):
            body["description"] = arguments["description"]
        event = svc.events().insert(calendarId="primary", body=body).execute()
        return [TextContent(type="text", text=json.dumps({"id": event["id"], "link": event.get("htmlLink", "")}))]

    elif name == "get_event":
        event = svc.events().get(calendarId="primary", eventId=arguments["event_id"]).execute()
        return [TextContent(type="text", text=json.dumps({
            "id": event["id"], "summary": event.get("summary", ""),
            "start": event.get("start", {}).get("dateTime", ""),
            "end": event.get("end", {}).get("dateTime", ""),
            "description": event.get("description", ""),
        }, ensure_ascii=False))]

    return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


async def main():
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
