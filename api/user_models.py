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
    user_id = Column(
        UNIQUEIDENTIFIER(),
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


class AnalysisLog(Base):
    """
    Log of analyses performed by users for auditing and usage tracking.
    """
    __tablename__ = "analysis_logs"

    # Primary key
    log_id = Column(
        UNIQUEIDENTIFIER(),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False
    )
    
    # Reference to user
    user_id = Column(
        UNIQUEIDENTIFIER(),
        nullable=False,
        index=True
    )
    
    # File name analyzed
    file_name = Column(String(255), nullable=True)
    
    # Whether job description was provided
    has_job_description = Column(Boolean, default=False)
    
    # Analysis result summary (can store JSON)
    result_summary = Column(String(2000), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    def __repr__(self):
        return f"<AnalysisLog(log_id={self.log_id}, user_id={self.user_id})>"


class PasswordResetToken(Base):
    """One-time, short-lived password reset tokens.

    Only a SHA-256 hash is stored. The raw token is sent to the user and is
    never persisted in the database.
    """
    __tablename__ = "password_reset_tokens"

    token_id = Column(
        UNIQUEIDENTIFIER(),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False,
    )
    user_id = Column(UNIQUEIDENTIFIER(), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<PasswordResetToken(token_id={self.token_id}, user_id={self.user_id})>"
