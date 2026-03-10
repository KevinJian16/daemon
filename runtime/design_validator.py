"""Unified Design (move DAG) validation.

Consolidates the 5 checks from SPEC §7.3:
1. DAG is acyclic
2. All node IDs are valid
3. All dependency references are valid
4. Move count ≤ dag_budget
5. At least one terminal move exists
"""
from __future__ import annotations

from runtime.brief import Brief

VALID_AGENTS = frozenset({
    "counsel", "scout", "sage", "artificer", "arbiter", "scribe", "envoy", "spine",
})


def validate_design(plan: dict) -> tuple[bool, str]:
    """Validate a plan's move list (Design).

    Returns (True, "") on success or (False, reason) on failure.
    """
    moves = plan.get("moves") or []
    if not isinstance(moves, list) or not moves:
        return False, "plan must contain a non-empty moves list"

    ids: set[str] = set()
    normalized: list[tuple[str, dict]] = []

    # Check 2: valid node IDs, no duplicates, valid agents.
    for i, step in enumerate(moves):
        if not isinstance(step, dict):
            return False, f"move {i} is not an object"
        sid = str(step.get("id") or f"move_{i}")
        if sid in ids:
            return False, f"duplicate move id: {sid}"
        ids.add(sid)
        normalized.append((sid, step))
        agent = str(step.get("agent") or "")
        if agent and agent not in VALID_AGENTS:
            return False, f"move {sid}: unknown agent type {agent!r}"

    # Check 3: all dependency references point to known IDs.
    in_degree: dict[str, int] = {sid: 0 for sid, _ in normalized}
    for sid, step in normalized:
        for dep in step.get("depends_on") or []:
            if dep not in ids:
                return False, f"move {sid}: depends_on unknown move {dep!r}"
            in_degree[sid] = in_degree.get(sid, 0) + 1

    # Check 1: DAG is acyclic (Kahn's algorithm).
    queue = [sid for sid, deg in in_degree.items() if deg == 0]
    visited = 0
    children: dict[str, list[str]] = {sid: [] for sid, _ in normalized}
    for sid, step in normalized:
        for dep in step.get("depends_on") or []:
            children[dep].append(sid)
    topo_queue = list(queue)
    while topo_queue:
        node = topo_queue.pop(0)
        visited += 1
        for child in children.get(node, []):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                topo_queue.append(child)
    if visited != len(normalized):
        return False, "plan contains a cycle in the move DAG"

    # Check 4: move count ≤ dag_budget.
    brief = Brief.from_dict(plan.get("brief") if isinstance(plan.get("brief"), dict) else {})
    if len(moves) > int(brief.dag_budget):
        return False, f"move count {len(moves)} exceeds dag_budget {brief.dag_budget}"

    # Check 5: at least one terminal move (no other move depends on it).
    dependents: set[str] = set()
    for _, step in normalized:
        for dep in step.get("depends_on") or []:
            dependents.add(dep)
    terminal = [sid for sid, _ in normalized if sid not in dependents]
    if not terminal:
        return False, "plan has no terminal moves"

    return True, ""
