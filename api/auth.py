# AnalyzeMyCV
# api/auth.py
# 
# This file is deprecated. All authentication is now handled in api/azure_auth.py
# Please import from there instead.
#
# Migration: Supabase → Azure Entra ID
# Date: 2026-08-30

# For backwards compatibility, re-export from azure_auth
from api.azure_auth import (
    router,
    AuthRequest,
    AuthResponse,
    token_verifier,
)

__all__ = ["router", "AuthRequest", "AuthResponse", "token_verifier"]
