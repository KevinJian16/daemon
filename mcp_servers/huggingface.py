#!/usr/bin/env python3
"""MCP server: HuggingFace Hub — search models/datasets, get model info.
Public API, no auth required. Reference: https://huggingface.co/docs/hub/api
Transport: stdio (launched by MCPDispatcher).
"""
from __future__ import annotations

import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

HF_BASE = "https://huggingface.co/api"

app = Server("huggingface")


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Accept": "application/json"}
    if tok := os.environ.get("HF_TOKEN"):
        h["Authorization"] = f"Bearer {tok}"
    return h


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_models",
            description="Search HuggingFace Hub for models by query, task, or library.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query string"},
                    "filter_task": {"type": "string", "description": "Filter by task (e.g. 'text-generation', 'image-classification')"},
                    "filter_library": {"type": "string", "description": "Filter by library (e.g. 'pytorch', 'transformers')"},
                    "sort": {"type": "string", "description": "Sort by: 'downloads', 'likes', 'lastModified'", "default": "downloads"},
                    "limit": {"type": "integer", "description": "Max results (1-100)", "default": 10},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="search_datasets",
            description="Search HuggingFace Hub for datasets by query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query string"},
                    "sort": {"type": "string", "description": "Sort by: 'downloads', 'likes', 'lastModified'", "default": "downloads"},
                    "limit": {"type": "integer", "description": "Max results (1-100)", "default": 10},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_model_info",
            description="Get detailed info for a specific HuggingFace model by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_id": {"type": "string", "description": "Model ID (e.g. 'meta-llama/Llama-2-7b-hf')"},
                },
                "required": ["model_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=30, headers=_headers()) as client:
        if name == "search_models":
            params: dict = {
                "search": arguments["query"],
                "sort": arguments.get("sort", "downloads"),
                "direction": "-1",
                "limit": min(int(arguments.get("limit", 10)), 100),
            }
            if arguments.get("filter_task"):
                params["pipeline_tag"] = arguments["filter_task"]
            if arguments.get("filter_library"):
                params["library"] = arguments["filter_library"]
            resp = await client.get(f"{HF_BASE}/models", params=params)
            resp.raise_for_status()
            _mk = ("id", "pipeline_tag", "downloads", "likes", "lastModified")
            models = [{**{k: m.get(k) for k in _mk}, "tags": m.get("tags", [])[:10]}
                      for m in resp.json()]
            return [TextContent(type="text", text=json.dumps(models, ensure_ascii=False, indent=2))]

        elif name == "search_datasets":
            params = {
                "search": arguments["query"],
                "sort": arguments.get("sort", "downloads"),
                "direction": "-1",
                "limit": min(int(arguments.get("limit", 10)), 100),
            }
            resp = await client.get(f"{HF_BASE}/datasets", params=params)
            resp.raise_for_status()
            _dk = ("id", "downloads", "likes", "lastModified")
            datasets = [{**{k: d.get(k) for k in _dk}, "tags": d.get("tags", [])[:10]}
                        for d in resp.json()]
            return [TextContent(type="text", text=json.dumps(datasets, ensure_ascii=False, indent=2))]

        elif name == "get_model_info":
            model_id = arguments["model_id"]
            resp = await client.get(f"{HF_BASE}/models/{model_id}")
            resp.raise_for_status()
            data = resp.json()
            _ik = ("id", "pipeline_tag", "library_name", "downloads", "likes", "lastModified")
            info = {k: data.get(k) for k in _ik}
            info["tags"] = data.get("tags", [])
            info["siblings"] = [s.get("rfilename") for s in data.get("siblings", [])[:20]]
            info["card_data"] = data.get("cardData")
            return [TextContent(type="text", text=json.dumps(info, ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
