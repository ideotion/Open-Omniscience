"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""
"""
Database Migration: Add Enhanced Metadata Fields

This migration adds enhanced metadata fields to the Source and Article tables:
- Source: reliability_score, language, region, country, source_type, update_frequency, cacheability
- Article: region, country, author

Run this migration after updating the models.py file.

Usage:
    python3 src/database/migrations/002_add_enhanced_metadata.py
"""

from pathlib import Path

from src.database.models import Base, engine
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
