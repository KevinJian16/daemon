#!/usr/bin/env python3
"""MCP server: macOS control — system control via osascript/AppleScript.

Provides tools to open files/URLs, launch apps, query frontmost app,
and position windows using a 15% left-margin layout.
Transport: stdio (launched by MCPDispatcher).
"""
from __future__ import annotations

import json
import subprocess

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

app = Server("macos-control")


def _osascript(script: str) -> str:
    """Run AppleScript via osascript and return stdout."""
    r = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=15,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"osascript exit {r.returncode}")
    return r.stdout.strip()


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="open_file",
            description="Open a file or URL with the default application.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path or URL to open"},
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="open_app",
            description="Launch a macOS application by name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Application name, e.g. 'Safari'"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="get_frontmost_app",
            description="Get the name of the currently frontmost application.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="position_window",
            description=(
                "Position the frontmost window using a 15% left-margin layout. "
                "The window is placed at x=15% of screen width, y=25px (menu bar), "
                "filling the remaining space to the right and bottom."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Target app name. If omitted, uses frontmost app.",
                    },
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "open_file":
        path = arguments["path"]
        if path.startswith("http://") or path.startswith("https://"):
            _osascript(f'open location "{path}"')
        else:
            _osascript(f'do shell script "open " & quoted form of "{path}"')
        return [TextContent(type="text", text=json.dumps({"opened": path}))]

    elif name == "open_app":
        app_name = arguments["name"]
        _osascript(f'tell application "{app_name}" to activate')
        return [TextContent(type="text", text=json.dumps({"launched": app_name}))]

    elif name == "get_frontmost_app":
        result = _osascript(
            'tell application "System Events" to get name of first application process '
            'whose frontmost is true'
        )
        return [TextContent(type="text", text=json.dumps({"frontmost_app": result}))]

    elif name == "position_window":
        target = arguments.get("app_name", "")
        # Get screen size dynamically
        screen_info = _osascript(
            'tell application "Finder" to get bounds of window of desktop'
        )
        parts = [int(x.strip()) for x in screen_info.split(",")]
        screen_w, screen_h = parts[2], parts[3]

        x = int(screen_w * 0.15)
        y = 25  # menu bar height
        w = screen_w - x
        h = screen_h - y

        if target:
            script = (
                f'tell application "System Events" to tell process "{target}" to '
                f'set position of window 1 to {{{x}, {y}}}\n'
                f'tell application "System Events" to tell process "{target}" to '
                f'set size of window 1 to {{{w}, {h}}}'
            )
        else:
            script = (
                'tell application "System Events"\n'
                '  set fp to first application process whose frontmost is true\n'
                f'  set position of window 1 of fp to {{{x}, {y}}}\n'
                f'  set size of window 1 of fp to {{{w}, {h}}}\n'
                'end tell'
            )
        _osascript(script)
        result = {"x": x, "y": y, "width": w, "height": h, "screen": [screen_w, screen_h]}
        return [TextContent(type="text", text=json.dumps(result))]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
