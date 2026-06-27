# AnalyzeMyCV
# api/auth.py

import logging
import os
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")


def supabase_request(method: str, path: str, json_body: dict = None) -> dict:
    url = f"{SUPABASE_URL}{path}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.request(method, url, headers=headers, json=json_body, timeout=15)
    resp.raise_for_status()
    return resp.json()


class AuthRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    success: bool
    user_email: Optional[str] = None
    access_token: Optional[str] = None
    message: Optional[str] = None


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=AuthResponse)
async def signup(body: AuthRequest):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Auth signup failed: Supabase not configured")
        raise HTTPException(status_code=503, detail="Auth service unavailable.")
    try:
        print(f"Auth signup attempt for: {body.email}")
        data = supabase_request("POST", "/auth/v1/signup", {"email": body.email, "password": body.password})
        access_token = data.get("access_token")
        user_email = data.get("email") or body.email
        print(f"Auth signup success for: {body.email}")
        if access_token:
            return AuthResponse(success=True, user_email=user_email, access_token=access_token)
        return AuthResponse(success=True, user_email=user_email, message="Confirmation email sent. Check your inbox.")
    except requests.RequestException as e:
        error_msg = str(e)
        print(f"Auth signup error for {body.email}: {error_msg}")
        status = 400
        if "already registered" in error_msg.lower():
            status = 409
        raise HTTPException(status_code=status, detail=error_msg)


@router.post("/login", response_model=AuthResponse)
async def login(body: AuthRequest):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Auth login failed: Supabase not configured")
        raise HTTPException(status_code=503, detail="Auth service unavailable.")
    try:
        print(f"Auth login attempt for: {body.email}")
        data = supabase_request(
            "POST",
            "/auth/v1/token?grant_type=password",
            {"email": body.email, "password": body.password},
        )
        access_token = data.get("access_token")
        user = data.get("user", {})
        user_email = user.get("email") or body.email
        print(f"Auth login success for: {body.email}")
        return AuthResponse(success=True, user_email=user_email, access_token=access_token)
    except requests.RequestException as e:
        error_msg = str(e)
        print(f"Auth login error for {body.email}: {error_msg}")
        status = 400
        if "invalid" in error_msg.lower() or "credentials" in error_msg.lower():
            status = 401
        raise HTTPException(status_code=status, detail=error_msg)
