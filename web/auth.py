"""Discord OAuth2 login.

Only the `identify` scope is requested, and the Discord access token is
discarded once the profile has been read. What persists is a signed cookie
holding the user id, name and avatar hash, so nothing sensitive is stored
server side and there is no session table to leak.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = f"{DISCORD_API}/oauth2/token"

SESSION_COOKIE = "riko_session"
STATE_COOKIE = "riko_oauth_state"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
STATE_MAX_AGE = 60 * 10


def _secret() -> bytes:
    """Key used to sign cookies.

    Falls back to a per-process random key so a missing SESSION_SECRET logs
    people out on restart rather than signing with a guessable constant.
    """
    configured = os.getenv("SESSION_SECRET")
    if configured:
        return configured.encode("utf-8")
    if not hasattr(_secret, "_ephemeral"):
        logger.warning(
            "SESSION_SECRET is not set, using an ephemeral key. "
            "Logins will not survive a restart."
        )
        _secret._ephemeral = secrets.token_bytes(32)
    return _secret._ephemeral


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def sign(payload: Dict[str, Any]) -> str:
    """Serialise and HMAC-sign a cookie payload."""
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    mac = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64e(mac)}"


def unsign(token: Optional[str], max_age: int) -> Optional[Dict[str, Any]]:
    """Verify a signed cookie and return its payload, or None."""
    if not token or "." not in token:
        return None
    body, _, mac = token.partition(".")
    expected = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(_b64d(mac), expected):
            return None
        payload = json.loads(_b64d(body))
    except Exception:
        return None
    issued = payload.get("iat", 0)
    if not isinstance(issued, (int, float)) or time.time() - issued > max_age:
        return None
    return payload


def build_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify",
        "state": state,
        "prompt": "none",
    })


async def exchange_code(
    client_id: str, client_secret: str, code: str, redirect_uri: str
) -> Optional[str]:
    """Swap an authorization code for an access token."""
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        "Discord token exchange failed with %s: %s",
                        resp.status, (await resp.text())[:200],
                    )
                    return None
                return (await resp.json()).get("access_token")
    except Exception as e:
        logger.error(f"Discord token exchange error: {e}")
        return None


async def fetch_user(access_token: str) -> Optional[Dict[str, Any]]:
    """Read the authenticated user's public profile."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{DISCORD_API}/users/@me",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning("Discord /users/@me returned %s", resp.status)
                    return None
                return await resp.json()
    except Exception as e:
        logger.error(f"Discord user fetch error: {e}")
        return None


def avatar_url(user_id: str, avatar_hash: Optional[str]) -> str:
    if avatar_hash:
        ext = "gif" if str(avatar_hash).startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=128"
    # Default avatars are keyed off the account id for the new username system.
    index = (int(user_id) >> 22) % 6 if str(user_id).isdigit() else 0
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"
