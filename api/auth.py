# AnalyzeMyCV
# api/auth.py
"""Identity for API requests.

End users sign in with Clerk, verified by the reverse proxy (proxy.py) in front of
the Streamlit frontend. This API is bound to localhost and is only called by that
frontend, which forwards the signed-in user as a short-lived HS256 token signed
with JWT_SECRET (see client/streamlit_client.py).
No credentials or user records are stored by this application.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Local development: values come from .env.local, then .env (App Service sets real environment variables).
_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env.local")
load_dotenv(_ROOT / ".env")

logger = logging.getLogger(__name__)

JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
ALGORITHM = "HS256"
# Must match the values the frontend signs with.
TOKEN_ISSUER = "analyzemycv-frontend"
TOKEN_AUDIENCE = "analyzemycv-api"
MIN_SECRET_LENGTH = 32

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    email: Optional[str]
    display_name: Optional[str]


def decode_internal_token(token: str) -> dict:
    """Verify a frontend-issued token. Raises jwt.PyJWTError on any failure."""
    if len(JWT_SECRET) < MIN_SECRET_LENGTH:
        raise jwt.InvalidKeyError("JWT_SECRET is missing or too short")
    return jwt.decode(
        token,
        JWT_SECRET,
        algorithms=[ALGORITHM],
        audience=TOKEN_AUDIENCE,
        issuer=TOKEN_ISSUER,
        options={"require": ["exp", "iat", "sub", "iss", "aud"]},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
) -> CurrentUser:
    if len(JWT_SECRET) < MIN_SECRET_LENGTH:
        logger.error("JWT_SECRET is missing or shorter than %d characters", MIN_SECRET_LENGTH)
        raise HTTPException(status_code=503, detail="Auth service unavailable.")
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        payload = decode_internal_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return CurrentUser(
        user_id=user_id,
        email=payload.get("email"),
        display_name=payload.get("name"),
    )
