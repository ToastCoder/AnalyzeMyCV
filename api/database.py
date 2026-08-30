# AnalyzeMyCV
# api/database.py
# Azure SQL Database Configuration and Session Management

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

# Database Configuration
# Using Azure SQL Database with connection pooling disabled for serverless scenarios
SQLALCHEMY_DATABASE_URL = os.getenv(
    "AZURE_SQL_DATABASE_URL",
    ""
).strip()

if not SQLALCHEMY_DATABASE_URL:
    raise ValueError(
        "AZURE_SQL_DATABASE_URL environment variable not set. "
        "Format: mssql+pyodbc://username:password@server.database.windows.net/database?driver=ODBC+Driver+17+for+SQL+Server"
    )

# Create engine with connection pooling disabled for serverless/containerized apps
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    poolclass=NullPool,
    echo=False,  # Set to True for SQL query debugging
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for all ORM models
Base = declarative_base()


def get_db():
    """Dependency injection for database sessions in FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize all database tables."""
    Base.metadata.create_all(bind=engine)
