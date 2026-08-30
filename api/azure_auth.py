# AnalyzeMyCV
# api/azure_auth.py
# Azure Entra ID Authentication using MSAL (Microsoft Authentication Library)

import logging
import os
import json
from typing import Optional
from datetime import datetime, timedelta

import jwt
import requests
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from api.database import get_db
from api.user_models import User

logger = logging.getLogger(__name__)

# Azure Entra ID Configuration
TENANT_ID = os.getenv("AZURE_TENANT_ID", "").strip()
CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("AZURE_AUTH_REDIRECT_URI", "").strip()

# Azure Entra ID Token Endpoint
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
TOKEN_ENDPOINT = f"{AUTHORITY}/oauth2/v2.0/token"
JWKS_URI = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"

logger.info(f"Azure Entra ID Auth: TENANT_ID set = {bool(TENANT_ID)}")
logger.info(f"Azure Entra ID Auth: CLIENT_ID set = {bool(CLIENT_ID)}")
logger.info(f"Azure Entra ID Auth: CLIENT_SECRET set = {bool(CLIENT_SECRET)}")


class AuthRequest(BaseModel):
    """Request model for authentication endpoints."""
    code: Optional[str] = None  # Authorization code from Azure Entra ID
    refresh_token: Optional[str] = None  # For token refresh
    access_token: Optional[str] = None  # For confirmation


class AuthResponse(BaseModel):
    """Response model for authentication endpoints."""
    success: bool
    user_email: Optional[str] = None
    user_id: Optional[str] = None
    display_name: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    message: Optional[str] = None


class TokenVerifier:
    """Verify and decode Azure Entra ID tokens."""
    
    def __init__(self):
        self.jwks = None
        self.jwks_fetched_at = None
    
    def _fetch_jwks(self):
        """Fetch JWKS from Azure Entra ID."""
        if self.jwks and self.jwks_fetched_at and \
           datetime.utcnow() - self.jwks_fetched_at < timedelta(hours=24):
            return
        
        try:
            resp = requests.get(JWKS_URI, timeout=10)
            resp.raise_for_status()
            self.jwks = resp.json()
            self.jwks_fetched_at = datetime.utcnow()
            logger.info("JWKS updated from Azure Entra ID")
        except Exception as e:
            logger.error(f"Failed to fetch JWKS: {e}")
            raise
    
    def verify_token(self, token: str) -> dict:
        """
        Verify and decode Azure Entra ID access token.
        Returns decoded token payload.
        """
        try:
            self._fetch_jwks()
            
            # Decode without verification first to get kid
            unverified = jwt.decode(token, options={"verify_signature": False})
            kid = jwt.get_unverified_header(token).get("kid")
            
            # Find the key
            if not self.jwks or "keys" not in self.jwks:
                raise ValueError("No JWKS available")
            
            key = None
            for k in self.jwks["keys"]:
                if k.get("kid") == kid:
                    key = k
                    break
            
            if not key:
                raise ValueError(f"Key with kid {kid} not found")
            
            # Convert JWKS key to PEM
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.backends import default_backend
            
            # Build RSA key from JWKS
            numbers = rsa.RSAPublicNumbers(
                e=int.from_bytes(__import__('base64').urlsafe_b64decode(key['e'] + '==='), 'big'),
                n=int.from_bytes(__import__('base64').urlsafe_b64decode(key['n'] + '==='), 'big'),
            )
            public_key = numbers.public_key(default_backend())
            
            # Verify token
            decoded = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=CLIENT_ID,
                issuer=f"{AUTHORITY}/v2.0"
            )
            
            return decoded
        
        except Exception as e:
            logger.error(f"Token verification failed: {e}")
            raise HTTPException(status_code=401, detail="Invalid token")


token_verifier = TokenVerifier()

router = APIRouter(prefix="/auth", tags=["auth"])


def exchange_code_for_token(code: str) -> dict:
    """Exchange authorization code for access token."""
    try:
        data = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
            "scope": "openid profile email offline_access"
        }
        
        resp = requests.post(TOKEN_ENDPOINT, data=data, timeout=15)
        resp.raise_for_status()
        return resp.json()
    
    except Exception as e:
        logger.error(f"Token exchange failed: {e}")
        raise HTTPException(status_code=400, detail=f"Authentication failed: {str(e)}")


def get_or_create_user(
    entra_id: str,
    email: str,
    display_name: str,
    db: Session
) -> User:
    """Get existing user or create new one."""
    user = db.query(User).filter(User.entra_id == entra_id).first()
    
    if not user:
        user = User(
            entra_id=entra_id,
            email=email,
            display_name=display_name,
            email_verified=True,
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"New user created: {email}")
    else:
        # Update last login and display name
        user.last_login = datetime.utcnow()
        user.display_name = display_name
        db.commit()
        db.refresh(user)
    
    return user


