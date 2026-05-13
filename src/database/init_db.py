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
Database Initialization Script for Open Omniscience

This script initializes the SQLite database and populates it with
sources from the configs/sources.yml file.

Author: Ideotion
"""

import sys
import yaml
import logging
from pathlib import Path

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent))

# Import database models
from models import Base, engine, Session, Source

# Configure logging using shared config
from utils.logging_config import setup_logging
logger = setup_logging("init_db")


def init_db():
    """
    Initialize the database by:
    1. Creating all tables if they don't exist.
    2. Populating the sources table from configs/sources.yml.
    """
    logger.info("Initializing database...")
    
    # Create all tables
    Base.metadata.create_all(engine)
    logger.info("Database tables created or verified.")
    
    # Load sources from YAML
    sources_yml_path = Path(__file__).parent.parent.parent / "configs" / "sources.yml"
    if not sources_yml_path.exists():
        logger.error(f"Sources file not found at {sources_yml_path}")
        return
    
    with open(sources_yml_path, "r") as f:
        sources_data = yaml.safe_load(f)
    
    if not sources_data or "sources" not in sources_data:
        logger.error("No sources found in sources.yml")
        return
    
    # Add sources to the database
    session = Session()
    try:
        sources_added = 0
        sources_skipped = 0
        
        for source_data in sources_data["sources"]:
            # Check if source already exists
            existing_source = session.query(Source).filter_by(
                domain=source_data["domain"]
            ).first()
            
            if existing_source:
                # Update existing source if needed
                existing_source.name = source_data["name"]
                existing_source.rss_url = source_data.get("rss_url", existing_source.rss_url)
                existing_source.rate_limit_ms = source_data.get("rate_limit_ms", existing_source.rate_limit_ms)
                existing_source.enabled = source_data.get("enabled", existing_source.enabled)
                sources_skipped += 1
                logger.info(f"Updated existing source: {source_data['name']}")
            else:
                # Add new source
                new_source = Source(
                    name=source_data["name"],
                    domain=source_data["domain"],
                    rss_url=source_data.get("rss_url"),
                    rate_limit_ms=source_data.get("rate_limit_ms", 2000),
                    enabled=source_data.get("enabled", True)
                )
                session.add(new_source)
                sources_added += 1
                logger.info(f"Added new source: {source_data['name']}")
        
        session.commit()
        logger.info(f"Database initialization complete. Added {sources_added} sources, skipped {sources_skipped} existing sources.")
    except Exception as e:
        session.rollback()
        logger.error(f"Error initializing database: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    init_db()