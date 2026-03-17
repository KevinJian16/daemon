"""Shared Google OAuth2 helper for Gmail, Calendar, Docs, Drive MCP servers.

First run opens browser for consent. Token cached at ~/.daemon/google_token.json.
Subsequent runs use cached token (auto-refresh if expired).
"""
from __future__ import annotations

import os
import wsgiref.util
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow, _RedirectWSGIApp
from googleapiclient.discovery import build

TOKEN_DIR = Path.home() / ".daemon"
TOKEN_PATH = TOKEN_DIR / "google_token.json"

ALL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]

_SUCCESS_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Daemon</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@400;600&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Bricolage Grotesque',system-ui,sans-serif;background:#fdfaf7;color:#3a2f4a;display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{text-align:center;padding:3rem 4rem;background:#fff;border-radius:1rem;box-shadow:0 4px 24px rgba(0,0,0,.06)}
.icon{width:48px;height:48px;border-radius:12px;margin-bottom:1.25rem}
h1{font-size:1.2rem;font-weight:600;margin-bottom:.5rem}
p{font-size:.875rem;color:#8a8094;line-height:1.6}
</style>
</head>
<body>
<div class="card">
<img class="icon" src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI1MTIiIGhlaWdodD0iNTEyIiB2aWV3Qm94PSIwIDAgNTEyIDUxMiI+CiAgPGRlZnM+CiAgICA8bGluZWFyR3JhZGllbnQgaWQ9ImJnIiB4MT0iMCIgeTE9IjAiIHgyPSIwLjUiIHkyPSIxIj4KICAgICAgPHN0b3Agb2Zmc2V0PSIwJSIgc3RvcC1jb2xvcj0iI0Q4QzRFRCIvPgogICAgICA8c3RvcCBvZmZzZXQ9IjEwMCUiIHN0b3AtY29sb3I9IiNCOTkyREEiLz4KICAgIDwvbGluZWFyR3JhZGllbnQ+CiAgPC9kZWZzPgogIDxyZWN0IHdpZHRoPSI1MTIiIGhlaWdodD0iNTEyIiByeD0iMTEyIiBmaWxsPSJ1cmwoI2JnKSIvPgogIDxnIHRyYW5zZm9ybT0idHJhbnNsYXRlKDc2LDY4KSBzY2FsZSgyMi41KSI+CiAgICA8cGF0aCBmaWxsPSJ3aGl0ZSIgZD0iTTE1LjgwNy41MzFjLS4xNzQtLjE3Ny0uNDEtLjI4OS0uNjQtLjM2M2EzLjggMy44IDAgMCAwLS44MzMtLjE1Yy0uNjItLjA0OS0xLjM5NCAwLTIuMjUyLjE3NUMxMC4zNjUuNTQ1IDguMjY0IDEuNDE1IDYuMzE1IDMuMVMzLjE0NyA2LjgyNCAyLjU1NyA4LjUyM2MtLjI5NC44NDctLjQ0IDEuNjM0LS40MjkgMi4yNjguMDA1LjMxNi4wNS42Mi4xNTQuODhxLjAyNS4wNjEuMDU2LjEyMkE2OCA2OCAwIDAgMCAuMDggMTUuMTk4YS41My41MyAwIDAgMCAuMTU3LjcyLjUwNC41MDQgMCAwIDAgLjcwNS0uMTYgNjggNjggMCAwIDEgMi4xNTgtMy4yNmMuMjg1LjE0MS42MTYuMTk1Ljk1OC4xODIuNTEzLS4wMiAxLjA5OC0uMTg4IDEuNzIzLS40OSAxLjI1LS42MDUgMi43NDQtMS43ODcgNC4zMDMtMy42NDJsMS41MTgtMS41NWEuNTMuNTMgMCAwIDAgMC0uNzM5bC0uNzI5LS43NDQgMS4zMTEuMjA5YS41LjUgMCAwIDAgLjQ0My0uMTVsLjY2My0uNjg0Yy42NjMtLjY4IDEuMjkyLTEuMzI1IDEuNzYzLTEuODkyLjMxNC0uMzc4LjU4NS0uNzUyLjc1NC0xLjEwNy4xNjMtLjM0NS4yNzgtLjc3My4xMTItMS4xODhhLjUuNSAwIDAgMC0uMTEyLS4xNzJNMy43MzMgMTEuNjJDNS4zODUgOS4zNzQgNy4yNCA3LjIxNSA5LjMwOSA1LjM5NGwxLjIxIDEuMjM0LTEuMTcxIDEuMTk2LS4wMjcuMDNjLTEuNSAxLjc4OS0yLjg5MSAyLjg2Ny0zLjk3NyAzLjM5My0uNTQ0LjI2My0uOTkuMzc4LTEuMzI0LjM5YTEuMyAxLjMgMCAwIDEtLjI4Ny0uMDE4Wm02Ljc2OS03LjIyYzEuMzEtMS4wMjggMi43LTEuOTE0IDQuMTcyLTIuNmE3IDcgMCAwIDEtLjQuNTIzYy0uNDQyLjUzMy0xLjAyOCAxLjEzNC0xLjY4MSAxLjgwNGwtLjUxLjUyNHptMy4zNDYtMy4zNTdDOS41OTQgMy4xNDcgNi4wNDUgNi44IDMuMTQ5IDEwLjY3OGMuMDA3LS40NjQuMTIxLTEuMDg2LjM3LTEuODA2LjUzMy0xLjUzNSAxLjY1LTMuNDE1IDMuNDU1LTQuOTc2IDEuODA3LTEuNTYxIDMuNzQ2LTIuMzYgNS4zMS0yLjY4YTggOCAwIDAgMSAxLjU2NC0uMTczIi8+CiAgPC9nPgo8L3N2Zz4K" />
<h1>Authorization Complete</h1>
<p>Daemon has been granted access to your Google account.<br>You can close this window.</p>
</div>
</body>
</html>"""


class _BrandedRedirectApp(_RedirectWSGIApp):
    """Override to serve HTML instead of plain text."""

    def __call__(self, environ, start_response):
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        self.last_request_uri = wsgiref.util.request_uri(environ)
        return [self._success_message.encode("utf-8")]


def _get_client_config() -> dict:
    client_id = os.environ.get("GOOGLE_DESKTOP_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_DESKTOP_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise RuntimeError("GOOGLE_DESKTOP_CLIENT_ID and GOOGLE_DESKTOP_CLIENT_SECRET must be set in .env")
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def get_credentials(scopes: list[str] | None = None) -> Credentials:
    """Get valid Google credentials, prompting for consent if needed."""
    scopes = scopes or ALL_SCOPES
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), scopes)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_config(_get_client_config(), scopes)
        # Patch in our branded HTML redirect handler
        flow._OOB_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"  # keep default
        wsgi_app = _BrandedRedirectApp(_SUCCESS_HTML)
        import google_auth_oauthlib.flow as _flow_mod
        _orig = _flow_mod._RedirectWSGIApp
        _flow_mod._RedirectWSGIApp = _BrandedRedirectApp
        try:
            creds = flow.run_local_server(port=0, success_message=_SUCCESS_HTML)
        finally:
            _flow_mod._RedirectWSGIApp = _orig

    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())
    return creds


def get_service(api: str, version: str, scopes: list[str] | None = None):
    """Build a Google API service client."""
    creds = get_credentials(scopes)
    return build(api, version, credentials=creds)