@router.post("/login", response_model=AuthResponse)
async def login(body: AuthRequest, db: Session = Depends(get_db)):
    """
    Handle Azure Entra ID login.
    Frontend should redirect to: 
    {AUTHORITY}/oauth2/v2.0/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=openid+profile+email+offline_access
    """
    if not TENANT_ID or not CLIENT_ID or not CLIENT_SECRET:
        logger.error("Auth login failed: Azure Entra ID not configured")
        raise HTTPException(status_code=503, detail="Auth service unavailable.")
    
    if not body.code:
        raise HTTPException(status_code=400, detail="Authorization code required.")
    
    try:
        logger.info("Auth login attempt with authorization code")
        
        # Exchange code for tokens
        token_response = exchange_code_for_token(body.code)
        access_token = token_response.get("access_token")
        refresh_token = token_response.get("refresh_token")
        
        if not access_token:
            raise ValueError("No access token in response")
        
        # Verify and decode token
        decoded = token_verifier.verify_token(access_token)
        
        entra_id = decoded.get("oid")  # Object ID from Azure Entra ID
        email = decoded.get("email") or decoded.get("preferred_username")
        display_name = decoded.get("name", email)
        
        if not entra_id or not email:
            raise ValueError("Missing required claims in token")
        
        # Get or create user
        user = get_or_create_user(entra_id, email, display_name, db)
        
        logger.info(f"Auth login success for: {email}")
        return AuthResponse(
            success=True,
            user_id=str(user.user_id),
            user_email=user.email,
            display_name=user.display_name,
            access_token=access_token,
            refresh_token=refresh_token
        )
    
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Auth login error: {error_msg}")
        raise HTTPException(status_code=401, detail="Authentication failed")


@router.post("/refresh", response_model=AuthResponse)
async def refresh(body: AuthRequest, db: Session = Depends(get_db)):
    """Refresh access token using refresh token."""
    if not TENANT_ID or not CLIENT_ID or not CLIENT_SECRET:
        logger.error("Auth refresh failed: Azure Entra ID not configured")
        raise HTTPException(status_code=503, detail="Auth service unavailable.")
    
    if not body.refresh_token:
        raise HTTPException(status_code=400, detail="Refresh token required.")
    
    try:
        logger.info("Auth token refresh attempt")
        
        data = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": body.refresh_token,
            "grant_type": "refresh_token",
            "scope": "openid profile email offline_access"
        }
        
        resp = requests.post(TOKEN_ENDPOINT, data=data, timeout=15)
        resp.raise_for_status()
        token_response = resp.json()
        
        access_token = token_response.get("access_token")
        new_refresh_token = token_response.get("refresh_token", body.refresh_token)
        
        if not access_token:
            raise ValueError("No access token in response")
        
        # Verify token
        decoded = token_verifier.verify_token(access_token)
        entra_id = decoded.get("oid")
        email = decoded.get("email") or decoded.get("preferred_username")
        
        if not entra_id:
            raise ValueError("Missing oid in token")
        
        # Update user last login
        user = db.query(User).filter(User.entra_id == entra_id).first()
        if user:
            user.last_login = datetime.utcnow()
            db.commit()
        
        logger.info(f"Auth token refresh success for: {email}")
        return AuthResponse(
            success=True,
            user_email=email,
            access_token=access_token,
            refresh_token=new_refresh_token
        )
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Auth refresh error: {error_msg}")
        raise HTTPException(status_code=401, detail="Token refresh failed")


@router.post("/verify", response_model=AuthResponse)
async def verify(body: AuthRequest, db: Session = Depends(get_db)):
    """Verify and validate an access token."""
    if not body.access_token:
        raise HTTPException(status_code=400, detail="Access token required.")
    
    try:
        decoded = token_verifier.verify_token(body.access_token)
        entra_id = decoded.get("oid")
        email = decoded.get("email") or decoded.get("preferred_username")
        display_name = decoded.get("name", email)
        
        # Get or create user
        user = get_or_create_user(entra_id, email, display_name, db)
        
        logger.info(f"Auth token verified for: {email}")
        return AuthResponse(
            success=True,
            user_id=str(user.user_id),
            user_email=user.email,
            display_name=user.display_name,
            access_token=body.access_token
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth verify error: {e}")
        raise HTTPException(status_code=401, detail="Token verification failed")


@router.post("/logout", response_model=AuthResponse)
async def logout():
    """Logout endpoint (mainly for client-side cleanup)."""
    return AuthResponse(
        success=True,
        message="Logged out successfully"
    )
