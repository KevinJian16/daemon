"""System routes — minimal system management endpoints.

In the new architecture, system management is handled by:
  - admin agent (L2) via Temporal workflows
  - scripts/start.py, scripts/stop.py
  - Self-healing workflow (§7.8)

This file is kept for potential future system control endpoints.
"""
