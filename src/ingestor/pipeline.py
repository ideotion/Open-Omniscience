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
Ingestion Pipeline for Open Omniscience

This module orchestrates the end-to-end ingestion workflow:
1. Scrape articles from configured sources.
2. Normalize article data (text, dates, metadata).
3. Check for duplicates using advanced deduplication (MinHash + LSH + Content Hash).
4. Canonicalize URLs and resolve redirects.
5. Store new articles in the SQLite database.
6. Handle errors with retries and exponential backoff.

Author: Ideotion
"""

import sys
import logging
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent))

# Import local modules
from scraper.scraper import Scraper
from scraper.source_monitor import SourceMonitor
from ingestor.url_utils import canonicalize_url, resolve_redirects, generate_content_hash
from ingestor.normalizer import ArticleNormalizer
from ingestor.deduplicator import Deduplicator, DeduplicationConfig
from database.models import Article, Source, get_session

# Configure logging using shared config
from utils.logging_config import setup_logging
logger = setup_logging("pipeline")

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds (will use exponential backoff)


class IngestionPipeline:
    """
    Manages the ingestion of articles from sources into the database.
    Includes error handling with retries and exponential backoff.
    
    Features:
    - Source monitoring and health checks
    - Advanced deduplication (MinHash + LSH + Content Hash)
    - Data normalization (text, dates, metadata)
    - URL canonicalization
    - Rate limiting and retry logic
    """
    
    def __init__(self, config_path=None, enable_deduplication=True, enable_normalization=True, enable_monitoring=True):
        """
        Initialize the pipeline with a scraper and database session.
        
        Args:
            config_path: Path to the sources YAML configuration file.
            enable_deduplication: Enable advanced deduplication (default: True).
            enable_normalization: Enable data normalization (default: True).
            enable_monitoring: Enable source monitoring (default: True).
        """
        # Get the absolute path to the repository root
        repo_root = Path(__file__).parent.parent.parent.resolve()
        
        # Use dynamic path for config
        if config_path is None:
            config_path = repo_root / "configs" / "sources.yml"
        
        self.config_path = config_path
        self.scraper = Scraper(str(config_path))
        self.session = get_session()
        self.failed_sources = set()  # Track sources with persistent failures
        
        # Initialize optional components
        self.enable_deduplication = enable_deduplication
        self.enable_normalization = enable_normalization
        self.enable_monitoring = enable_monitoring
        
        if self.enable_deduplication:
            # Use conservative settings for production
            dedup_config = DeduplicationConfig(
                minhash_num_perm=128,
                minhash_threshold=0.85,
                lsh_bands=20,
                lsh_rows=8,
                enable_minhash=True,
                enable_tfidf=False,  # Disable for now (requires fitting)
                enable_content_hash=True
            )
            self.deduplicator = Deduplicator(dedup_config)
            logger.info("Advanced deduplication enabled.")
        
        if self.enable_normalization:
            self.normalizer = ArticleNormalizer()
            logger.info("Data normalization enabled.")
        
        if self.enable_monitoring:
            self.source_monitor = SourceMonitor(str(config_path))
            logger.info("Source monitoring enabled.")
        
        logger.info("Ingestion pipeline initialized.")
    
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
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay} seconds...")
                time.sleep(delay)
        
        logger.error(f"All {MAX_RETRIES} attempts failed: {last_exception}")
        return None
    
    def ingest_source(self, source_data) -> int:
        """
        Ingest articles from a single source.
        
        Args:
            source_data: Dictionary containing source configuration.
            
        Returns:
            int: Number of articles ingested from this source.
        """
        domain = source_data.get("domain", "")
        
        # Check if source is enabled
        if not source_data.get("enabled", True):
            logger.info(f"Skipping disabled source: {source_data.get('name', domain)}")
            return 0
        
        # Skip if source has persistent failures
        if domain in self.failed_sources:
            logger.warning(f"Skipping source with persistent failures: {source_data.get('name', domain)}")
            return 0
        
        # Check source health if monitoring is enabled
        if self.enable_monitoring and self.source_monitor:
            health = self.source_monitor.get_source_health(domain)
            if health and not health.is_healthy():
                logger.warning(f"Skipping unhealthy source: {domain} ({health.status.value})")
                return 0
        
        # Get or create the source in the database
        source = self.session.query(Source).filter_by(domain=domain).first()
        if not source:
            source = Source(
                name=source_data["name"],
                domain=domain,
                rss_url=source_data.get("rss_url"),
                rate_limit_ms=source_data.get("rate_limit_ms", 2000),
                enabled=source_data.get("enabled", True),
                # Add enhanced metadata if available
                reliability_score=source_data.get("reliability_score", 5),
                language=source_data.get("language", "en"),
                region=source_data.get("region", "global"),
                country=source_data.get("country", "US"),
                source_type=source_data.get("source_type", "news")
            )
            self.session.add(source)
            self.session.commit()
            logger.info(f"Added new source to database: {source_data.get('name', domain)}")
        
        # Scrape articles from the source with retries
        try:
            articles = self._retry_with_backoff(self.scraper.scrape_source, source_data)
            if articles is None:
                self.failed_sources.add(domain)
                logger.error(f"Failed to scrape {source_data.get('name', domain)} after retries. Marking as failed.")
                return 0
            
            logger.info(f"Scraped {len(articles)} articles from {source_data.get('name', domain)}")
        except Exception as e:
            logger.error(f"Unexpected error scraping {source_data.get('name', domain)}: {e}")
            self.failed_sources.add(domain)
            return 0
        
        # Process and ingest each article
        ingested_count = 0
        for article in articles:
            try:
                # Normalize article data if enabled
                if self.enable_normalization and self.normalizer:
                    # Prepare article data for normalization
                    article_data = {
                        'url': article.get('url', ''),
                        'title': article.get('title', 'No Title'),
                        'content': article.get('content', ''),
                        'published_at': article.get('published_at'),
                        'language': article.get('language', source_data.get('language', 'en')),
                        'author': article.get('author'),
                        'source': source_data.get('name', domain),
                        'source_domain': domain
                    }
                    normalized = self.normalizer.normalize(article_data)
                    
                    # Use normalized data
                    title = normalized.title
                    content = normalized.content
                    published_at = normalized.published_at
                    language = normalized.language
                    region = normalized.region
                    country = normalized.country
                    author = normalized.author
                    canonical_url = normalized.canonical_url
                else:
                    # Legacy path without normalization
                    title = article.get("title", "No Title")
                    content = article.get("content", "")
                    published_at = article.get("published_at")
                    language = article.get("language", source_data.get("language", "en"))
                    region = None
                    country = None
                    author = article.get("author")
                    canonical_url = canonicalize_url(resolve_redirects(article["url"]))
                
                # Check for duplicates using advanced deduplication if enabled
                if self.enable_deduplication and self.deduplicator:
                    # Use content hash from normalizer if available
                    content_hash = self.deduplicator.get_content_hash(content)
                    
                    # Check if this is a duplicate
                    is_duplicate, dup_id = self.deduplicator.is_duplicate(content)
                    if is_duplicate:
                        logger.debug(f"Duplicate article detected (hash: {content_hash}), skipping.")
                        # Add to deduplicator index for future checks
                        self.deduplicator.add_document(article.get('url', ''), content)
                        continue
                else:
                    # Legacy path: use simple content hash
                    content_hash = generate_content_hash(content)
                    existing_article = self.session.query(Article).filter_by(hash=content_hash).first()
                    if existing_article:
                        logger.debug(f"Duplicate article detected (hash: {content_hash}), skipping.")
                        continue
                
                # Parse published_at if it's a string
                if isinstance(published_at, str):
                    try:
                        published_at = datetime.fromisoformat(published_at)
                    except ValueError:
                        published_at = datetime.now(timezone.utc)
                        logger.warning(f"Invalid date format for article: {article.get('url', 'unknown')}")
                
                # Create new article record
                new_article = Article(
                    url=article.get("url", ""),
                    canonical_url=canonical_url,
                    source_id=source.id,
                    title=title,
                    content=content,
                    published_at=published_at,
                    language=language,
                    hash=content_hash,
                    region=region,
                    country=country,
                    author=author
                )
                self.session.add(new_article)
                ingested_count += 1
                
                # Add to deduplicator index for future checks
                if self.enable_deduplication and self.deduplicator:
                    self.deduplicator.add_document(article.get('url', ''), content)
                
                logger.debug(f"Ingested article: {title[:50]}...")
                
            except Exception as e:
                logger.error(f"Error processing article from {source_data.get('name', domain)}: {e}")
                self.session.rollback()
                continue
        
        try:
            self.session.commit()
        finally:
            self.session.close()
            self.session = get_session()  # Reopen session for next operations
        
        logger.info(f"Ingested {ingested_count} articles from {source_data.get('name', domain)}")
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
        
        logger.info(f"Total articles ingested: {total_ingested}")
        if self.failed_sources:
            logger.warning(f"Failed to ingest from {len(self.failed_sources)} sources: {', '.join(self.failed_sources)}")
        return total_ingested
    
    def close(self):
        """Close the database session and cleanup resources."""
        self.session.close()
        
        # Close optional components
        if self.enable_deduplication and hasattr(self, 'deduplicator'):
            self.deduplicator.clear()
        
        if self.enable_monitoring and hasattr(self, 'source_monitor'):
            self.source_monitor.close()
        
        logger.info("Database session closed. Resources cleaned up.")
    
    def check_source_health(self, domain: str = None):
        """
        Check health of a specific source or all sources.
        
        Args:
            domain: Optional domain to check. If None, checks all sources.
            
        Returns:
            Dictionary with health information.
        """
        if not self.enable_monitoring or not self.source_monitor:
            logger.warning("Source monitoring is disabled.")
            return {}
        
        if domain:
            health = self.source_monitor.check_source_health(
                self.source_monitor.get_source_info(domain)
            )
            return {domain: health.to_dict()}
        else:
            results = self.source_monitor.check_all_sources()
            return {d: h.to_dict() for d, h in results.items()}
    
    def get_health_stats(self):
        """
        Get health monitoring statistics.
        
        Returns:
            Dictionary with health statistics.
        """
        if not self.enable_monitoring or not self.source_monitor:
            return {}
        return self.source_monitor.get_health_stats()
    
    def get_deduplication_stats(self):
        """
        Get deduplication statistics.
        
        Returns:
            Dictionary with deduplication statistics.
        """
        if not self.enable_deduplication or not self.deduplicator:
            return {}
        return self.deduplicator.get_stats()


if __name__ == "__main__":
    pipeline = IngestionPipeline()
    try:
        total = pipeline.ingest_all_sources()
        print(f"Ingestion complete. Total articles ingested: {total}")
    except Exception as e:
        logger.error(f"Error in ingestion pipeline: {e}")
    finally:
        pipeline.close()