# AnalyzeMyCV
# api/user_models.py
# SQLAlchemy ORM Models for User Management

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
import uuid
from api.database import Base


class User(Base):
    """
    User model for Azure SQL Database.
    Stores email/password accounts. Passwords are never stored in plaintext.
    """
    __tablename__ = "users"

    # Primary key
    # as_uuid=False: values are stored/round-tripped as plain strings, matching
    # the str(uuid.uuid4()) default and every str(user.user_id)/JWT "sub" use
    # site elsewhere. SQLAlchemy 2.0's UNIQUEIDENTIFIER defaults to as_uuid=True
    # (real uuid.UUID objects), which raises AttributeError on insert here since
    # MSSQL's dialect uses the same string-based bind path as SQLite does.
    user_id = Column(
        UNIQUEIDENTIFIER(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False
    )

    # User email (lowercase, unique)
    email = Column(String(255), unique=True, nullable=False, index=True)

    # Hashed password (bcrypt) — plaintext is never stored
    password_hash = Column(String(255), nullable=True)

    # Optional display name
    display_name = Column(String(255), nullable=True)

    # Account status
    is_active = Column(Boolean, default=True, index=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<User(user_id={self.user_id}, email={self.email})>"


class PasswordResetToken(Base):
    """One-time, short-lived password reset tokens.

    Only a SHA-256 hash is stored. The raw token is sent to the user and is
    never persisted in the database.
    """
    __tablename__ = "password_reset_tokens"

    token_id = Column(
        UNIQUEIDENTIFIER(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False,
    )
    user_id = Column(UNIQUEIDENTIFIER(as_uuid=False), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<PasswordResetToken(token_id={self.token_id}, user_id={self.user_id})>"
