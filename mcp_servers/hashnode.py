#!/usr/bin/env python3
"""MCP server: Hashnode GraphQL API — create and retrieve blog posts.

Provides tools for publishing posts and retrieving articles on Hashnode
via its GraphQL API.
Transport: stdio (launched by MCPDispatcher).

Reference: https://apidocs.hashnode.com
"""
from __future__ import annotations

import json
import os

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

GQL_URL = "https://gql.hashnode.com"

app = Server("hashnode")


def _headers() -> dict[str, str]:
    token = os.environ.get("HASHNODE_TOKEN", "")
    return {"Authorization": token, "Content-Type": "application/json"}


async def _gql(client: httpx.AsyncClient, query: str, variables: dict | None = None) -> dict:
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = await client.post(GQL_URL, json=payload, headers=_headers())
    resp.raise_for_status()
    body = resp.json()
    if body.get("errors"):
        raise RuntimeError(json.dumps(body["errors"], ensure_ascii=False))
    return body.get("data", {})


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="hashnode_create_post",
            description="Create a new blog post on Hashnode.",
            inputSchema={
                "type": "object",
                "properties": {
                    "publication_id": {"type": "string", "description": "Hashnode publication (blog) ID"},
                    "title": {"type": "string", "description": "Post title"},
                    "content_markdown": {"type": "string", "description": "Post body in Markdown"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "object", "properties": {"slug": {"type": "string"}, "name": {"type": "string"}}},
                        "description": "Tags as [{slug, name}]",
                    },
                    "subtitle": {"type": "string", "description": "Post subtitle (optional)"},
                },
                "required": ["publication_id", "title", "content_markdown"],
            },
        ),
        Tool(
            name="hashnode_get_posts",
            description="Get recent posts from a Hashnode publication.",
            inputSchema={
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Publication host (e.g. 'myblog.hashnode.dev')"},
                    "first": {"type": "integer", "description": "Number of posts to fetch", "default": 10},
                },
                "required": ["host"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=30) as client:
        if name == "hashnode_create_post":
            mutation = """
            mutation PublishPost($input: PublishPostInput!) {
                publishPost(input: $input) {
                    post { id title slug url }
                }
            }"""
            variables = {
                "input": {
                    "publicationId": arguments["publication_id"],
                    "title": arguments["title"],
                    "contentMarkdown": arguments["content_markdown"],
                }
            }
            if arguments.get("tags"):
                variables["input"]["tags"] = arguments["tags"]
            if arguments.get("subtitle"):
                variables["input"]["subtitle"] = arguments["subtitle"]
            data = await _gql(client, mutation, variables)
            post = data.get("publishPost", {}).get("post", {})
            return [TextContent(type="text", text=json.dumps(post, ensure_ascii=False, indent=2))]

        elif name == "hashnode_get_posts":
            query = """
            query GetPosts($host: String!, $first: Int!) {
                publication(host: $host) {
                    id title
                    posts(first: $first) {
                        edges {
                            node { id title slug url brief publishedAt }
                        }
                    }
                }
            }"""
            variables = {
                "host": arguments["host"],
                "first": min(int(arguments.get("first", 10)), 50),
            }
            data = await _gql(client, query, variables)
            pub = data.get("publication", {})
            edges = pub.get("posts", {}).get("edges", [])
            posts = [e["node"] for e in edges]
            result = {"publication": pub.get("title", ""), "posts": posts}
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
