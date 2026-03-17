#!/usr/bin/env python3
"""MCP server: matplotlib chart — generate charts and upload to MinIO.

Provides a tool to create various chart types (bar, line, pie, scatter, etc.)
using matplotlib, then upload the resulting PNG to MinIO and return the URL.
Transport: stdio (launched by MCPDispatcher).
"""
from __future__ import annotations

import io
import json
import os
import uuid

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

app = Server("matplotlib-chart")

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "127.0.0.1:9000")
MINIO_ACCESS = os.environ.get("MINIO_ROOT_USER", "")
MINIO_SECRET = os.environ.get("MINIO_ROOT_PASSWORD", "")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "daemon-artifacts")


def _upload_to_minio(data: bytes, object_name: str, content_type: str) -> str:
    """Upload bytes to MinIO and return the URL."""
    from minio import Minio

    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS,
        secret_key=MINIO_SECRET,
        secure=False,
    )
    if not client.bucket_exists(MINIO_BUCKET):
        client.make_bucket(MINIO_BUCKET)
    client.put_object(MINIO_BUCKET, object_name, io.BytesIO(data), len(data), content_type=content_type)
    return f"http://{MINIO_ENDPOINT}/{MINIO_BUCKET}/{object_name}"


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="create_chart",
            description="Create a chart with matplotlib, upload PNG to MinIO, return URL.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chart_type": {
                        "type": "string",
                        "enum": ["bar", "line", "pie", "scatter", "hist"],
                        "description": "Chart type",
                    },
                    "data": {
                        "type": "object",
                        "description": "Chart data: {x: [...], y: [...]} for bar/line/scatter, {values: [...]} for pie/hist",
                    },
                    "labels": {
                        "type": "object",
                        "description": "Labels: {x: 'X axis', y: 'Y axis', legend: ['Series 1']}",
                    },
                    "title": {"type": "string", "description": "Chart title"},
                    "figsize": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "[width, height] in inches",
                        "default": [10, 6],
                    },
                },
                "required": ["chart_type", "data"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "create_chart":
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    chart_type = arguments["chart_type"]
    data = arguments["data"]
    labels = arguments.get("labels", {})
    title = arguments.get("title", "")
    figsize = tuple(arguments.get("figsize", [10, 6]))

    fig, ax = plt.subplots(figsize=figsize)

    if chart_type == "bar":
        ax.bar(data.get("x", range(len(data["y"]))), data["y"])
    elif chart_type == "line":
        ax.plot(data.get("x", range(len(data["y"]))), data["y"], marker="o")
    elif chart_type == "scatter":
        ax.scatter(data["x"], data["y"])
    elif chart_type == "pie":
        ax.pie(data["values"], labels=data.get("labels"), autopct="%1.1f%%")
    elif chart_type == "hist":
        ax.hist(data["values"], bins=data.get("bins", 10))

    if title:
        ax.set_title(title)
    if labels.get("x"):
        ax.set_xlabel(labels["x"])
    if labels.get("y"):
        ax.set_ylabel(labels["y"])
    if labels.get("legend"):
        ax.legend(labels["legend"])

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()

    obj_name = f"charts/{uuid.uuid4().hex}.png"
    url = _upload_to_minio(png_bytes, obj_name, "image/png")

    result = {"url": url, "object": obj_name, "size_bytes": len(png_bytes)}
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
