"""MCP code_exec tool — lightweight MCP server wrapper for CC/Codex CLI.

Exposes a single `code_exec` MCP tool that runs Claude Code or Codex CLI
in a subprocess. Integrates with mcp_dispatch.py as a local stdio server.

Per-engine concurrency is enforced by Semaphore(1) so at most one CC and
one Codex run simultaneously per process.

Reference: SYSTEM_DESIGN.md §3.13
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Per-engine concurrency: max 1 parallel run per engine
_ENGINE_SEMAPHORES: dict[str, asyncio.Semaphore] = {
    "claude_code": asyncio.Semaphore(1),
    "codex": asyncio.Semaphore(1),
}

# Default execution timeout (seconds)
_DEFAULT_TIMEOUT = 300


def _find_cli(name: str) -> str | None:
    return shutil.which(name)


async def code_exec(
    engine: str,
    task: str,
    working_directory: str | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT,
    model: str | None = None,
) -> dict:
    """Execute a task via Claude Code or Codex CLI.

    Args:
        engine: "claude_code" or "codex"
        task: Natural-language task description / prompt
        working_directory: Working dir for CLI subprocess (defaults to DAEMON_HOME)
        timeout_s: Execution timeout in seconds
        model: Optional model override (passed as --model flag)

    Returns:
        {"ok": bool, "output": str, "engine": str, "exit_code": int}
    """
    if engine not in _ENGINE_SEMAPHORES:
        return {
            "ok": False,
            "engine": engine,
            "output": f"Unsupported engine '{engine}'. Use 'claude_code' or 'codex'.",
            "exit_code": -1,
        }

    if not task or not task.strip():
        return {
            "ok": False,
            "engine": engine,
            "output": "task must not be empty",
            "exit_code": -1,
        }

    cwd = working_directory or os.environ.get("DAEMON_HOME", str(Path(__file__).parent.parent))

    semaphore = _ENGINE_SEMAPHORES[engine]

    async with semaphore:
        if engine == "claude_code":
            cli = _find_cli("claude")
            if not cli:
                return {
                    "ok": False,
                    "engine": engine,
                    "output": "'claude' CLI not found in PATH",
                    "exit_code": -1,
                }
            cmd = [cli, "--print", "--output-format", "text"]
            if model:
                cmd.extend(["--model", model])
            cmd.append(task)

        else:  # codex
            cli = _find_cli("codex")
            if not cli:
                return {
                    "ok": False,
                    "engine": engine,
                    "output": "'codex' CLI not found in PATH",
                    "exit_code": -1,
                }
            cmd = [cli, "--quiet", "--approval-mode", "auto-edit"]
            if model:
                cmd.extend(["--model", model])
            cmd.append(task)

        logger.info("code_exec [%s]: running %s (cwd=%s)", engine, cli, cwd)

        loop = asyncio.get_running_loop()

        def _run() -> tuple[str, str, int]:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=cwd,
            )
            return result.stdout, result.stderr, result.returncode

        try:
            stdout, stderr, returncode = await loop.run_in_executor(None, _run)
        except subprocess.TimeoutExpired:
            logger.warning("code_exec [%s] timed out after %ds", engine, timeout_s)
            return {
                "ok": False,
                "engine": engine,
                "output": f"Execution timed out after {timeout_s}s",
                "exit_code": -1,
            }
        except Exception as exc:
            logger.warning("code_exec [%s] subprocess failed: %s", engine, exc)
            return {
                "ok": False,
                "engine": engine,
                "output": str(exc)[:500],
                "exit_code": -1,
            }

        output = (stdout or "").strip()
        if returncode != 0 and not output:
            output = (stderr or "").strip()

        return {
            "ok": returncode == 0,
            "engine": engine,
            "output": output[:20000],
            "exit_code": returncode,
        }


# ── MCP server entry point ───────────────────────────────────────────────────
# When invoked as `python runtime/mcp_code_exec.py` this module runs as a
# stdio MCP server exposing the `code_exec` tool to OpenClaw / mcp_dispatch.

def _build_mcp_server():
    """Build and return the MCP server instance."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import Tool, TextContent
        import mcp.types as types
    except ImportError:
        logger.error("mcp package not installed — cannot run as MCP server")
        sys.exit(1)

    server = Server("code-exec")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="code_exec",
                description=(
                    "Execute a task via Claude Code or Codex CLI. "
                    "Per-engine concurrency limit: 1 (Semaphore(1))."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "engine": {
                            "type": "string",
                            "enum": ["claude_code", "codex"],
                            "description": "CLI engine to use",
                        },
                        "task": {
                            "type": "string",
                            "description": "Task description / prompt for the CLI",
                        },
                        "working_directory": {
                            "type": "string",
                            "description": "Working directory (optional, defaults to DAEMON_HOME)",
                        },
                        "timeout_s": {
                            "type": "integer",
                            "description": "Execution timeout in seconds (default 300)",
                            "default": 300,
                        },
                        "model": {
                            "type": "string",
                            "description": "Model override (optional)",
                        },
                    },
                    "required": ["engine", "task"],
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name != "code_exec":
            raise ValueError(f"Unknown tool: {name}")

        result = await code_exec(
            engine=str(arguments.get("engine") or "claude_code"),
            task=str(arguments.get("task") or ""),
            working_directory=arguments.get("working_directory"),
            timeout_s=int(arguments.get("timeout_s") or _DEFAULT_TIMEOUT),
            model=arguments.get("model"),
        )

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    return server, stdio_server


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    async def _main():
        server, stdio_server = _build_mcp_server()
        async with stdio_server(server):
            await asyncio.Event().wait()  # run until killed

    asyncio.run(_main())
