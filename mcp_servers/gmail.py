#!/usr/bin/env python3
"""MCP server: Gmail — email search, read, and send via Gmail API.
Transport: stdio (launched by MCPDispatcher).
"""
from __future__ import annotations

import base64
import json
from email.mime.text import MIMEText

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from google_auth_helper import get_service

app = Server("gmail")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def _svc():
    return get_service("gmail", "v1", SCOPES)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_emails",
            description="Search Gmail messages using Gmail search syntax.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Gmail search query (e.g. 'from:alice subject:report')"},
                    "max_results": {"type": "integer", "description": "Max messages to return", "default": 10},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_email",
            description="Get full content of a Gmail message by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Gmail message ID"},
                },
                "required": ["message_id"],
            },
        ),
        Tool(
            name="send_email",
            description="Send an email via Gmail.",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Plain-text email body"},
                },
                "required": ["to", "subject", "body"],
            },
        ),
    ]


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        svc = _svc()
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    if name == "search_emails":
        query = arguments["query"]
        max_results = arguments.get("max_results", 10)
        resp = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        messages = resp.get("messages", [])
        results = []
        for m in messages[:max_results]:
            msg = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                              metadataHeaders=["From", "Subject", "Date"]).execute()
            hdrs = msg.get("payload", {}).get("headers", [])
            results.append({
                "id": m["id"],
                "from": _header(hdrs, "From"),
                "subject": _header(hdrs, "Subject"),
                "date": _header(hdrs, "Date"),
                "snippet": msg.get("snippet", ""),
            })
        return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False))]

    elif name == "get_email":
        msg = svc.users().messages().get(userId="me", id=arguments["message_id"], format="full").execute()
        hdrs = msg.get("payload", {}).get("headers", [])
        # Extract plain text body
        body = ""
        payload = msg.get("payload", {})
        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                    break
        elif payload.get("body", {}).get("data"):
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        result = {
            "id": msg["id"],
            "from": _header(hdrs, "From"),
            "to": _header(hdrs, "To"),
            "subject": _header(hdrs, "Subject"),
            "date": _header(hdrs, "Date"),
            "body": body[:5000],
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    elif name == "send_email":
        mime = MIMEText(arguments["body"])
        mime["to"] = arguments["to"]
        mime["subject"] = arguments["subject"]
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return [TextContent(type="text", text=json.dumps({"status": "sent", "to": arguments["to"]}))]

    return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
