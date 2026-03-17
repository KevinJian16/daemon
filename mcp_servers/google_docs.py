#!/usr/bin/env python3
"""MCP server: Google Docs — document read and create.
Transport: stdio (launched by MCPDispatcher).
"""
from __future__ import annotations

import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from google_auth_helper import get_service

app = Server("google-docs")
SCOPES = ["https://www.googleapis.com/auth/documents"]


def _svc():
    return get_service("docs", "v1", SCOPES)


def _extract_text(doc: dict) -> str:
    """Extract plain text from Google Docs document body."""
    text = []
    for elem in doc.get("body", {}).get("content", []):
        if "paragraph" in elem:
            for run in elem["paragraph"].get("elements", []):
                if "textRun" in run:
                    text.append(run["textRun"]["content"])
    return "".join(text)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_document",
            description="Get a Google Doc's text content by document ID.",
            inputSchema={
                "type": "object",
                "properties": {"document_id": {"type": "string", "description": "Google Doc ID"}},
                "required": ["document_id"],
            },
        ),
        Tool(
            name="create_document",
            description="Create a new Google Doc with a title.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Document title"},
                    "body": {"type": "string", "description": "Initial plain text content"},
                },
                "required": ["title"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        svc = _svc()
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    if name == "get_document":
        doc = svc.documents().get(documentId=arguments["document_id"]).execute()
        return [TextContent(type="text", text=json.dumps({
            "title": doc.get("title", ""),
            "text": _extract_text(doc)[:10000],
        }, ensure_ascii=False))]

    elif name == "create_document":
        doc = svc.documents().create(body={"title": arguments["title"]}).execute()
        doc_id = doc["documentId"]
        if arguments.get("body"):
            svc.documents().batchUpdate(documentId=doc_id, body={
                "requests": [{"insertText": {"location": {"index": 1}, "text": arguments["body"]}}]
            }).execute()
        return [TextContent(type="text", text=json.dumps({
            "document_id": doc_id,
            "title": arguments["title"],
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        }))]

    return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


async def main():
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
