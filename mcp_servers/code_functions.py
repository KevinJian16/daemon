#!/usr/bin/env python3
"""MCP server: code analysis via tree-sitter — function/class extraction.

Provides tools to extract code structure (functions, classes, imports) from
source files using tree-sitter parsers. Zero LLM tokens.

Transport: stdio (launched by MCPDispatcher).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

app = Server("code-functions")

# Language extension → tree-sitter language mapping
_LANG_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
}

# Tree-sitter node types that represent "functions" per language
_FUNC_TYPES: dict[str, set[str]] = {
    "python": {"function_definition", "class_definition"},
    "javascript": {"function_declaration", "class_declaration", "method_definition", "arrow_function"},
    "typescript": {"function_declaration", "class_declaration", "method_definition", "arrow_function"},
    "tsx": {"function_declaration", "class_declaration", "method_definition", "arrow_function"},
}

_parsers: dict[str, object] = {}


def _get_parser(lang: str):
    """Get or create a tree-sitter parser for the given language."""
    if lang in _parsers:
        return _parsers[lang]

    import tree_sitter

    parser = tree_sitter.Parser()

    if lang == "python":
        import tree_sitter_python
        ts_lang = tree_sitter.Language(tree_sitter_python.language())
    elif lang == "javascript":
        import tree_sitter_javascript
        ts_lang = tree_sitter.Language(tree_sitter_javascript.language())
    elif lang in ("typescript", "tsx"):
        import tree_sitter_typescript
        if lang == "tsx":
            ts_lang = tree_sitter.Language(tree_sitter_typescript.language_tsx())
        else:
            ts_lang = tree_sitter.Language(tree_sitter_typescript.language_typescript())
    else:
        return None

    parser.language = ts_lang
    _parsers[lang] = parser
    return parser


def _detect_lang(file_path: str) -> str | None:
    ext = Path(file_path).suffix.lower()
    return _LANG_MAP.get(ext)


def _extract_symbols(file_path: str) -> list[dict]:
    """Extract function/class symbols from a file."""
    lang = _detect_lang(file_path)
    if not lang:
        return []

    parser = _get_parser(lang)
    if not parser:
        return []

    try:
        source = Path(file_path).read_bytes()
    except (OSError, IOError):
        return []

    tree = parser.parse(source)
    func_types = _FUNC_TYPES.get(lang, {"function_definition", "class_definition"})
    symbols: list[dict] = []

    def _walk(node, parent_name: str = ""):
        if node.type in func_types:
            name_node = node.child_by_field_name("name")
            name = name_node.text.decode("utf-8") if name_node else "<anonymous>"
            qualified = f"{parent_name}.{name}" if parent_name else name

            # Extract parameters for functions
            params = ""
            params_node = node.child_by_field_name("parameters")
            if params_node:
                params = params_node.text.decode("utf-8")

            symbols.append({
                "type": node.type.replace("_definition", "").replace("_declaration", ""),
                "name": qualified,
                "line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "params": params,
            })

            # Recurse into class body for methods
            for child in node.children:
                _walk(child, parent_name=qualified)
        else:
            for child in node.children:
                _walk(child, parent_name=parent_name)

    _walk(tree.root_node)
    return symbols


def _extract_imports(file_path: str) -> list[str]:
    """Extract import statements from a file."""
    lang = _detect_lang(file_path)
    if not lang:
        return []

    parser = _get_parser(lang)
    if not parser:
        return []

    try:
        source = Path(file_path).read_bytes()
    except (OSError, IOError):
        return []

    tree = parser.parse(source)
    imports: list[str] = []

    import_types = {
        "python": {"import_statement", "import_from_statement"},
        "javascript": {"import_statement"},
        "typescript": {"import_statement"},
        "tsx": {"import_statement"},
    }

    target_types = import_types.get(lang, set())

    def _walk(node):
        if node.type in target_types:
            imports.append(node.text.decode("utf-8").strip())
        for child in node.children:
            _walk(child)

    _walk(tree.root_node)
    return imports


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="code_functions",
            description="Extract all function and class definitions from a source file with line numbers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "Absolute path to the source file"},
                },
                "required": ["file"],
            },
        ),
        Tool(
            name="code_structure",
            description="Get the code structure (functions, classes) of all supported files in a directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Absolute path to the directory"},
                    "recursive": {"type": "boolean", "description": "Recurse into subdirs", "default": True},
                    "extensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "File extensions to include (e.g. ['.py', '.ts']). Defaults to all supported.",
                    },
                },
                "required": ["directory"],
            },
        ),
        Tool(
            name="code_imports",
            description="Extract all import statements from a source file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "Absolute path to the source file"},
                },
                "required": ["file"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "code_functions":
        file_path = arguments["file"]
        symbols = _extract_symbols(file_path)
        return [TextContent(type="text", text=json.dumps(symbols, indent=2))]

    elif name == "code_structure":
        directory = Path(arguments["directory"])
        recursive = arguments.get("recursive", True)
        extensions = arguments.get("extensions") or list(_LANG_MAP.keys())
        ext_set = set(extensions)

        result: dict[str, list[dict]] = {}
        pattern = "**/*" if recursive else "*"

        for ext in ext_set:
            if ext not in _LANG_MAP:
                continue
            for fp in directory.glob(f"{pattern}{ext}"):
                if fp.is_file():
                    symbols = _extract_symbols(str(fp))
                    if symbols:
                        rel = str(fp.relative_to(directory))
                        result[rel] = symbols

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "code_imports":
        file_path = arguments["file"]
        imports = _extract_imports(file_path)
        return [TextContent(type="text", text=json.dumps(imports, indent=2))]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
