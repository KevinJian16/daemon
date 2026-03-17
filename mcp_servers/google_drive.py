#!/usr/bin/env python3
"""MCP server: Google Drive — file listing, download metadata, upload.
Transport: stdio (launched by MCPDispatcher).
"""
from __future__ import annotations

import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from google_auth_helper import get_service

app = Server("google-drive")
SCOPES = ["https://www.googleapis.com/auth/drive"]


def _svc():
    return get_service("drive", "v3", SCOPES)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_files",
            description="List files in Google Drive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Drive search query (e.g. \"name contains 'report'\")"},
                    "max_results": {"type": "integer", "description": "Max files", "default": 20},
                },
            },
        ),
        Tool(
            name="get_file",
            description="Get Google Drive file metadata by ID.",
            inputSchema={
                "type": "object",
                "properties": {"file_id": {"type": "string", "description": "Drive file ID"}},
                "required": ["file_id"],
            },
        ),
        Tool(
            name="upload_file",
            description="Upload a local file to Google Drive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "local_path": {"type": "string", "description": "Local file path to upload"},
                    "name": {"type": "string", "description": "File name in Drive (optional, defaults to filename)"},
                    "folder_id": {"type": "string", "description": "Parent folder ID (optional)"},
                },
                "required": ["local_path"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        svc = _svc()
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    if name == "list_files":
        params = {"pageSize": arguments.get("max_results", 20),
                  "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink)"}
        if arguments.get("query"):
            params["q"] = arguments["query"]
        resp = svc.files().list(**params).execute()
        files = [{
            "id": f["id"], "name": f["name"], "mimeType": f.get("mimeType", ""),
            "modified": f.get("modifiedTime", ""), "size": f.get("size", ""),
            "link": f.get("webViewLink", ""),
        } for f in resp.get("files", [])]
        return [TextContent(type="text", text=json.dumps(files, ensure_ascii=False))]

    elif name == "get_file":
        f = svc.files().get(fileId=arguments["file_id"],
                            fields="id,name,mimeType,modifiedTime,size,webViewLink,parents").execute()
        return [TextContent(type="text", text=json.dumps({
            "id": f["id"], "name": f["name"], "mimeType": f.get("mimeType", ""),
            "modified": f.get("modifiedTime", ""), "size": f.get("size", ""),
            "link": f.get("webViewLink", ""), "parents": f.get("parents", []),
        }, ensure_ascii=False))]

    elif name == "upload_file":
        from googleapiclient.http import MediaFileUpload
        from pathlib import Path
        local = Path(arguments["local_path"])
        if not local.exists():
            return [TextContent(type="text", text=json.dumps({"error": f"File not found: {local}"}))]
        meta = {"name": arguments.get("name", local.name)}
        if arguments.get("folder_id"):
            meta["parents"] = [arguments["folder_id"]]
        media = MediaFileUpload(str(local))
        f = svc.files().create(body=meta, media_body=media, fields="id,name,webViewLink").execute()
        return [TextContent(type="text", text=json.dumps({
            "id": f["id"], "name": f["name"], "link": f.get("webViewLink", ""),
        }))]

    return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


async def main():
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
