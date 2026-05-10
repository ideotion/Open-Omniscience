"""
Database Session Management for SQLite
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path

# Get database URL from environment or use default
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/database.sqlite")

# Ensure data directory exists
Path("./data").mkdir(parents=True, exist_ok=True)

# Create SQLite engine
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # Required for SQLite
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False  # Set to True for debugging SQL queries
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for declarative models
Base = declarative_base()


def get_db():
    """
    Dependency that provides a database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Initialize database tables
def init_db():
    """
    Create all database tables
    """
    Base.metadata.create_all(bind=engine)


# Close database connection
async def close_db():
    """
    Close database connection (for FastAPI shutdown)
    """
    engine.dispose()
