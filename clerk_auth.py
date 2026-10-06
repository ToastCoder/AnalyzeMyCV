# AnalyzeMyCV
# clerk_auth.py
"""Clerk sign-in for the public reverse proxy (proxy.py).

Streamlit can't host Clerk's JavaScript sign-in, so the proxy does it: anonymous
visitors are sent to /auth/sign-in (a small page running clerk-js), which leaves
Clerk's short-lived `__session` JWT in a cookie. The proxy verifies that JWT
against Clerk's JWKS, then swaps it for its own longer-lived `amc_session`
cookie so Streamlit's websocket and reruns don't depend on a 60-second token.
The verified user reaches Streamlit as X-Auth-* headers (see client/streamlit_client.py).
"""

import asyncio
import base64
import os
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import jwt
from aiohttp import ClientSession, ClientTimeout
from dotenv import load_dotenv

load_dotenv()

PUBLISHABLE_KEY = os.getenv("CLERK_PUBLISHABLE_KEY", "").strip()
# Optional: lets the proxy look up the user's email and name (session tokens carry only the id).
SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "").strip()
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
# Optional comma-separated origins allowed in the session token's `azp` claim.
AUTHORIZED_PARTIES = {
    origin.strip().rstrip("/") for origin in os.getenv("CLERK_AUTHORIZED_PARTIES", "").split(",") if origin.strip()
}

MIN_SECRET_LENGTH = 32
CLERK_SESSION_COOKIE = "__session"
SESSION_COOKIE = "amc_session"
SESSION_TTL_SECONDS = 900  # also how long a Clerk-side ban/sign-out can take to apply
SESSION_ISSUER = "analyzemycv-proxy"
SESSION_AUDIENCE = "analyzemycv-proxy"
CLERK_API_URL = "https://api.clerk.com/v1"


def _frontend_host(publishable_key: str) -> str:
    """The publishable key is `pk_<env>_<base64(frontend host + '$')>`."""
    try:
        encoded = publishable_key.split("_", 2)[2]
        host = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode().rstrip("$")
    except (IndexError, ValueError):
        return ""
    return host if re.fullmatch(r"[a-z0-9.-]+", host) else ""


FRONTEND_HOST = _frontend_host(PUBLISHABLE_KEY)
ISSUER = f"https://{FRONTEND_HOST}"
# A key being set means Clerk is meant to be on; if the rest of the config is bad the
# proxy must refuse requests (proxy.py), never fall back to open access.
CONFIGURED = bool(PUBLISHABLE_KEY)
ENABLED = bool(FRONTEND_HOST) and len(JWT_SECRET) >= MIN_SECRET_LENGTH

_jwks_client = jwt.PyJWKClient(f"{ISSUER}/.well-known/jwks.json") if FRONTEND_HOST else None


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    email: Optional[str] = None
    name: Optional[str] = None


def _verify_clerk_token(token: str) -> Optional[dict]:
    """Blocking (may fetch the JWKS); call through a thread."""
    try:
        key = _jwks_client.get_signing_key_from_jwt(token).key
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=ISSUER,
            leeway=5,
            options={"require": ["exp", "iat", "sub", "iss"], "verify_aud": False},
        )
    except jwt.PyJWTError:
        return None
    if AUTHORIZED_PARTIES and payload.get("azp") not in AUTHORIZED_PARTIES:
        return None
    return payload


async def _fetch_profile(session: ClientSession, user_id: str) -> dict:
    """Best-effort email/name lookup through Clerk's Backend API."""
    if not SECRET_KEY:
        return {}
    try:
        async with session.get(
            f"{CLERK_API_URL}/users/{quote(user_id, safe='')}",
            headers={"Authorization": f"Bearer {SECRET_KEY}"},
            timeout=ClientTimeout(total=5),
        ) as resp:
            if resp.status != 200:
                return {}
            data = await resp.json()
    except Exception:
        return {}
    primary = data.get("primary_email_address_id")
    email = next((e.get("email_address") for e in data.get("email_addresses") or [] if e.get("id") == primary), None)
    name = " ".join(filter(None, (data.get("first_name"), data.get("last_name")))) or data.get("username")
    return {"email": email, "name": name}


def issue_session_cookie(user: AuthUser) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": user.user_id,
            "email": user.email,
            "name": user.name,
            "iss": SESSION_ISSUER,
            "aud": SESSION_AUDIENCE,
            "iat": now,
            "exp": now + SESSION_TTL_SECONDS,
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def _read_session_cookie(token: str) -> Optional[AuthUser]:
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
            audience=SESSION_AUDIENCE,
            issuer=SESSION_ISSUER,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.PyJWTError:
        return None
    return AuthUser(payload["sub"], payload.get("email"), payload.get("name"))


async def authenticate(cookies, http: ClientSession):
    """Return (user, new_session_cookie_value). user is None when not signed in;
    the cookie value is set only when a Clerk token was just exchanged."""
    if not ENABLED:
        return None, None
    own = cookies.get(SESSION_COOKIE)
    if own:
        user = _read_session_cookie(own)
        if user:
            return user, None
    clerk_token = cookies.get(CLERK_SESSION_COOKIE)
    if not clerk_token:
        return None, None
    payload = await asyncio.get_running_loop().run_in_executor(None, _verify_clerk_token, clerk_token)
    if not payload or not isinstance(payload["sub"], str):
        return None, None
    profile = await _fetch_profile(http, payload["sub"])
    user = AuthUser(
        payload["sub"],
        profile.get("email") or payload.get("email"),
        profile.get("name") or payload.get("name"),
    )
    return user, issue_session_cookie(user)


def identity_headers(user: AuthUser) -> dict:
    """Headers handed to Streamlit; values are percent-encoded so any name survives HTTP."""
    headers = {"X-Auth-User-Id": quote(user.user_id, safe="")}
    if user.email:
        headers["X-Auth-Email"] = quote(user.email, safe="")
    if user.name:
        headers["X-Auth-Name"] = quote(user.name, safe="")
    return headers
