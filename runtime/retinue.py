"""Retinue — pre-created agent retinue with per-Deed isolation.

Each role (scout/sage/artificer/arbiter/scribe/envoy) has N pre-registered
openclaw agent instances. Deeds allocate idle instances, use them for the
duration of execution, then clean up and return them.

See: daemon_实施方案.md §7.1-7.2
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

POOL_ROLES = ["scout", "sage", "artificer", "arbiter", "scribe", "envoy"]
DEFAULT_POOL_SIZE = 24
MIN_POOL_SIZE = 16


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class PoolExhausted(Exception):
    """No idle instances available for the requested role."""


class Retinue:
    """Manages pre-created openclaw agent retinue instances.

    Retinue state persisted in state/pool_status.json.
    Thread safety via Ledger._locked_rw on the pool file.
    """

    def __init__(
        self,
        daemon_home: Path,
        openclaw_home: Path,
        pool_size: int = DEFAULT_POOL_SIZE,
    ) -> None:
        self._home = daemon_home
        self._oc_home = openclaw_home
        self._pool_size = max(MIN_POOL_SIZE, pool_size)
        self._pool_file = daemon_home / "state" / "pool_status.json"
        self._templates_dir = daemon_home / "templates"

    def _load_pool(self) -> list[dict]:
        if not self._pool_file.exists():
            return []
        try:
            data = json.loads(self._pool_file.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_pool(self, pool: list[dict]) -> None:
        self._pool_file.parent.mkdir(parents=True, exist_ok=True)
        self._pool_file.write_text(
            json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _mutate_pool(self, fn) -> Any:
        """Atomic read-mutate-write on pool_status.json."""
        import fcntl

        self._pool_file.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._pool_file.parent / ".pool_status.lock"
        lock_path.touch(exist_ok=True)
        with open(lock_path, "r") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                pool = self._load_pool()
                result = fn(pool)
                self._save_pool(pool)
                return result
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    # ── Allocation ────────────────────────────────────────────────────────────

    def allocate(self, role: str, deed_id: str) -> dict:
        """Allocate an idle retinue instance for the given role.

        Steps:
        1. Find idle instance of role
        2. Copy templates/<role>/ → instance agentDir
        3. Mark occupied with deed_id
        4. Return instance info

        Raises PoolExhausted if no idle instances available.
        """
        if role not in POOL_ROLES:
            raise ValueError(f"Invalid pool role: {role}")

        def _do_allocate(pool: list[dict]) -> dict:
            for inst in pool:
                if inst.get("role") == role and inst.get("status") == "idle":
                    instance_id = inst.get("instance_id", "")
                    inst["status"] = "occupied"
                    inst["deed_id"] = deed_id
                    inst["allocated_utc"] = _utc()
                    inst["session_key"] = f"agent:{instance_id}:main"
                    self._fill_templates(inst)
                    self.write_psyche_snapshot(instance_id, self._default_psyche_snapshot())
                    return dict(inst)
            raise PoolExhausted(f"No idle {role} instances (pool_size={self._pool_size})")

        return self._mutate_pool(_do_allocate)

    def release(self, instance_id: str, deed_id: str | None = None) -> None:
        """Release a retinue instance back to idle state.

        Steps:
        1. Clean agentDir (remove template files)
        2. Clean workspace/memory/
        3. Mark idle
        """

        def _do_release(pool: list[dict]) -> None:
            for inst in pool:
                if inst.get("instance_id") == instance_id:
                    if deed_id and inst.get("deed_id") != deed_id:
                        logger.warning(
                            "Release mismatch: instance %s has deed_id=%s, expected %s",
                            instance_id, inst.get("deed_id"), deed_id,
                        )
                    self._destroy_instance_sessions(instance_id)
                    self._clean_instance(inst)
                    inst["status"] = "idle"
                    inst["deed_id"] = None
                    inst["allocated_utc"] = None
                    inst["session_key"] = None
                    return
            logger.warning("Instance %s not found in retinue", instance_id)

        self._mutate_pool(_do_release)

    def get_instance(self, instance_id: str) -> dict | None:
        pool = self._load_pool()
        for inst in pool:
            if inst.get("instance_id") == instance_id:
                return dict(inst)
        return None

    # ── Startup recovery ──────────────────────────────────────────────────────

    def recover_on_startup(self) -> dict:
        """Scan all retinue instances, clean up any left in occupied state."""
        recovered = []

        def _do_recover(pool: list[dict]) -> list[str]:
            for inst in pool:
                if inst.get("status") == "occupied":
                    iid = inst.get("instance_id", "")
                    logger.info(
                        "Recovering orphaned instance %s (was deed %s)",
                        iid, inst.get("deed_id"),
                    )
                    self._destroy_instance_sessions(iid)
                    self._clean_instance(inst)
                    inst["status"] = "idle"
                    inst["deed_id"] = None
                    inst["allocated_utc"] = None
                    inst["session_key"] = None
                    recovered.append(iid)
            return recovered

        self._mutate_pool(_do_recover)
        return {"recovered": recovered, "count": len(recovered)}

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return retinue usage statistics."""
        pool = self._load_pool()
        by_role: dict[str, dict] = {}
        for inst in pool:
            role = inst.get("role", "unknown")
            if role not in by_role:
                by_role[role] = {"total": 0, "idle": 0, "occupied": 0}
            by_role[role]["total"] += 1
            if inst.get("status") == "idle":
                by_role[role]["idle"] += 1
            else:
                by_role[role]["occupied"] += 1
        total = len(pool)
        idle = sum(1 for i in pool if i.get("status") == "idle")
        return {
            "retinue_size": self._pool_size,
            "total_instances": total,
            "idle": idle,
            "occupied": total - idle,
            "by_role": by_role,
        }

    # ── Template management ───────────────────────────────────────────────────

    # Files to copy from base agent workspace → pool instance workspace.
    _WORKSPACE_TEMPLATE_FILES = {
        "SOUL.md", "TOOLS.md", "AGENTS.md", "IDENTITY.md",
        "BOOTSTRAP.md", "HEARTBEAT.md", "USER.md",
    }

    def _fill_templates(self, inst: dict) -> None:
        """Copy role workspace files from the base agent into the pool instance.

        Source: openclaw/workspace/{role}/  (the base agent)
        Dest:   openclaw/workspace/{role}_{N}/  (the pool instance)

        Only copies role-definition markdown files and role-specific
        subdirs (e.g. skills/).  Skips .git, memory/, .openclaw/.
        """
        role = inst.get("role", "")
        base_workspace = self._oc_home / "workspace" / role
        inst_workspace = Path(inst.get("workspace_dir", ""))
        if not base_workspace.exists() or not inst_workspace.parent.exists():
            return
        inst_workspace.mkdir(parents=True, exist_ok=True)

        skip_dirs = {".git", ".openclaw", "memory"}
        for src in base_workspace.iterdir():
            name = src.name
            if src.is_file() and name in self._WORKSPACE_TEMPLATE_FILES:
                shutil.copy2(src, inst_workspace / name)
            elif src.is_dir() and name not in skip_dirs:
                dst_dir = inst_workspace / name
                if dst_dir.exists():
                    shutil.rmtree(dst_dir)
                shutil.copytree(src, dst_dir)

    def _destroy_instance_sessions(self, instance_id: str) -> None:
        """Delete session JSONL files for a pool instance.

        Forces fresh session creation on next use, which reloads MEMORY.md.
        """
        sessions_dir = self._oc_home / "agents" / instance_id / "sessions"
        if not sessions_dir.is_dir():
            return
        for f in sessions_dir.iterdir():
            if f.suffix == ".jsonl":
                try:
                    f.unlink()
                except Exception as exc:
                    logger.warning("Failed to delete session file %s: %s", f, exc)

    def _clean_instance(self, inst: dict) -> None:
        """Remove template files and workspace memory from pool instance.

        Restores workspace to empty state:  only the bare directory remains.
        Does NOT touch the agentDir (agent config stays).
        """
        workspace = Path(inst.get("workspace_dir", ""))
        if not workspace.exists():
            return
        for item in workspace.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as exc:
                logger.warning("Failed to clean %s: %s", item, exc)

    def write_psyche_snapshot(self, instance_id: str, memory_snapshot: str) -> None:
        """Write Psyche Memory snapshot into instance workspace/memory/MEMORY.md."""
        inst = self.get_instance(instance_id)
        if not inst:
            logger.warning("Cannot write snapshot: instance %s not found", instance_id)
            return
        workspace_dir = Path(inst.get("workspace_dir", ""))
        mem_dir = workspace_dir / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        (mem_dir / "MEMORY.md").write_text(memory_snapshot, encoding="utf-8")

    def _default_psyche_snapshot(self) -> str:
        snap_path = self._home / "state" / "snapshots" / "memory_snapshot.json"
        try:
            if snap_path.exists():
                data = json.loads(snap_path.read_text(encoding="utf-8"))
                entries = data.get("entries") if isinstance(data, dict) else []
                if isinstance(entries, list) and entries:
                    lines = ["# Psyche Memory Snapshot", ""]
                    for row in entries[:40]:
                        if not isinstance(row, dict):
                            continue
                        content = str(row.get("content") or "").strip()
                        if not content:
                            continue
                        tags = row.get("tags") if isinstance(row.get("tags"), list) else []
                        tag_text = f" [{', '.join(str(tag) for tag in tags[:6])}]" if tags else ""
                        lines.append(f"- {content[:280]}{tag_text}")
                    if len(lines) > 2:
                        return "\n".join(lines).strip() + "\n"
        except Exception:
            pass
        return "# Psyche Memory Snapshot\n\n- No relay snapshot available yet.\n"


