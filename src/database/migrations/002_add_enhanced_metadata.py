"""
Database Migration: Add Enhanced Metadata Fields

This migration adds enhanced metadata fields to the Source and Article tables:
- Source: reliability_score, language, region, country, source_type, update_frequency, cacheability
- Article: region, country, author

Run this migration after updating the models.py file.

Usage:
    python3 src/database/migrations/002_add_enhanced_metadata.py
"""

import sys
from pathlib import Path

# Add parent directory to path
repo_root = Path(__file__).parent.parent.parent
sys.path.append(str(repo_root))

from database.models import Base, engine
from sqlalchemy import inspect

def migration_needed():
    """Check if migration is needed."""
    inspector = inspect(engine)
    
    # Check Source table
    source_columns = [col['name'] for col in inspector.get_columns('sources')]
    required_source_columns = ['reliability_score', 'language', 'region', 'country', 
                                'source_type', 'update_frequency', 'cacheability']
    
    for col in required_source_columns:
        if col not in source_columns:
            return True
    
    # Check Article table
    article_columns = [col['name'] for col in inspector.get_columns('articles')]
    required_article_columns = ['region', 'country', 'author']
    
    for col in required_article_columns:
        if col not in article_columns:
            return True
    
    return False

def run_migration():
    """Run the migration."""
    print("Checking if migration is needed...")
    
    if not migration_needed():
        print("✓ Migration not needed - all columns already exist.")
        return
    
    print("✓ Migration needed - adding new columns...")
    
    # Create all tables (this will add new columns to existing tables)
    Base.metadata.create_all(engine)
    
    print("✓ Migration completed successfully!")
    print("\nNew columns added:")
    print("  Source: reliability_score, language, region, country, source_type, update_frequency, cacheability")
    print("  Article: region, country, author")

if __name__ == "__main__":
    run_migration()
