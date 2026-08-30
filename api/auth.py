"""Email/password authentication backed by the application's SQL database."""

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.database import get_db
from api.user_models import User

logger = logging.getLogger(__name__)
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24
MIN_PASSWORD_LENGTH = 8
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)
auth_limiter = Limiter(key_func=get_remote_address)


class AuthRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class ConfirmRequest(BaseModel):
    access_token: str


class AuthResponse(BaseModel):
    success: bool
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    display_name: Optional[str] = None
    access_token: Optional[str] = None
    message: Optional[str] = None


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.fullmatch(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    return email


def require_jwt_secret() -> None:
    if len(JWT_SECRET) < 32:
        logger.error("JWT_SECRET is missing or shorter than 32 characters")
        raise HTTPException(status_code=503, detail="Auth service unavailable.")


def hash_password(password: str) -> str:
    """Hash a password; plaintext is never stored."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user: User) -> str:
    return jwt.encode(
        {"sub": str(user.user_id), "email": user.email,
         "exp": datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)},
        JWT_SECRET, algorithm=ALGORITHM,
    )


def decode_access_token(access_token: str) -> dict:
    require_jwt_secret()
    return jwt.decode(access_token, JWT_SECRET, algorithms=[ALGORITHM])


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        payload = decode_access_token(credentials.credentials)
        user = db.query(User).filter(User.user_id == payload.get("sub")).first()
    except (jwt.PyJWTError, HTTPException):
        user = None
    if not user or not user.is_active or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return user


def auth_response(user: User, message: Optional[str] = None) -> AuthResponse:
    return AuthResponse(success=True, user_id=str(user.user_id), user_email=user.email,
                        display_name=user.display_name, access_token=create_access_token(user),
                        message=message)


@router.post("/signup", response_model=AuthResponse)
@auth_limiter.limit("5/minute")
async def signup(request: Request, body: AuthRequest, db: Session = Depends(get_db)):
    require_jwt_secret()
    email = normalize_email(body.email)
    if len(body.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if get_user_by_email(db, email):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    logger.info("New account created for %s", email)
    return auth_response(user, "Account created.")


@router.post("/login", response_model=AuthResponse)
@auth_limiter.limit("10/minute")
async def login(request: Request, body: AuthRequest, db: Session = Depends(get_db)):
    require_jwt_secret()
    email = normalize_email(body.email)
    user = get_user_by_email(db, email)
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been disabled.")
    user.last_login = datetime.utcnow()
    db.commit()
    return auth_response(user)


@router.post("/verify", response_model=AuthResponse)
async def verify(body: ConfirmRequest, db: Session = Depends(get_db)):
    try:
        payload = decode_access_token(body.access_token)
        user = db.query(User).filter(User.user_id == payload.get("sub")).first()
    except (jwt.PyJWTError, HTTPException):
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return AuthResponse(success=True, user_id=str(user.user_id), user_email=user.email, display_name=user.display_name)


@router.post("/logout", response_model=AuthResponse)
async def logout():
    return AuthResponse(success=True, message="Logged out successfully.")
