#!/usr/bin/env python3
"""Run warmup Stage 3 test tasks and collect results.

Usage:
    python scripts/run_warmup_tasks.py                    # Run all tasks
    python scripts/run_warmup_tasks.py --task T01         # Run specific task
    python scripts/run_warmup_tasks.py --scene copilot    # Run tasks for scene
    python scripts/run_warmup_tasks.py --status           # Show results summary

Reference: SYSTEM_DESIGN.md §7.3 Stage 3
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

DAEMON_HOME = Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))
TASKS_FILE = DAEMON_HOME / "warmup" / "stage3_test_tasks.json"
RESULTS_DIR = DAEMON_HOME / "warmup" / "results" / "stage3"
API_BASE = os.environ.get("DAEMON_API_URL", "http://127.0.0.1:8100")


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_tasks() -> list[dict]:
    data = json.loads(TASKS_FILE.read_text())
    return data["tasks"]


def submit_task(task: dict) -> dict:
    """Submit a test task via the appropriate API endpoint."""
    scene = task.get("scene", "copilot")
    route = task.get("expected_route", "task")

    if route == "direct":
        # Single-step direct Job via /jobs/submit
        steps = [{
            "id": "step_0",
            "step_index": 0,
            "goal": task["input"],
            "agent_id": task["agents"][0],
            "execution_type": "agent",
            "depends_on": [],
        }]
    else:
        # Multi-step Job — build steps from agents list
        steps = []
        for i, agent_id in enumerate(task["agents"]):
            step = {
                "id": f"step_{i}",
                "step_index": i,
                "goal": f"{task['input']} (Step {i+1}: {agent_id} agent)",
                "agent_id": agent_id,
                "execution_type": "agent",
                "depends_on": [f"step_{i-1}"] if i > 0 else [],
            }
            steps.append(step)

    payload = {
        "title": f"[Warmup {task['id']}] {task['title']}",
        "steps": steps,
    }

    resp = httpx.post(f"{API_BASE}/jobs/submit", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def check_job_status(job_id: str, timeout_s: int = 300) -> dict:
    """Poll job status until completion or timeout."""
    start = time.time()
    while time.time() - start < timeout_s:
        resp = httpx.get(f"{API_BASE}/jobs?limit=50", timeout=10)
        jobs = resp.json()
        for job in jobs:
            if str(job.get("job_id")) == job_id:
                if job.get("status") == "closed":
                    return job
        time.sleep(5)
    return {"status": "timeout", "job_id": job_id}


def run_task(task: dict) -> dict:
    """Run a single warmup task and record result."""
    _log(f"Running {task['id']}: {task['title']}")
    _log(f"  Scene: {task['scene']}, Route: {task['expected_route']}")
    _log(f"  Agents: {', '.join(task['agents'])}")

    started = time.time()

    try:
        submit_result = submit_task(task)
        job_id = submit_result.get("job_id", "")
        _log(f"  Submitted: job_id={job_id}")

        # Wait for completion (~3min per agent, min 5min)
        timeout = max(420, 300 * len(task["agents"]))
        job_result = check_job_status(job_id, timeout_s=timeout)

        elapsed = time.time() - started
        sub_status = job_result.get("sub_status", "unknown")
        _log(f"  Result: {sub_status} ({elapsed:.1f}s)")

        result = {
            "task_id": task["id"],
            "title": task["title"],
            "scene": task["scene"],
            "agents": task["agents"],
            "skills_tested": task.get("skills_tested", []),
            "job_id": job_id,
            "status": sub_status,
            "elapsed_s": round(elapsed, 1),
            "acceptance_criteria": task.get("acceptance_criteria", []),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        if sub_status not in ("completed", "succeeded"):
            result["error"] = job_result.get("error_message", "")

        return result

    except Exception as exc:
        elapsed = time.time() - started
        _log(f"  Error: {exc}")
        return {
            "task_id": task["id"],
            "title": task["title"],
            "status": "error",
            "error": str(exc)[:500],
            "elapsed_s": round(elapsed, 1),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }


def show_status():
    """Show summary of existing results."""
    if not RESULTS_DIR.exists():
        _log("No results yet.")
        return

    results = []
    for f in sorted(RESULTS_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        if isinstance(data, list):
            results.extend(data)
        else:
            results.append(data)

    if not results:
        _log("No results yet.")
        return

    passed = sum(1 for r in results if r.get("status") in ("completed", "succeeded"))
    failed = sum(1 for r in results if r.get("status") not in ("completed", "succeeded"))
    _log(f"Total: {len(results)} tasks, {passed} passed, {failed} failed")

    for r in results:
        status_icon = "✅" if r.get("status") in ("completed", "succeeded") else "❌"
        _log(f"  {status_icon} {r.get('task_id', '?')}: {r.get('title', '?')} ({r.get('elapsed_s', 0):.0f}s)")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Run warmup Stage 3 test tasks")
    parser.add_argument("--task", help="Run specific task by ID (e.g. T01)")
    parser.add_argument("--scene", help="Run tasks for specific scene")
    parser.add_argument("--status", action="store_true", help="Show results summary")
    args = parser.parse_args()

    if args.status:
        show_status()
        return 0

    tasks = load_tasks()

    if args.task:
        tasks = [t for t in tasks if t["id"] == args.task]
        if not tasks:
            _log(f"Task {args.task} not found")
            return 1

    if args.scene:
        tasks = [t for t in tasks if t["scene"] == args.scene]

    _log(f"Running {len(tasks)} warmup task(s)")
    _log("=" * 50)

    results = []
    for task in tasks:
        result = run_task(task)
        results.append(result)
        _log("")

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    result_path = RESULTS_DIR / f"run_{ts}.json"
    result_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    _log(f"Results saved: {result_path}")

    # Summary
    _log("=" * 50)
    passed = sum(1 for r in results if r.get("status") in ("completed", "succeeded"))
    _log(f"Summary: {passed}/{len(results)} tasks passed")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
