#!/usr/bin/env python3
"""MCP server: Docker control — container management via docker CLI.

Provides tools to list, restart, and inspect containers using the docker CLI.
Transport: stdio (launched by MCPDispatcher).
"""
from __future__ import annotations

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

app = Server("docker-control")


async def _run_docker(*args: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a docker CLI command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "docker", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_containers",
            description="List Docker containers. Shows all containers by default (including stopped).",
            inputSchema={
                "type": "object",
                "properties": {
                    "all": {
                        "type": "boolean",
                        "description": "Include stopped containers",
                        "default": True,
                    },
                    "filter": {
                        "type": "string",
                        "description": "Filter expression (e.g. 'name=postgres', 'status=running')",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="restart_container",
            description="Restart a Docker container by name or ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "container": {
                        "type": "string",
                        "description": "Container name or ID",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Seconds to wait before killing (default 10)",
                        "default": 10,
                    },
                },
                "required": ["container"],
            },
        ),
        Tool(
            name="get_container_logs",
            description="Get recent logs from a Docker container.",
            inputSchema={
                "type": "object",
                "properties": {
                    "container": {
                        "type": "string",
                        "description": "Container name or ID",
                    },
                    "tail": {
                        "type": "integer",
                        "description": "Number of lines from the end (default 100)",
                        "default": 100,
                    },
                    "since": {
                        "type": "string",
                        "description": "Show logs since timestamp or relative (e.g. '10m', '1h', '2024-01-01T00:00:00')",
                    },
                },
                "required": ["container"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "list_containers":
        args = ["ps", "--format", "json", "--no-trunc"]
        if arguments.get("all", True):
            args.append("-a")
        if arguments.get("filter"):
            args.extend(["-f", arguments["filter"]])
        rc, stdout, stderr = await _run_docker(*args)
        if rc != 0:
            return [TextContent(type="text", text=json.dumps({"error": stderr}, ensure_ascii=False))]
        # docker ps --format json outputs one JSON object per line
        containers = []
        for line in stdout.strip().splitlines():
            if line.strip():
                containers.append(json.loads(line))
        return [TextContent(type="text", text=json.dumps(containers, ensure_ascii=False, indent=2))]

    elif name == "restart_container":
        container = arguments["container"]
        t = str(arguments.get("timeout", 10))
        rc, stdout, stderr = await _run_docker("restart", "-t", t, container)
        if rc != 0:
            result = {"success": False, "error": stderr.strip()}
        else:
            result = {"success": True, "container": container, "message": stdout.strip()}
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    elif name == "get_container_logs":
        container = arguments["container"]
        tail = str(arguments.get("tail", 100))
        args = ["logs", "--tail", tail]
        if arguments.get("since"):
            args.extend(["--since", arguments["since"]])
        args.append(container)
        rc, stdout, stderr = await _run_docker(*args, timeout=15)
        if rc != 0:
            return [TextContent(type="text", text=json.dumps({"error": stderr}, ensure_ascii=False))]
        # Docker sends some logs to stderr (e.g. container stderr stream)
        logs = (stdout + stderr)[-30000:]  # Cap at 30k chars
        result = {"container": container, "logs": logs}
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
