"""OAuth authentication routes — Google + GitHub.

Endpoints:
  GET  /auth/google   → Redirect to Google OAuth
  GET  /auth/github   → Redirect to GitHub OAuth
  GET  /auth/callback → OAuth callback handler → JWT
  GET  /auth/me       → Current user info

Reference: SYSTEM_DESIGN.md §6.13.1
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

JWT_SECRET = os.environ.get("JWT_SECRET", "daemon-dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72

# OAuth provider configs (loaded from env)
_google_config = None
_github_config = None


def configure(
    google_client_id: str = "",
    google_client_secret: str = "",
    github_client_id: str = "",
    github_client_secret: str = "",
    redirect_base_url: str = "http://localhost:8000",
) -> None:
    """Set OAuth provider configs from env vars."""
    global _google_config, _github_config

    if google_client_id and google_client_secret:
        _google_config = {
            "client_id": google_client_id,
            "client_secret": google_client_secret,
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
            "scopes": "openid email profile",
            "redirect_uri": f"{redirect_base_url}/auth/callback?provider=google",
        }
        logger.info("Google OAuth configured")

    if github_client_id and github_client_secret:
        _github_config = {
            "client_id": github_client_id,
            "client_secret": github_client_secret,
            "authorize_url": "https://github.com/login/oauth/authorize",
            "token_url": "https://github.com/login/oauth/access_token",
            "userinfo_url": "https://api.github.com/user",
            "scopes": "read:user user:email",
            "redirect_uri": f"{redirect_base_url}/auth/callback?provider=github",
        }
        logger.info("GitHub OAuth configured")


def create_jwt(user_info: dict) -> str:
    """Create a JWT token for an authenticated user."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_info.get("id") or user_info.get("email") or "unknown",
        "email": user_info.get("email", ""),
        "name": user_info.get("name", ""),
        "provider": user_info.get("provider", ""),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_EXPIRY_HOURS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> dict:
    """Verify a JWT token and return the payload."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


async def get_current_user(request: Request) -> dict:
    """FastAPI dependency: extract and verify JWT from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    return verify_jwt(auth[7:])


# ── Routes ──────────────────────────────────────────────────────────────


@router.get("/google")
async def auth_google():
    """Redirect to Google OAuth consent screen."""
    if not _google_config:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")

    import urllib.parse
    params = {
        "client_id": _google_config["client_id"],
        "redirect_uri": _google_config["redirect_uri"],
        "response_type": "code",
        "scope": _google_config["scopes"],
        "access_type": "offline",
        "prompt": "select_account",
    }
    url = f"{_google_config['authorize_url']}?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url)


@router.get("/github")
async def auth_github():
    """Redirect to GitHub OAuth consent screen."""
    if not _github_config:
        raise HTTPException(status_code=501, detail="GitHub OAuth not configured")

    import urllib.parse
    params = {
        "client_id": _github_config["client_id"],
        "redirect_uri": _github_config["redirect_uri"],
        "scope": _github_config["scopes"],
    }
    url = f"{_github_config['authorize_url']}?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url)


@router.get("/callback")
async def auth_callback(provider: str = "", code: str = "", state: str = ""):
    """Handle OAuth callback — exchange code for token, issue JWT."""
    import httpx

    if provider == "google" and _google_config:
        config = _google_config
    elif provider == "github" and _github_config:
        config = _github_config
    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    # Exchange code for access token
    async with httpx.AsyncClient() as client:
        token_data = {
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "code": code,
            "redirect_uri": config["redirect_uri"],
            "grant_type": "authorization_code",
        }
        headers = {"Accept": "application/json"}
        resp = await client.post(config["token_url"], data=token_data, headers=headers)

        if resp.status_code != 200:
            logger.warning("OAuth token exchange failed: %s %s", resp.status_code, resp.text[:200])
            raise HTTPException(status_code=502, detail="Token exchange failed")

        token_resp = resp.json()
        access_token = token_resp.get("access_token")
        if not access_token:
            raise HTTPException(status_code=502, detail="No access token in response")

        # Get user info
        auth_header = {"Authorization": f"Bearer {access_token}"}
        if provider == "github":
            auth_header["Authorization"] = f"token {access_token}"

        user_resp = await client.get(config["userinfo_url"], headers=auth_header)
        if user_resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to get user info")

        user_data = user_resp.json()

    # Normalize user info
    if provider == "google":
        user_info = {
            "id": user_data.get("sub", ""),
            "email": user_data.get("email", ""),
            "name": user_data.get("name", ""),
            "provider": "google",
        }
    else:  # github
        user_info = {
            "id": str(user_data.get("id", "")),
            "email": user_data.get("email", ""),
            "name": user_data.get("name") or user_data.get("login", ""),
            "provider": "github",
        }

    token = create_jwt(user_info)

    return {
        "ok": True,
        "token": token,
        "user": user_info,
        "expires_in": JWT_EXPIRY_HOURS * 3600,
    }


@router.get("/me")
async def auth_me(user: dict = Depends(get_current_user)):
    """Get current authenticated user info."""
    return {
        "ok": True,
        "user": {
            "id": user.get("sub"),
            "email": user.get("email"),
            "name": user.get("name"),
            "provider": user.get("provider"),
        },
    }
