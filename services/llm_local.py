"""Local LLM client — calls Ollama for internal daemon tasks.

Used by task_model_map tasks (triage, guardrails, replan, compression, etc.)
that don't need OC agent sessions. Keeps cloud API tokens for agent work.

Ollama exposes an OpenAI-compatible API at /v1/chat/completions,
plus native /api/generate and /api/embeddings endpoints.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(__file__).parent.parent / "config" / "model_registry.json"
_POLICY_PATH = Path(__file__).parent.parent / "config" / "model_policy.json"

# Cache loaded config
_registry: dict | None = None
_policy: dict | None = None


def _load_registry() -> dict:
    global _registry
    if _registry is None:
        _registry = json.loads(_REGISTRY_PATH.read_text())
    return _registry


def _load_policy() -> dict:
    global _policy
    if _policy is None:
        _policy = json.loads(_POLICY_PATH.read_text())
    return _policy


def _resolve_model(alias: str) -> tuple[str, str]:
    """Resolve alias → (model_id, endpoint).

    Returns (model_id, endpoint) for Ollama models.
    Raises ValueError if alias not found or not an Ollama model.
    """
    registry = _load_registry()
    for entry in registry.get("models", []):
        if entry.get("alias") == alias:
            if entry.get("provider") != "ollama":
                raise ValueError(f"Model alias {alias!r} is not an Ollama model (provider={entry.get('provider')!r})")
            return entry["model_id"], entry.get("endpoint", "http://localhost:11434")
    raise ValueError(f"Model alias {alias!r} not found in model_registry.json")


def resolve_task_model(task_name: str) -> str:
    """Look up the model alias for a task_model_map entry.

    Returns the alias string (e.g. 'local-heavy').
    Falls back to 'local-light' if task not in map.
    """
    policy = _load_policy()
    return policy.get("task_model_map", {}).get(task_name, "local-light")


async def chat(
    alias: str,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
    max_tokens: int = 1024,
    timeout_s: int = 120,
) -> str:
    """Send a chat completion request to Ollama.

    Args:
        alias: Model alias from model_registry.json (e.g. 'local-heavy')
        messages: OpenAI-format messages [{"role": "user", "content": "..."}]
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        timeout_s: Request timeout in seconds

    Returns:
        The assistant's response text.
    """
    model_id, endpoint = _resolve_model(alias)

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(
            f"{endpoint}/v1/chat/completions",
            json={
                "model": model_id,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    logger.debug(
        "llm_local.chat alias=%s model=%s tokens_in=%s tokens_out=%s",
        alias, model_id,
        usage.get("prompt_tokens", "?"),
        usage.get("completion_tokens", "?"),
    )
    return content


async def generate(
    alias: str,
    prompt: str,
    *,
    temperature: float = 0.1,
    max_tokens: int = 1024,
    system: str | None = None,
    timeout_s: int = 120,
) -> str:
    """Simple generate (non-chat) via Ollama native API.

    Useful for single-turn tasks like classification.
    """
    model_id, endpoint = _resolve_model(alias)
    payload: dict[str, Any] = {
        "model": model_id,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    if system:
        payload["system"] = system

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(f"{endpoint}/api/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()

    return data.get("response", "")


async def embed(
    text: str | list[str],
    *,
    alias: str = "local-embedding",
    timeout_s: int = 30,
) -> list[list[float]]:
    """Generate embeddings via Ollama.

    Args:
        text: Single string or list of strings to embed.
        alias: Embedding model alias (default: local-embedding)

    Returns:
        List of embedding vectors.
    """
    model_id, endpoint = _resolve_model(alias)
    if isinstance(text, str):
        text = [text]

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(
            f"{endpoint}/api/embed",
            json={"model": model_id, "input": text},
        )
        resp.raise_for_status()
        data = resp.json()

    return data.get("embeddings", [])


async def healthy() -> bool:
    """Check if Ollama is running and responsive."""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get("http://localhost:11434/api/version")
            return resp.status_code == 200
    except Exception:
        return False


def reload_config() -> None:
    """Force reload of model_registry.json and model_policy.json.

    Call after config files are updated at runtime.
    """
    global _registry, _policy
    _registry = None
    _policy = None
