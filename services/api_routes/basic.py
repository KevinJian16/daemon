"""Basic API routes — health and status.

In the new architecture (7th draft), most routes are handled by:
  - scenes.py (L1 agent interaction)
  - plane_webhook.py (Plane webhooks)

This file is kept minimal. The /status and /health endpoints are
defined inline in api.py.
"""
