"""Cortex — unified LLM abstraction layer with adaptive routing and graceful degradation."""
from __future__ import annotations

import json
import logging
import os
import time
import traceback
from collections.abc import Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# Provider priorities applied when no Compass routing is available.
_DEFAULT_PROVIDER_ORDER = ["deepseek", "anthropic", "openai", "minimax"]


class CortexError(Exception):
    pass


class Cortex:
    """Unified LLM access layer. Manages provider selection, fallback, token metering, degradation."""

    def __init__(self, compass=None) -> None:
        # compass: CompassFabric | None — if provided, reads dynamic routing strategy.
        self._compass = compass
        self._usage: list[dict] = []
        self._clients: dict[str, Any] = {}
        self._init_clients()

    def _init_clients(self) -> None:
        if os.getenv("OPENAI_API_KEY"):
            try:
                import openai
                self._clients["openai"] = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            except ImportError:
                logger.debug("openai package not installed — provider skipped")

        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                import anthropic
                self._clients["anthropic"] = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            except ImportError:
                logger.debug("anthropic package not installed — provider skipped")

        if os.getenv("DEEPSEEK_API_KEY"):
            try:
                import openai
                self._clients["deepseek"] = openai.OpenAI(
                    api_key=os.environ["DEEPSEEK_API_KEY"],
                    base_url="https://api.deepseek.com/v1",
                )
            except ImportError:
                logger.debug("openai package not installed — deepseek provider skipped")

        if os.getenv("MINIMAX_API_KEY") and os.getenv("MINIMAX_GROUP_ID"):
            self._clients["minimax"] = {
                "api_key": os.environ["MINIMAX_API_KEY"],
                "group_id": os.environ["MINIMAX_GROUP_ID"],
            }

    def _provider_order(self) -> list[str]:
        if self._compass:
            primary = self._compass.get_pref("model_primary", "")
            if primary and primary in self._clients:
                rest = [p for p in _DEFAULT_PROVIDER_ORDER if p != primary and p in self._clients]
                return [primary] + rest
        return [p for p in _DEFAULT_PROVIDER_ORDER if p in self._clients]

    def is_available(self) -> bool:
        return bool(self._clients)

    def complete(self, prompt: str, model: str | None = None, max_tokens: int = 2048, temperature: float = 0.3) -> str:
        """Generate a completion. Tries providers in priority order."""
        providers = self._provider_order()
        if not providers:
            raise CortexError("no LLM providers configured")

        last_err: Exception | None = None
        for provider in providers:
            t0 = time.time()
            try:
                result, in_tokens, out_tokens = self._call(provider, prompt, model, max_tokens, temperature)
                elapsed = time.time() - t0
                self._record_usage(provider, model or provider, in_tokens, out_tokens, elapsed, True)
                return result
            except Exception as e:
                elapsed = time.time() - t0
                self._record_usage(provider, model or provider, 0, 0, elapsed, False, str(e)[:200])
                last_err = e

        raise CortexError(f"all providers failed; last error: {last_err}") from last_err

    def structured(self, prompt: str, schema: dict, model: str | None = None) -> dict:
        """LLM call that returns validated JSON. Falls back to empty dict on parse failure."""
        schema_hint = json.dumps(schema, ensure_ascii=False, indent=2)
        full_prompt = (
            f"{prompt}\n\n"
            f"Respond ONLY with valid JSON matching this schema:\n{schema_hint}\n"
            "Do not include markdown fences or any other text."
        )
        raw = self.complete(full_prompt, model=model, temperature=0.1)
        # Strip optional markdown fences.
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[-1].lstrip("json").strip()
            if raw.endswith("```"):
                raw = raw[:-3].strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise CortexError(f"structured: invalid JSON from LLM: {e}") from e

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings for a list of texts. Uses first available provider with embed support."""
        if "openai" in self._clients:
            client = self._clients["openai"]
            resp = client.embeddings.create(model="text-embedding-3-small", input=texts)
            return [item.embedding for item in resp.data]
        # DeepSeek and MiniMax do not support embeddings; only OpenAI does.
        raise CortexError("no embedding provider available (need openai)")

    def try_or_degrade(self, fn: Callable[[], Any], fallback: Callable[[], Any]) -> Any:
        """Try fn(); if Cortex is unavailable or fails, run fallback() instead."""
        if not self.is_available():
            return fallback()
        try:
            return fn()
        except CortexError:
            return fallback()
        except Exception:
            return fallback()

    def usage_today(self) -> dict:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        today_usage = [u for u in self._usage if u["timestamp"].startswith(today)]
        by_provider: dict[str, dict] = {}
        for u in today_usage:
            p = u["provider"]
            if p not in by_provider:
                by_provider[p] = {"calls": 0, "in_tokens": 0, "out_tokens": 0, "errors": 0}
            by_provider[p]["calls"] += 1
            by_provider[p]["in_tokens"] += u.get("in_tokens", 0)
            by_provider[p]["out_tokens"] += u.get("out_tokens", 0)
            if not u.get("success"):
                by_provider[p]["errors"] += 1
        return {"date": today, "by_provider": by_provider, "total_calls": len(today_usage)}

    def recent_traces(self, limit: int = 20) -> list[dict]:
        return self._usage[-limit:]

    # ── Internal ─────────────────────────────────────────────────────────────

    def _call(self, provider: str, prompt: str, model: str | None, max_tokens: int, temperature: float) -> tuple[str, int, int]:
        """Returns (text, in_tokens, out_tokens)."""
        if provider == "openai":
            return self._call_openai(self._clients["openai"], prompt, model or "gpt-4o-mini", max_tokens, temperature)
        if provider == "deepseek":
            return self._call_openai(self._clients["deepseek"], prompt, model or "deepseek-chat", max_tokens, temperature)
        if provider == "anthropic":
            return self._call_anthropic(self._clients["anthropic"], prompt, model or "claude-haiku-4-5-20251001", max_tokens, temperature)
        if provider == "minimax":
            return self._call_minimax(self._clients["minimax"], prompt, model or "abab6.5s-chat", max_tokens, temperature)
        raise CortexError(f"unknown provider: {provider}")

    def _call_openai(self, client: Any, prompt: str, model: str, max_tokens: int, temperature: float) -> tuple[str, int, int]:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        return text, int(usage.prompt_tokens or 0), int(usage.completion_tokens or 0)

    def _call_anthropic(self, client: Any, prompt: str, model: str, max_tokens: int, temperature: float) -> tuple[str, int, int]:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        return text, int(resp.usage.input_tokens or 0), int(resp.usage.output_tokens or 0)

    def _call_minimax(self, cfg: dict, prompt: str, model: str, max_tokens: int, temperature: float) -> tuple[str, int, int]:
        url = f"https://api.minimax.chat/v1/text/chatcompletion_v2?GroupId={cfg['group_id']}"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        resp = httpx.post(url, json=payload, headers={"Authorization": f"Bearer {cfg['api_key']}"}, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))

    def _record_usage(self, provider: str, model: str, in_t: int, out_t: int, elapsed: float, success: bool, error: str | None = None) -> None:
        entry = {
            "timestamp": _utc(),
            "provider": provider,
            "model": model,
            "in_tokens": in_t,
            "out_tokens": out_t,
            "elapsed_s": round(elapsed, 2),
            "success": success,
        }
        if error:
            entry["error"] = error
        self._usage.append(entry)
        # Keep last 1000 entries in memory; persistence handled by spine.witness analysis of traces.
        if len(self._usage) > 1000:
            self._usage = self._usage[-1000:]
        # Deduct from Compass budget if available.
        if success and self._compass:
            total = in_t + out_t
            resource_key = f"{provider}_tokens"
            self._compass.consume_budget(resource_key, total)
