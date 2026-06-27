# AnalyzeMyCV
# api/auth.py

import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from supabase import Client, create_client

logger = logging.getLogger(__name__)

supabase: Optional[Client] = None

try:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if supabase_url and supabase_key:
        supabase = create_client(supabase_url, supabase_key)
        logger.info("Supabase client initialized.")
        print("Auth: Supabase client initialized successfully.")
    else:
        logger.warning("SUPABASE_URL or SUPABASE_KEY not set. Auth endpoints will return 503.")
        print("Auth: SUPABASE_URL or SUPABASE_KEY not set.")
except Exception as e:
    logger.error(f"Failed to initialize Supabase client: {e}")
    print(f"Auth: Failed to initialize Supabase client: {e}")
    supabase = None


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
    if supabase is None:
        print("Auth signup failed: Supabase not initialized")
        raise HTTPException(status_code=503, detail="Auth service unavailable.")
    try:
        print(f"Auth signup attempt for: {body.email}")
        result = supabase.auth.sign_up({"email": body.email, "password": body.password})
        user = result.user
        session = result.session
        print(f"Auth signup success for: {body.email}, session: {session is not None}")
        if session:
            return AuthResponse(
                success=True,
                user_email=user.email,
                access_token=session.access_token,
            )
        return AuthResponse(
            success=True,
            user_email=user.email if user else body.email,
            message="Confirmation email sent. Check your inbox.",
        )
    except Exception as e:
        error_msg = str(e)
        print(f"Auth signup error for {body.email}: {error_msg}")
        if "already registered" in error_msg.lower():
            raise HTTPException(status_code=409, detail="Email already registered.")
        raise HTTPException(status_code=400, detail=error_msg)


@router.post("/login", response_model=AuthResponse)
async def login(body: AuthRequest):
    if supabase is None:
        raise HTTPException(status_code=503, detail="Auth service unavailable.")
    try:
        result = supabase.auth.sign_in_with_password({"email": body.email, "password": body.password})
        user = result.user
        session = result.session
        return AuthResponse(
            success=True,
            user_email=user.email if user else body.email,
            access_token=session.access_token if session else None,
        )
    except Exception as e:
        error_msg = str(e)
        if "invalid" in error_msg.lower() or "credentials" in error_msg.lower():
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        raise HTTPException(status_code=400, detail=error_msg)
