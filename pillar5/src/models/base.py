"""
Base Model for Pillar 5

Defines the SQLAlchemy Base and database connection for Pillar 5 models.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float, ForeignKey, Index, JSON
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import create_engine
from datetime import datetime
import os
from pathlib import Path

# Get the repository root
REPO_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
DATA_DIR = REPO_ROOT / "data"

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# Database URL: Default to SQLite, but can be overridden for PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'open_omniscience.db'}")

# Create the base class for all models
Base = declarative_base()

# Database engine
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency to get DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Utility function to initialize the database
def init_db():
    """Initialize the database by creating all tables."""
    Base.metadata.create_all(bind=engine)
    print("Pillar 5 database tables created successfully.")


# Utility function to drop all tables (for testing)
def drop_db():
    """Drop all Pillar 5 tables (use with caution!)."""
    Base.metadata.drop_all(bind=engine)
    print("Pillar 5 database tables dropped successfully.")
