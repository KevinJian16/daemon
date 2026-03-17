#!/usr/bin/env python3
"""MCP server: LanguageTool — grammar and style checking.

Provides tools for checking text grammar/style and listing supported languages
via a self-hosted LanguageTool instance or the public API.
Transport: stdio (launched by MCPDispatcher).

Reference: https://languagetool.org/http-api/
"""
from __future__ import annotations

import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

LT_BASE = os.environ.get("LANGUAGETOOL_URL", "http://localhost:8081/v2")

app = Server("languagetool")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="lt_check_text",
            description="Check text for grammar, spelling, and style issues using LanguageTool.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to check"},
                    "language": {
                        "type": "string",
                        "description": "Language code (e.g. 'en-US', 'zh-CN', 'auto')",
                        "default": "auto",
                    },
                    "disabled_rules": {
                        "type": "string",
                        "description": "Comma-separated rule IDs to disable",
                    },
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="lt_languages",
            description="Get list of languages supported by this LanguageTool instance.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=30) as client:
        if name == "lt_check_text":
            data = {
                "text": arguments["text"],
                "language": arguments.get("language", "auto"),
            }
            if arguments.get("disabled_rules"):
                data["disabledRules"] = arguments["disabled_rules"]
            resp = await client.post(f"{LT_BASE}/check", data=data)
            resp.raise_for_status()
            result = resp.json()

            # Simplify output: extract matches with context
            matches = []
            for m in result.get("matches", []):
                matches.append({
                    "message": m.get("message", ""),
                    "short_message": m.get("shortMessage", ""),
                    "offset": m.get("offset", 0),
                    "length": m.get("length", 0),
                    "replacements": [r["value"] for r in m.get("replacements", [])[:5]],
                    "rule_id": m.get("rule", {}).get("id", ""),
                    "rule_category": m.get("rule", {}).get("category", {}).get("name", ""),
                    "context": m.get("context", {}).get("text", ""),
                })
            output = {
                "language_detected": result.get("language", {}).get("detectedLanguage", {}).get("name", ""),
                "match_count": len(matches),
                "matches": matches,
            }
            return [TextContent(type="text", text=json.dumps(output, ensure_ascii=False, indent=2))]

        elif name == "lt_languages":
            resp = await client.get(f"{LT_BASE}/languages")
            resp.raise_for_status()
            langs = [{"code": l["longCode"], "name": l["name"]} for l in resp.json()]
            return [TextContent(type="text", text=json.dumps(langs, ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
