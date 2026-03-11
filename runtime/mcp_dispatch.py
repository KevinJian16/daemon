"""MCP tool dispatcher — programmatic tool calls to MCP servers, zero LLM."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack
from pathlib import Path

logger = logging.getLogger(__name__)


class MCPDispatcher:
    """Manages connections to MCP servers and dispatches tool calls by name."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._server_configs: dict[str, dict] = {}
        self._connections: dict[str, _ServerConnection] = {}
        self._tool_routes: dict[str, str] = {}  # tool_name -> server_name
        self._discovered = False
        if config_path and config_path.exists():
            try:
                raw = json.loads(config_path.read_text())
                self._server_configs = raw.get("servers") or {}
            except Exception as exc:
                logger.warning("Failed to load MCP server config from %s: %s", config_path, exc)

    @property
    def available(self) -> bool:
        return bool(self._server_configs)

    async def call_tool(self, tool_name: str, tool_args: dict, timeout_s: float = 60) -> dict:
        """Call a tool on the appropriate MCP server. Connects lazily on first use."""
        if not self._discovered:
            await self._discover_all()

        server_name = self._tool_routes.get(tool_name)
        if not server_name:
            raise ValueError(f"No MCP server registered for tool '{tool_name}'")

        conn = self._connections.get(server_name)
        if not conn or not conn.session:
            raise RuntimeError(f"MCP server '{server_name}' not connected")

        result = await asyncio.wait_for(
            conn.session.call_tool(tool_name, arguments=tool_args),
            timeout=timeout_s,
        )

        if result.isError:
            texts = [c.text for c in (result.content or []) if hasattr(c, "text")]
            raise RuntimeError(f"MCP tool '{tool_name}' failed: {' '.join(texts)}")

        output_parts = []
        for block in result.content or []:
            if hasattr(block, "text"):
                output_parts.append(block.text)

        return {"output": "\n".join(output_parts), "tool": tool_name}

    async def _discover_all(self) -> None:
        """Connect to all configured servers and build the tool→server routing table."""
        for name, cfg in self._server_configs.items():
            try:
                conn = _ServerConnection(name, cfg)
                await conn.connect()
                self._connections[name] = conn
                tools_resp = await conn.session.list_tools()
                for tool in tools_resp.tools:
                    self._tool_routes[tool.name] = name
                logger.info("MCP server '%s': %d tools discovered", name, len(tools_resp.tools))
            except Exception as exc:
                logger.warning("Failed to connect MCP server '%s': %s", name, exc)
        self._discovered = True

    async def close(self) -> None:
        for name, conn in self._connections.items():
            try:
                await conn.close()
            except Exception as exc:
                logger.warning("Error closing MCP server '%s': %s", name, exc)
        self._connections.clear()
        self._tool_routes.clear()
        self._discovered = False

    def list_tools(self) -> list[str]:
        return list(self._tool_routes.keys())


class _ServerConnection:
    """Wraps a persistent connection to one MCP server."""

    def __init__(self, name: str, config: dict) -> None:
        self.name = name
        self._config = config
        self.session = None
        self._stack: AsyncExitStack | None = None

    async def connect(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        transport = str(self._config.get("transport") or "stdio")

        self._stack = AsyncExitStack()
        await self._stack.__aenter__()

        if transport == "stdio":
            command = str(self._config.get("command") or "")
            args = self._config.get("args") or []
            env_overrides = self._config.get("env") or {}
            env = {k: os.path.expandvars(str(v)) for k, v in env_overrides.items()}
            params = StdioServerParameters(command=command, args=args, env=env or None)
            read, write = await self._stack.enter_async_context(stdio_client(params))
        elif transport == "http":
            from mcp.client.streamable_http import streamablehttp_client
            url = str(self._config.get("url") or "")
            read, write, _ = await self._stack.enter_async_context(streamablehttp_client(url))
        else:
            raise ValueError(f"Unknown MCP transport: {transport}")

        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()

    async def close(self) -> None:
        if self._stack:
            await self._stack.__aexit__(None, None, None)
            self._stack = None
            self.session = None
