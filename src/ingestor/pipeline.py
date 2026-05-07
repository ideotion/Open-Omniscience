"""
Ingestion Pipeline for Open Omniscience

This module orchestrates the end-to-end ingestion workflow:
1. Scrape articles from configured sources.
2. Canonicalize URLs and resolve redirects.
3. Generate content hashes for duplicate detection.
4. Store new articles in the SQLite database.
5. Handle errors with retries and exponential backoff.

Author: Ideotion
"""

import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

# Import local modules
from scraper.scraper import Scraper
from url_utils import canonicalize_url, resolve_redirects, generate_content_hash
from database.models import Article, Source, get_session

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("../../audit/pipeline.log"),
        logging.StreamHandler()
    ]
)

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds (will use exponential backoff)


class IngestionPipeline:
    """
    Manages the ingestion of articles from sources into the database.
    Includes error handling with retries and exponential backoff.
    """
    
    def __init__(self, config_path="../../configs/sources.yml"):
        """
        Initialize the pipeline with a scraper and database session.
        
        Args:
            config_path: Path to the sources YAML configuration file.
        """
        self.scraper = Scraper(config_path=config_path)
        self.session = get_session()
        self.failed_sources = set()  # Track sources with persistent failures
        logging.info("Ingestion pipeline initialized.")
    
    def _retry_with_backoff(self, func, *args, **kwargs):
        """
        Execute a function with retries and exponential backoff.
        
        Args:
            func: Function to retry.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.
            
        Returns:
            Result of the function if successful, None otherwise.
        """
        last_exception = None
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                delay = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                logging.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay} seconds...")
                time.sleep(delay)
        
        logging.error(f"All {MAX_RETRIES} attempts failed: {last_exception}")
        return None
    
    def ingest_source(self, source_data) -> int:
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
        
        # Skip if source has persistent failures
        if source_data["domain"] in self.failed_sources:
            logging.warning(f"Skipping source with persistent failures: {source_data['name']}")
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
        
        # Scrape articles from the source with retries
        try:
            articles = self._retry_with_backoff(self.scraper.scrape_source, source_data)
            if articles is None:
                self.failed_sources.add(source_data["domain"])
                logging.error(f"Failed to scrape {source_data['name']} after retries. Marking as failed.")
                return 0
            
            logging.info(f"Scraped {len(articles)} articles from {source_data['name']}")
        except Exception as e:
            logging.error(f"Unexpected error scraping {source_data['name']}: {e}")
            self.failed_sources.add(source_data["domain"])
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
                        logging.warning(f"Invalid date format for article: {article.get('url', 'unknown')}")
                
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
                logging.debug(f"Ingested article: {article.get('title', 'No title')[:50]}...")
                
            except Exception as e:
                logging.error(f"Error processing article from {source_data['name']}: {e}")
                self.session.rollback()
                continue
        
        self.session.commit()
        logging.info(f"Ingested {ingested_count} articles from {source_data['name']}")
        return ingested_count
    
    def ingest_all_sources(self) -> int:
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
        if self.failed_sources:
            logging.warning(f"Failed to ingest from {len(self.failed_sources)} sources: {', '.join(self.failed_sources)}")
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