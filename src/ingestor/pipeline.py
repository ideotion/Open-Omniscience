"""
Ingestion Pipeline for Open Omniscience

This module orchestrates the end-to-end ingestion workflow:
1. Scrape articles from configured sources.
2. Canonicalize URLs and resolve redirects.
3. Generate content hashes for duplicate detection.
4. Store new articles in the SQLite database.

Author: Ideotion
"""

import logging
from pathlib import Path
from datetime import datetime

# Import local modules
from scraper.scraper import Scraper
from url_utils import canonicalize_url, resolve_redirects, generate_content_hash
from database.models import Article, Source, get_session

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("../../audit/pipeline.log"),
        logging.StreamHandler()
    ]
)


class IngestionPipeline:
    """
    Manages the ingestion of articles from sources into the database.
    """
    
    def __init__(self, config_path="../../configs/sources.yml"):
        """
        Initialize the pipeline with a scraper and database session.
        
        Args:
            config_path: Path to the sources YAML configuration file.
        """
        self.scraper = Scraper(config_path=config_path)
        self.session = get_session()
        logging.info("Ingestion pipeline initialized.")
    
    def ingest_source(self, source_data):
        """
        Ingest articles from a single source.
        
        Args:
            source_data: Dictionary containing source configuration.
            
        Returns:
            int: Number of articles ingested from this source.
        """
        # Check if source is enabled
        if not source_data.get("enabled", True):
            logging.info(f"Skipping disabled source: {source_data['name']}")
            return 0
        
        # Get or create the source in the database
        source = self.session.query(Source).filter_by(domain=source_data["domain"]).first()
        if not source:
            source = Source(
                name=source_data["name"],
                domain=source_data["domain"],
                rss_url=source_data.get("rss_url"),
                rate_limit_ms=source_data.get("rate_limit_ms", 2000),
                enabled=source_data.get("enabled", True)
            )
            self.session.add(source)
            self.session.commit()
            logging.info(f"Added new source to database: {source_data['name']}")
        
        # Scrape articles from the source
        try:
            articles = self.scraper.scrape_source(source_data)
            logging.info(f"Scraped {len(articles)} articles from {source_data['name']}")
        except Exception as e:
            logging.error(f"Error scraping {source_data['name']}: {e}")
            return 0
        
        # Process and ingest each article
        ingested_count = 0
        for article in articles:
            try:
                # Canonicalize URL and resolve redirects
                canonical_url = canonicalize_url(resolve_redirects(article["url"]))
                
                # Generate content hash
                content_hash = generate_content_hash(article["content"])
                
                # Check for duplicates
                existing_article = self.session.query(Article).filter_by(hash=content_hash).first()
                if existing_article:
                    logging.debug(f"Duplicate article detected (hash: {content_hash}), skipping.")
                    continue
                
                # Parse published_at if it's a string
                published_at = article["published_at"]
                if isinstance(published_at, str):
                    try:
                        published_at = datetime.fromisoformat(published_at)
                    except ValueError:
                        published_at = datetime.utcnow()
                
                # Create new article record
                new_article = Article(
                    url=article["url"],
                    canonical_url=canonical_url,
                    source_id=source.id,
                    title=article["title"],
                    content=article["content"],
                    published_at=published_at,
                    language=article.get("language", "en"),
                    hash=content_hash
                )
                self.session.add(new_article)
                ingested_count += 1
                
            except Exception as e:
                logging.error(f"Error processing article from {source_data['name']}: {e}")
                continue
        
        self.session.commit()
        logging.info(f"Ingested {ingested_count} articles from {source_data['name']}")
        return ingested_count
    
    def ingest_all_sources(self):
        """
        Ingest articles from all enabled sources in the configuration.
        
        Returns:
            int: Total number of articles ingested.
        """
        total_ingested = 0
        for source_data in self.scraper.sources:
            ingested = self.ingest_source(source_data)
            total_ingested += ingested
        
        logging.info(f"Total articles ingested: {total_ingested}")
        return total_ingested
    
    def close(self):
        """Close the database session."""
        self.session.close()
        logging.info("Database session closed.")


if __name__ == "__main__":
    pipeline = IngestionPipeline()
    try:
        total = pipeline.ingest_all_sources()
        print(f"Ingestion complete. Total articles ingested: {total}")
    except Exception as e:
        logging.error(f"Error in ingestion pipeline: {e}")
    finally:
        pipeline.close()