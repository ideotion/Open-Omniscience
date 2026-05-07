"""
Database Initialization Script for Open Omniscience

This script initializes the SQLite database and populates it with
sources from the configs/sources.yml file.

Author: Ideotion
"""

import yaml
import logging
from pathlib import Path
from models import Base, engine, Session, Source

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("../../audit/init_db.log"),
        logging.StreamHandler()
    ]
)


def init_db():
    """
    Initialize the database by:
    1. Creating all tables if they don't exist.
    2. Populating the sources table from configs/sources.yml.
    """
    logging.info("Initializing database...")
    
    # Create all tables
    Base.metadata.create_all(engine)
    logging.info("Database tables created or verified.")
    
    # Load sources from YAML
    sources_yml_path = Path("../../configs/sources.yml")
    if not sources_yml_path.exists():
        logging.error(f"Sources file not found at {sources_yml_path}")
        return
    
    with open(sources_yml_path, "r") as f:
        sources_data = yaml.safe_load(f)
    
    if not sources_data or "sources" not in sources_data:
        logging.error("No sources found in sources.yml")
        return
    
    # Add sources to the database
    session = Session()
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
            logging.info(f"Updated existing source: {source_data['name']}")
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
            logging.info(f"Added new source: {source_data['name']}")
    
    session.commit()
    session.close()
    
    logging.info(f"Database initialization complete. Added {sources_added} sources, skipped {sources_skipped} existing sources.")


if __name__ == "__main__":
    init_db()