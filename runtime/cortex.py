"""Cortex — unified LLM abstraction layer with adaptive routing and graceful degradation."""
from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from runtime.trail_context import current_trail

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# Provider priorities applied when no Instinct routing is available.
# MiniMax is first — it is the high-frequency workhorse; Zhipu/Qwen/DeepSeek handle heavy analysis.
_DEFAULT_PROVIDER_ORDER = ["minimax", "zhipu", "qwen", "deepseek", "openai", "anthropic"]

# Path to model registry for alias resolution.
_REGISTRY_PATH = Path(__file__).parent.parent / "config" / "model_registry.json"
_POLICY_PATH = Path(__file__).parent.parent / "config" / "model_policy.json"


def _load_registry() -> dict[str, dict]:
    """Return {alias: {provider, model_id}} from model_registry.json."""
    try:
        data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        return {
            m["alias"]: m
            for m in data.get("models", [])
            if not m.get("inactive")
        }
    except Exception:
        return {}


def _load_policy() -> dict:
    try:
        return json.loads(_POLICY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


class CortexError(Exception):
    pass


class Cortex:
    """Unified LLM access layer. Manages provider selection, fallback, token metering, degradation."""

    def __init__(self, instinct=None, usage_path: Path | None = None) -> None:
        # instinct: Instinct | None — if provided, reads dynamic routing strategy.
        self._instinct = instinct
        self._usage: list[dict] = []
        self._clients: dict[str, Any] = {}
        self._usage_path = usage_path or self._default_usage_path()
        self._usage_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_usage()
        self._init_clients()

    def _default_usage_path(self) -> Path:
        daemon_home = Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))
        return daemon_home / "state" / "traces" / "cortex_usage.jsonl"

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

        if os.getenv("MINIMAX_API_KEY"):
            try:
                import anthropic
                self._clients["minimax"] = anthropic.Anthropic(
                    api_key=os.environ["MINIMAX_API_KEY"],
                    base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/anthropic"),
                )
            except ImportError:
                logger.debug("anthropic package not installed — minimax provider skipped")

        if os.getenv("ZHIPU_API_KEY"):
            try:
                import openai
                self._clients["zhipu"] = openai.OpenAI(
                    api_key=os.environ["ZHIPU_API_KEY"],
                    base_url=os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/"),
                )
            except ImportError:
                logger.debug("openai package not installed — zhipu provider skipped")

        if os.getenv("DASHSCOPE_API_KEY"):
            try:
                import openai
                self._clients["qwen"] = openai.OpenAI(
                    api_key=os.environ["DASHSCOPE_API_KEY"],
                    base_url=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                )
            except ImportError:
                logger.debug("openai package not installed — qwen provider skipped")

    def _provider_order(self) -> list[str]:
        policy = _load_policy()
        route = policy.get("provider_route") if isinstance(policy.get("provider_route"), list) else []
        ordered = [str(p) for p in route if str(p) in self._clients]
        if self._instinct:
            primary = self._instinct.get_pref("model_primary", "")
            if primary and primary in self._clients and primary not in ordered:
                ordered = [primary] + ordered
        for p in _DEFAULT_PROVIDER_ORDER:
            if p in self._clients and p not in ordered:
                ordered.append(p)
        return ordered

    def is_available(self) -> bool:
        return bool(self._clients)

    def complete(self, prompt: str, model: str | None = None, max_tokens: int = 4096, temperature: float = 0.3) -> str:
        """Generate a completion. Tries providers in priority order.

        ``model`` may be a registry alias (e.g. "fast", "analysis") or a literal
        model ID (e.g. "deepseek-reasoner").  Aliases are resolved against
        config/model_registry.json; if the resolved provider is available it is
        called directly (skipping the provider loop).
        """
        # Resolve alias → (provider, model_id) if applicable.
        if not model:
            policy = _load_policy()
            default_alias = str(policy.get("default_alias") or "").strip()
            if default_alias:
                model = default_alias

        resolved_provider: str | None = None
        resolved_model: str | None = model
        attempted_route: list[str] = []
        if model:
            registry = _load_registry()
            if model in registry:
                entry = registry[model]
                resolved_provider = entry["provider"]
                resolved_model = entry["model_id"]

        # Direct call when alias resolved to an available provider.
        if resolved_provider and resolved_provider in self._clients:
            attempted_route.append(resolved_provider)
            t0 = time.time()
            try:
                result, in_t, out_t = self._call(resolved_provider, prompt, resolved_model, max_tokens, temperature)
                if not self._ration_admit(resolved_provider, in_t + out_t):
                    self._record_usage(
                        resolved_provider,
                        resolved_model or resolved_provider,
                        in_t,
                        out_t,
                        round(time.time() - t0, 2),
                        False,
                        "provider_ration_exceeded",
                        prompt_preview=prompt[:300],
                        provider_route=attempted_route,
                    )
                else:
                    self._record_usage(
                        resolved_provider,
                        resolved_model or resolved_provider,
                        in_t,
                        out_t,
                        round(time.time() - t0, 2),
                        True,
                        prompt_preview=prompt[:300],
                        output_preview=result[:300],
                        provider_route=attempted_route,
                    )
                    return result
            except Exception as e:
                self._record_usage(resolved_provider, resolved_model or resolved_provider, 0, 0,
                                   round(time.time() - t0, 2), False, str(e)[:200], prompt_preview=prompt[:300],
                                   provider_route=attempted_route)
                # Fall through to provider loop as fallback.

        providers = self._provider_order()
        if resolved_provider:
            providers = [p for p in providers if p != resolved_provider]
        if not providers:
            raise CortexError("no LLM providers configured")

        last_err: Exception | None = None
        ration_blocked = False
        for provider in providers:
            attempted_route.append(provider)
            t0 = time.time()
            try:
                result, in_tokens, out_tokens = self._call(provider, prompt, resolved_model, max_tokens, temperature)
                if not self._ration_admit(provider, in_tokens + out_tokens):
                    elapsed = time.time() - t0
                    self._record_usage(
                        provider,
                        model or provider,
                        in_tokens,
                        out_tokens,
                        elapsed,
                        False,
                        "provider_ration_exceeded",
                        prompt_preview=prompt[:300],
                        provider_route=attempted_route,
                    )
                    ration_blocked = True
                    last_err = CortexError("provider_ration_exceeded")
                    continue
                elapsed = time.time() - t0
                self._record_usage(
                    provider,
                    model or provider,
                    in_tokens,
                    out_tokens,
                    elapsed,
                    True,
                    prompt_preview=prompt[:300],
                    output_preview=result[:300],
                    provider_route=attempted_route,
                )
                return result
            except Exception as e:
                elapsed = time.time() - t0
                self._record_usage(
                    provider,
                    model or provider,
                    0,
                    0,
                    elapsed,
                    False,
                    str(e)[:200],
                    prompt_preview=prompt[:300],
                    provider_route=attempted_route,
                )
                last_err = e

        if ration_blocked:
            route = "->".join(attempted_route)
            raise CortexError(
                f"provider_ration_exceeded: all candidate providers blocked or failed after ration checks; "
                f"provider_route={route}"
            )
        route = "->".join(attempted_route)
        raise CortexError(f"all providers failed; provider_route={route}; last error: {last_err}") from last_err

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

    def embed(self, text: str | list[str]) -> list[float] | list[list[float]]:
        """Return embedding(s). Single string → single vector; list → list of vectors.

        Provider priority: zhipu (embedding-3) → openai (text-embedding-3-small).
        """
        client = self._clients.get("zhipu") or self._clients.get("openai")
        if client is None:
            raise CortexError("no embedding provider available (need zhipu or openai)")
        model = "embedding-3" if "zhipu" in self._clients else "text-embedding-3-small"
        if isinstance(text, str):
            resp = client.embeddings.create(model=model, input=[text])
            return resp.data[0].embedding
        resp = client.embeddings.create(model=model, input=text)
        return [item.embedding for item in resp.data]

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
        today_usage = [u for u in self._usage if str(u.get("timestamp", "")).startswith(today)]
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

    def recent_trails(self, limit: int = 20) -> list[dict]:
        return self._usage[-limit:]

    def usage_between(self, since: str | None = None, until: str | None = None, limit: int = 1000) -> list[dict]:
        items = []
        for entry in reversed(self._usage):
            ts = str(entry.get("timestamp", ""))
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            items.append(entry)
            if len(items) >= limit:
                break
        return list(reversed(items))

    def usage_for_trail(self, trail_id: str, limit: int = 200) -> list[dict]:
        if not trail_id:
            return []
        items = [u for u in self._usage if str(u.get("trail_id", "")) == str(trail_id)]
        return items[-limit:]

    def provider_remaining_budget(self, provider: str) -> float | None:
        target = str(provider or "").strip().lower()
        if target != "minimax":
            return None
        api_key = os.getenv("MINIMAX_API_KEY", "").strip()
        if not api_key:
            return None
        base_url = os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/anthropic").rstrip("/")
        candidates = [
            os.getenv("MINIMAX_REMAINS_URL", "").strip(),
            base_url.replace("/anthropic", "/coding_plan/remains"),
            f"{base_url}/coding_plan/remains",
        ]
        headers = {"Authorization": f"Bearer {api_key}"}
        for url in candidates:
            if not url:
                continue
            try:
                resp = httpx.get(url, headers=headers, timeout=8)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                continue
            remains = self._extract_remaining_value(data)
            if remains is not None:
                return remains
        return None

    # ── Internal ─────────────────────────────────────────────────────────────

    def _call(self, provider: str, prompt: str, model: str | None, max_tokens: int, temperature: float) -> tuple[str, int, int]:
        """Returns (text, in_tokens, out_tokens)."""
        if provider == "openai":
            return self._call_openai(self._clients["openai"], prompt, model or "gpt-4o-mini", max_tokens, temperature)
        if provider == "deepseek":
            return self._call_deepseek(self._clients["deepseek"], prompt, model or "deepseek-chat", max_tokens, temperature)
        if provider == "anthropic":
            return self._call_anthropic(self._clients["anthropic"], prompt, model or "claude-haiku-4-5-20251001", max_tokens, temperature)
        if provider == "minimax":
            return self._call_anthropic(self._clients["minimax"], prompt, model or "MiniMax-M2.5", max_tokens, temperature)
        if provider == "zhipu":
            return self._call_zhipu(self._clients["zhipu"], prompt, model or "glm-z1-flash", max_tokens, temperature)
        if provider == "qwen":
            return self._call_openai(self._clients["qwen"], prompt, model or "qwen-max", max_tokens, temperature)
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

    def _call_deepseek(self, client: Any, prompt: str, model: str, max_tokens: int, temperature: float) -> tuple[str, int, int]:
        # deepseek-reasoner only accepts temperature=1; deepseek-chat accepts arbitrary values.
        is_reasoner = "reasoner" in model
        effective_temperature = 1.0 if is_reasoner else temperature
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=effective_temperature,
        )
        # Reasoner responses include reasoning_content + content; we use content (final answer).
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        # deepseek-reasoner reports reasoning tokens separately; sum all for ration tracking.
        in_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        out_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        return text, in_tokens, out_tokens

    def _call_zhipu(self, client: Any, prompt: str, model: str, max_tokens: int, temperature: float) -> tuple[str, int, int]:
        """Call Zhipu (GLM-Z1 series). Strips <think>...</think> reasoning blocks from output."""
        import re as _re
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = resp.choices[0].message.content or ""
        # GLM-Z1 reasoning models wrap chain-of-thought in <think>...</think>.
        # Strip complete blocks first, then any incomplete/unclosed block at the end.
        text = _re.sub(r"<think>[\s\S]*?</think>", "", text, flags=_re.IGNORECASE)
        text = _re.sub(r"<think>[\s\S]*$", "", text, flags=_re.IGNORECASE).strip()
        usage = resp.usage
        return text, int(getattr(usage, "prompt_tokens", 0) or 0), int(getattr(usage, "completion_tokens", 0) or 0)

    def _call_anthropic(self, client: Any, prompt: str, model: str, max_tokens: int, temperature: float) -> tuple[str, int, int]:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        return text, int(resp.usage.input_tokens or 0), int(resp.usage.output_tokens or 0)


    def _record_usage(
        self,
        provider: str,
        model: str,
        in_t: int,
        out_t: int,
        elapsed: float,
        success: bool,
        error: str | None = None,
        prompt_preview: str | None = None,
        output_preview: str | None = None,
        provider_route: list[str] | None = None,
    ) -> None:
        trail = current_trail()
        entry = {
            "timestamp": _utc(),
            "provider": provider,
            "model": model,
            "in_tokens": in_t,
            "out_tokens": out_t,
            "elapsed_s": round(elapsed, 2),
            "success": success,
            "trail_id": trail.get("trail_id", ""),
            "routine": trail.get("routine", ""),
        }
        if error:
            entry["error"] = error
        if prompt_preview:
            entry["prompt_preview"] = prompt_preview
        if output_preview:
            entry["output_preview"] = output_preview
        if provider_route:
            entry["provider_route"] = list(provider_route)
        self._usage.append(entry)
        if len(self._usage) > 5000:
            self._usage = self._usage[-5000:]
        try:
            with self._usage_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("Failed to persist cortex usage trail: %s", exc)

    def _ration_admit(self, provider: str, tokens: int) -> bool:
        if not self._instinct:
            return True
        if tokens <= 0:
            return True
        resource_key = f"{provider}_tokens"
        ok = self._instinct.consume_ration(resource_key, tokens)
        if not ok:
            self._emit_ration_signal(provider, tokens)
        return ok

    def _emit_ration_signal(self, provider: str, tokens: int) -> None:
        if not self._instinct:
            return
        today = time.strftime("%Y-%m-%d", time.gmtime())
        dedupe_key = f"ration_exceeded.{provider}.{today}"
        if self._instinct.get_pref(dedupe_key, "") == "1":
            return
        try:
            self._instinct.set_pref(dedupe_key, "1", source="system", changed_by="cortex")
            logger.warning("Provider ration exceeded: %s (%d tokens)", provider, tokens)
        except Exception as exc:
            logger.warning("Failed to record ration signal: %s", exc)

    def _load_usage(self) -> None:
        if not self._usage_path.exists():
            return
        try:
            lines = self._usage_path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            logger.warning("Failed to read cortex usage trail file: %s", exc)
            return
        loaded: list[dict] = []
        for line in lines[-5000:]:
            line = line.strip()
            if not line:
                continue
            try:
                loaded.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        self._usage = loaded

    def _extract_remaining_value(self, payload: Any) -> float | None:
        if isinstance(payload, (int, float)):
            return float(payload)
        if isinstance(payload, dict):
            for key in ("remaining", "remains", "remain", "quota_remaining"):
                if key in payload:
                    try:
                        return float(payload[key])
                    except (TypeError, ValueError):
                        pass
            data = payload.get("data")
            if data is not None:
                return self._extract_remaining_value(data)
        if isinstance(payload, list):
            for row in payload:
                value = self._extract_remaining_value(row)
                if value is not None:
                    return value
        return None
