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
    Stores user profile information and metadata.
    """
    __tablename__ = "users"

    # Primary key
    user_id = Column(
        UNIQUEIDENTIFIER(binary=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False
    )
    
    # User identity from Azure Entra ID (Object ID)
    entra_id = Column(String(255), unique=True, nullable=False, index=True)
    
    # User email
    email = Column(String(255), unique=True, nullable=False, index=True)
    
    # User display name
    display_name = Column(String(255), nullable=True)
    
    # Whether the user has confirmed their email
    email_verified = Column(Boolean, default=True)  # Azure Entra ID handles verification
    
    # Account status
    is_active = Column(Boolean, default=True, index=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    
    def __repr__(self):
        return f"<User(user_id={self.user_id}, email={self.email}, entra_id={self.entra_id})>"


class AnalysisLog(Base):
    """
    Log of analyses performed by users for auditing and usage tracking.
    """
    __tablename__ = "analysis_logs"

    # Primary key
    log_id = Column(
        UNIQUEIDENTIFIER(binary=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False
    )
    
    # Reference to user
    user_id = Column(
        UNIQUEIDENTIFIER(binary=False),
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
