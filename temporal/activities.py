"""Daemon Activities — Temporal activity implementations for Agent steps and Spine Routines."""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from temporalio import activity


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _daemon_home() -> Path:
    return Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))


def _openclaw_home() -> Path:
    v = os.environ.get("OPENCLAW_HOME")
    return Path(v) if v else _daemon_home() / "openclaw"


def _load_openclaw_config(oc_home: Path) -> dict:
    cfg_path = oc_home / "openclaw.json"
    if not cfg_path.exists():
        raise RuntimeError(f"openclaw.json not found at {cfg_path}")
    return json.loads(cfg_path.read_text())


def _gateway_headers(cfg: dict) -> dict:
    token = cfg.get("gateway", {}).get("auth", {}).get("token", "")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _gateway_url(cfg: dict) -> str:
    port = cfg.get("gateway", {}).get("port", 18789)
    return f"http://127.0.0.1:{port}"


class DaemonActivities:
    """All Temporal activities. Instantiated once per Worker process."""

    def __init__(self) -> None:
        self._home = _daemon_home()
        self._oc_home = _openclaw_home()
        self._oc_cfg: dict | None = None
        try:
            self._oc_cfg = _load_openclaw_config(self._oc_home)
        except Exception as exc:
            activity.logger.warning("Failed to load openclaw config from %s: %s", self._oc_home, exc)

    # ── OpenClaw step ─────────────────────────────────────────────────────────

    @activity.defn(name="activity_openclaw_step")
    async def activity_openclaw_step(self, run_root: str, plan: dict, step: dict) -> dict:
        """Execute one DAG step via OpenClaw Gateway HTTP API."""
        if not self._oc_cfg:
            raise RuntimeError("OpenClaw not configured (OPENCLAW_HOME missing or openclaw.json invalid)")

        agent_id = str(step.get("agent") or "").strip()
        step_id = str(step.get("id") or "step").strip()
        task_id = str(plan.get("task_id") or run_root.split("/")[-1] or uuid.uuid4().hex[:8])
        session_key = f"agent:{agent_id}:task:{task_id}:{step_id}"
        instruction = str(step.get("instruction") or step.get("message") or "").strip()
        timeout_s = int(step.get("timeout_s") or plan.get("default_step_timeout_s") or 480)

        gw_url = _gateway_url(self._oc_cfg)
        headers = _gateway_headers(self._oc_cfg)

        # Build context payload including Fabric snapshots.
        context_payload = self._build_step_context(run_root, plan, step)

        # Send message to Agent.
        send_body = {
            "tool": "sessions_send",
            "args": {
                "session_key": session_key,
                "message": f"{instruction}\n\n{json.dumps(context_payload, ensure_ascii=False)}" if context_payload else instruction,
            },
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{gw_url}/tools/invoke", json=send_body, headers=headers)
            resp.raise_for_status()

        # Poll for completion.
        deadline = time.time() + timeout_s
        poll_interval = 5
        last_content = ""

        while time.time() < deadline:
            await asyncio.sleep(poll_interval)
            async with httpx.AsyncClient(timeout=15) as client:
                hist_resp = await client.post(
                    f"{gw_url}/tools/invoke",
                    json={"tool": "sessions_history", "args": {"session_key": session_key, "limit": 1}},
                    headers=headers,
                )
                hist_resp.raise_for_status()
                hist_data = hist_resp.json()

            messages = (hist_data.get("result") or {}).get("messages") or (hist_data.get("result") or [])
            if not isinstance(messages, list):
                messages = []

            latest = messages[-1] if messages else {}
            content = latest.get("content") or latest.get("text") or ""
            role = latest.get("role") or ""

            if role == "assistant" and content and content != last_content:
                last_content = content
                # Check for completion signals.
                if any(signal in content.lower() for signal in ["[done]", "[complete]", "task complete", "completed successfully"]):
                    output_path = self._write_step_output(run_root, step_id, content)
                    return {"status": "ok", "step_id": step_id, "agent": agent_id, "session_key": session_key, "output_path": output_path}

            poll_interval = min(poll_interval * 1.2, 30)

        # Timeout — mark as degraded, not error (Temporal will handle retry policy).
        activity.logger.warning(f"Step {step_id} timed out after {timeout_s}s — marking degraded")
        return {
            "status": "degraded",
            "step_id": step_id,
            "agent": agent_id,
            "session_key": session_key,
            "error": f"timeout_after_{timeout_s}s",
            "degraded": True,
        }

    # ── Spine routine ─────────────────────────────────────────────────────────

    @activity.defn(name="activity_spine_routine")
    async def activity_spine_routine(self, run_root: str, plan: dict, routine_name: str) -> dict:
        """Execute a Spine Routine directly (no OpenClaw, no LLM unless hybrid)."""
        from fabric.memory import MemoryFabric
        from fabric.playbook import PlaybookFabric
        from fabric.compass import CompassFabric
        from runtime.cortex import Cortex
        from spine.nerve import Nerve
        from spine.trace import Tracer
        from spine.routines import SpineRoutines

        home = self._home
        state = home / "state"
        memory = MemoryFabric(state / "memory.db")
        playbook = PlaybookFabric(state / "playbook.db")
        compass = CompassFabric(state / "compass.db")
        cortex = Cortex(compass)
        nerve = Nerve()
        tracer = Tracer(state / "traces")

        routines = SpineRoutines(
            memory=memory, playbook=playbook, compass=compass,
            cortex=cortex, nerve=nerve, tracer=tracer,
            daemon_home=home, openclaw_home=self._oc_home,
        )

        method = getattr(routines, routine_name.replace("spine.", ""), None)
        if not callable(method):
            raise ValueError(f"Unknown spine routine: {routine_name}")
        result = method()
        return {"status": "ok", "routine": routine_name, "result": result}

    # ── Delivery finalization ─────────────────────────────────────────────────

    @activity.defn(name="activity_finalize_delivery")
    async def activity_finalize_delivery(self, run_root: str, plan: dict, step_results: list[dict]) -> dict:
        """Structural quality gate + archive to outcome/ + Nerve emit."""
        from fabric.compass import CompassFabric

        home = self._home
        state = home / "state"
        compass = CompassFabric(state / "compass.db")

        task_type = str(plan.get("task_type") or "default").strip()
        profile = compass.get_quality_profile(task_type)

        # Find render output.
        render_path = self._find_render_output(run_root, step_results)
        if not render_path:
            return {"ok": False, "error_code": "render_output_missing", "detail": "No render output found"}

        content = render_path.read_text()

        # Structural quality checks.
        check_result = self._structural_check(content, profile)
        if not check_result["ok"]:
            return {
                "ok": False,
                "error_code": check_result["error_code"],
                "detail": check_result["detail"],
            }

        # Archive to outcome/.
        outcome_path = self._archive_outcome(run_root, plan, render_path, step_results)

        # Update outcome index.
        self._update_outcome_index(outcome_path, plan)

        # Update task status.
        self._update_task_status(run_root, plan, "completed")

        # Emit delivery_completed for spine.record.
        # (Nerve runs in-process; in distributed setup this would use a signal.)
        task_id = str(plan.get("task_id") or "")
        activity.logger.info(f"Delivery completed for task {task_id}")

        return {
            "ok": True,
            "outcome_path": str(outcome_path),
            "task_id": task_id,
            "archived_utc": _utc(),
        }

    # ── Task status ───────────────────────────────────────────────────────────

    @activity.defn(name="activity_update_task_status")
    async def activity_update_task_status(self, run_root: str, plan: dict, status: str) -> dict:
        """Update task status in state/tasks.json (append-only for safety)."""
        self._update_task_status(run_root, plan, status)
        return {"ok": True, "status": status}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_step_context(self, run_root: str, plan: dict, step: dict) -> dict:
        """Attach Fabric snapshots from state/snapshots/ as context for the Agent."""
        snapshots_dir = self._home / "state" / "snapshots"
        context: dict = {}
        for snap_name in ("compass_snapshot.json",):
            snap_path = snapshots_dir / snap_name
            if snap_path.exists():
                try:
                    context[snap_name.replace(".json", "")] = json.loads(snap_path.read_text())
                except Exception as exc:
                    activity.logger.warning("Failed to load snapshot %s: %s", snap_name, exc)
        return context

    def _write_step_output(self, run_root: str, step_id: str, content: str) -> str:
        out_dir = Path(run_root) / "steps" / step_id / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "output.md"
        out_file.write_text(content)
        return str(out_file)

    def _find_render_output(self, run_root: str, step_results: list[dict]) -> Path | None:
        rp = Path(run_root)
        # Look for render step output.
        for res in reversed(step_results):
            sid = res.get("step_id", "")
            if "render" in sid.lower():
                out = rp / "steps" / sid / "output" / "output.md"
                if out.exists():
                    return out
        # Fallback: any .html or .md file in deliver/ subdirectories.
        for candidate in sorted(rp.glob("**/deliver/*.html"), key=lambda p: p.stat().st_mtime, reverse=True):
            return candidate
        for candidate in sorted(rp.glob("**/output/*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            return candidate
        return None

    def _structural_check(self, content: str, profile: dict) -> dict:
        """Deterministic structural quality checks — no LLM needed."""
        # Forbidden markers.
        for marker in (profile.get("forbidden_markers") or []):
            if marker.lower() in content.lower():
                return {"ok": False, "error_code": "forbidden_marker", "detail": f"Contains forbidden marker: {marker}"}

        # Minimum word count.
        min_words = int(profile.get("min_word_count") or 0)
        word_count = len(content.split())
        if min_words and word_count < min_words:
            return {"ok": False, "error_code": "word_count_too_low", "detail": f"{word_count} < {min_words}"}

        return {"ok": True}

    def _archive_outcome(self, run_root: str, plan: dict, render_path: Path, step_results: list[dict]) -> Path:
        task_type = str(plan.get("task_type") or "manual")
        task_id = str(plan.get("task_id") or uuid.uuid4().hex[:8])
        title = str(plan.get("title") or task_id)[:60].replace("/", "-")

        # Choose outcome category.
        if task_type in ("daily_brief", "weekly_brief"):
            today = time.strftime("%Y-%m-%d")
            dest = self._home / "outcome" / "scheduled" / task_type / today
        else:
            dest = self._home / "outcome" / "manual" / title

        dest.mkdir(parents=True, exist_ok=True)

        # Copy render output.
        suffix = render_path.suffix or ".html"
        dest_file = dest / f"report{suffix}"
        dest_file.write_text(render_path.read_text())

        # Write manifest.
        manifest = {
            "task_id": task_id,
            "title": title,
            "task_type": task_type,
            "run_root": run_root,
            "steps": len(step_results),
            "delivered_utc": _utc(),
        }
        (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

        return dest

    def _update_outcome_index(self, outcome_path: Path, plan: dict) -> None:
        index_path = self._home / "outcome" / "index.json"
        try:
            index = json.loads(index_path.read_text())
        except Exception as exc:
            activity.logger.warning("Failed to read outcome index %s: %s", index_path, exc)
            index = []
        entry = {
            "path": str(outcome_path.relative_to(self._home / "outcome")),
            "title": plan.get("title", ""),
            "task_type": plan.get("task_type", "manual"),
            "task_id": plan.get("task_id", ""),
            "delivered_utc": _utc(),
        }
        index.append(entry)
        # Keep last 1000 entries.
        index_path.write_text(json.dumps(index[-1000:], ensure_ascii=False, indent=2))

    def _update_task_status(self, run_root: str, plan: dict, status: str) -> None:
        tasks_path = self._home / "state" / "tasks.json"
        try:
            tasks = json.loads(tasks_path.read_text()) if tasks_path.exists() else []
        except Exception as exc:
            activity.logger.warning("Failed to read tasks.json %s: %s", tasks_path, exc)
            tasks = []
        task_id = str(plan.get("task_id") or "")
        for task in tasks:
            if task.get("task_id") == task_id:
                task["status"] = status
                task["updated_utc"] = _utc()
                break
        else:
            tasks.append({"task_id": task_id, "status": status, "updated_utc": _utc(), "run_root": run_root})
        tasks_path.parent.mkdir(parents=True, exist_ok=True)
        # Write atomically via temp file to avoid partial writes.
        tmp = tasks_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2))
        tmp.replace(tasks_path)