# ── Bootstrap: register retinue instances in openclaw.json ─────────────────────


def register_retinue_instances(
    openclaw_home: Path,
    daemon_home: Path,
    pool_size: int = DEFAULT_POOL_SIZE,
) -> dict:
    """Register N retinue instances per role in openclaw.json and create directories.

    Called once during first bootstrap. Triggers gateway restart.
    Returns a report of what was created.
    """
    pool_size = max(MIN_POOL_SIZE, pool_size)
    cfg_path = openclaw_home / "openclaw.json"
    if not cfg_path.exists():
        return {"ok": False, "error": f"openclaw.json not found at {cfg_path}"}

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    agents = cfg.get("agents", {})
    agent_list = agents.get("list", [])
    existing_ids = {str(a.get("id", "")) for a in agent_list if isinstance(a, dict)}

    # Find a role agent to use as template for model/provider settings
    role_templates: dict[str, dict] = {}
    for agent in agent_list:
        if not isinstance(agent, dict):
            continue
        aid = str(agent.get("id", ""))
        if aid in POOL_ROLES:
            role_templates[aid] = agent

    created_instances: list[dict] = []
    pool_status: list[dict] = []

    for role in POOL_ROLES:
        template = role_templates.get(role, {})
        for i in range(pool_size):
            instance_id = f"{role}_{i}"
            if instance_id in existing_ids:
                # Already registered, just ensure directories exist
                agent_dir = openclaw_home / "agents" / instance_id
                workspace_dir = openclaw_home / "workspace" / instance_id
                agent_dir.mkdir(parents=True, exist_ok=True)
                workspace_dir.mkdir(parents=True, exist_ok=True)
                pool_status.append({
                    "instance_id": instance_id,
                    "role": role,
                    "status": "idle",
                    "deed_id": None,
                    "allocated_utc": None,
                    "session_key": None,
                    "agent_dir": str(agent_dir),
                    "workspace_dir": str(workspace_dir),
                })
                continue

            agent_dir = openclaw_home / "agents" / instance_id
            workspace_dir = openclaw_home / "workspace" / instance_id
            agent_dir.mkdir(parents=True, exist_ok=True)
            workspace_dir.mkdir(parents=True, exist_ok=True)

            # Create agent entry based on role template
            agent_entry = {
                "id": instance_id,
                "model": template.get("model", ""),
                "provider": template.get("provider", ""),
            }
            # Copy relevant config from template
            for key in ("systemPrompt", "tools", "mcpServers"):
                if key in template:
                    agent_entry[key] = template[key]
            # Set instance-specific paths
            agent_entry["agentDir"] = str(agent_dir)
            agent_entry["workspace"] = str(workspace_dir)

            agent_list.append(agent_entry)
            created_instances.append({"instance_id": instance_id, "role": role})

            pool_status.append({
                "instance_id": instance_id,
                "role": role,
                "status": "idle",
                "deed_id": None,
                "allocated_utc": None,
                "session_key": None,
                "agent_dir": str(agent_dir),
                "workspace_dir": str(workspace_dir),
            })

    agents["list"] = agent_list
    cfg["agents"] = agents
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write pool status
    pool_file = daemon_home / "state" / "pool_status.json"
    pool_file.parent.mkdir(parents=True, exist_ok=True)
    pool_file.write_text(json.dumps(pool_status, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "retinue_size": pool_size,
        "roles": POOL_ROLES,
        "total_instances": len(pool_status),
        "newly_created": len(created_instances),
        "created": created_instances[:10],  # truncate for readability
    }


# Backward compatibility aliases
AgentPoolManager = Retinue
register_pool_instances = register_retinue_instances
