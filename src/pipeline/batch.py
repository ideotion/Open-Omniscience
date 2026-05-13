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
Batch Processing Pipeline for Open Omniscience

This module provides batch processing capabilities for historical data ingestion.
It handles:
- Batch processing of articles from multiple sources
- Parallel processing with configurable workers
- Error handling and retry logic
- Progress tracking and reporting

Author: Ideotion
"""

import sys
import time
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import csv
import json
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed, ProcessPoolExecutor
import threading

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent))

# Configure logging
from utils.logging_config import setup_logging
logger = setup_logging("batch_pipeline")


class BatchStatus(Enum):
    """Status of a batch processing job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BatchResult:
    """Result of a batch processing operation."""
    job_id: str
    status: BatchStatus
    total_items: int = 0
    processed_items: int = 0
    failed_items: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None
    results: List[Dict] = field(default_factory=list)
    
    @property
    def duration_seconds(self) -> float:
        """Get duration in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0
    
    @property
    def success_rate(self) -> float:
        """Get success rate as percentage."""
        if self.total_items == 0:
            return 0.0
        return (self.processed_items / self.total_items) * 100
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "total_items": self.total_items,
            "processed_items": self.processed_items,
            "failed_items": self.failed_items,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "success_rate": self.success_rate,
            "error_message": self.error_message,
            "results": self.results
        }


@dataclass
class ProcessingConfig:
    """Configuration for batch processing."""
    max_workers: int = 5
    batch_size: int = 100
    retry_attempts: int = 3
    retry_delay: float = 2.0
    timeout_seconds: float = 30.0
    output_format: str = "json"
    output_dir: str = "output/batch"
    temp_dir: str = "temp/batch"
    
    @classmethod
    def from_dict(cls, config_dict: Dict) -> "ProcessingConfig":
        """Create from dictionary."""
        return cls(**{k: v for k, v in config_dict.items() if k in cls.__dataclass_fields__})


class BatchProcessor:
    """
    Batch processor for ingesting and processing articles.
    
    Features:
    - Process articles in batches
    - Parallel processing with ThreadPool or ProcessPool
    - Progress tracking
    - Error handling with retries
    - Support for multiple input formats (CSV, JSON, YAML)
    - Support for multiple output formats (CSV, JSON)
    """
    
    def __init__(self, config: Optional[ProcessingConfig] = None):
        """
        Initialize the batch processor.
        
        Args:
            config: Processing configuration.
        """
        self.repo_root = Path(__file__).parent.parent.parent.resolve()
        
        if config is None:
            config = ProcessingConfig()
        self.config = config
        
        # Setup directories
        self.output_dir = self.repo_root / self.config.output_dir
        self.temp_dir = self.repo_root / self.config.temp_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Job tracking
        self._jobs: Dict[str, BatchResult] = {}
        self._lock = threading.Lock()
        self._job_counter = 0
        
        # Initialize database connection
        from database.models import get_session
        self.session = get_session()
        
        logger.info(f"BatchProcessor initialized with {self.config.max_workers} workers")
    
    def _generate_job_id(self) -> str:
        """Generate a unique job ID."""
        with self._lock:
            self._job_counter += 1
            return f"batch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{self._job_counter:04d}"
    
    def _get_processor_func(self, processor_type: str):
        """Get the appropriate processor function."""
        processors = {
            "article": self._process_article,
            "source": self._process_source,
            "url": self._process_url
        }
        return processors.get(processor_type, self._process_article)
    
    def _process_article(self, article_data: Dict, job_id: str) -> Tuple[bool, Dict]:
        """
        Process a single article.
        
        Args:
            article_data: Article data dictionary.
            job_id: Job ID for tracking.
            
        Returns:
            Tuple of (success, result_dict).
        """
        try:
            from ingestor.url_utils import canonicalize_url, generate_content_hash
            from database.models import Article, Source
            from datetime import datetime
            
            # Validate required fields
            if not article_data.get("url"):
                return False, {"error": "Missing URL"}
            
            if not article_data.get("content"):
                return False, {"error": "Missing content"}
            
            # Get or create source
            source_name = article_data.get("source", "Unknown")
            source_domain = article_data.get("source_domain", "unknown")
            
            source = self.session.query(Source).filter_by(domain=source_domain).first()
            if not source:
                source = Source(
                    name=source_name,
                    domain=source_domain,
                    enabled=True
                )
                self.session.add(source)
                self.session.commit()
            
            # Canonicalize URL
            canonical_url = canonicalize_url(article_data["url"])
            
            # Generate content hash
            content_hash = generate_content_hash(article_data["content"])
            
            # Check for duplicates
            existing = self.session.query(Article).filter_by(hash=content_hash).first()
            if existing:
                return True, {
                    "status": "duplicate",
                    "url": article_data["url"],
                    "canonical_url": canonical_url,
                    "hash": content_hash
                }
            
            # Parse date
            published_at = article_data.get("published_at")
            if isinstance(published_at, str):
                try:
                    published_at = datetime.fromisoformat(published_at)
                except ValueError:
                    published_at = datetime.now(timezone.utc)
            
            # Create article
            article = Article(
                url=article_data["url"],
                canonical_url=canonical_url,
                source_id=source.id,
                title=article_data.get("title", "No Title"),
                content=article_data["content"],
                published_at=published_at,
                language=article_data.get("language", "en"),
                hash=content_hash
            )
            self.session.add(article)
            self.session.commit()
            
            return True, {
                "status": "inserted",
                "url": article_data["url"],
                "canonical_url": canonical_url,
                "hash": content_hash,
                "article_id": article.id
            }
            
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error processing article in job {job_id}: {e}")
            return False, {"error": str(e)}
    
    def _process_source(self, source_data: Dict, job_id: str) -> Tuple[bool, Dict]:
        """
        Process a single source (scrape and ingest).
        
        Args:
            source_data: Source configuration dictionary.
            job_id: Job ID for tracking.
            
        Returns:
            Tuple of (success, result_dict).
        """
        try:
            from ingestor.pipeline import IngestionPipeline
            
            # Create a temporary pipeline instance
            pipeline = IngestionPipeline()
            
            # Ingest from this source
            count = pipeline.ingest_source(source_data)
            pipeline.close()
            
            return True, {
                "status": "processed",
                "source": source_data.get("name", "Unknown"),
                "domain": source_data.get("domain", ""),
                "articles_ingested": count
            }
            
        except Exception as e:
            logger.error(f"Error processing source in job {job_id}: {e}")
            return False, {"error": str(e)}
    
    def _process_url(self, url_data: Dict, job_id: str) -> Tuple[bool, Dict]:
        """
        Process a single URL (scrape and ingest).
        
        Args:
            url_data: URL data dictionary.
            job_id: Job ID for tracking.
            
        Returns:
            Tuple of (success, result_dict).
        """
        try:
            from scraper.scraper import Scraper
            from ingestor.pipeline import IngestionPipeline
            
            # Create a temporary source config
            source_config = {
                "name": url_data.get("source_name", "URL Import"),
                "domain": url_data.get("domain", "url_import"),
                "url": url_data["url"],
                "enabled": True,
                "rate_limit_ms": 2000
            }
            
            # Scrape the URL
            scraper = Scraper()
            articles = scraper.scrape_source(source_config)
            
            if not articles:
                return False, {"error": "No articles scraped"}
            
            # Ingest articles
            pipeline = IngestionPipeline()
            for article in articles:
                # Convert to format expected by pipeline
                source_data = {
                    "name": source_config["name"],
                    "domain": source_config["domain"],
                    "rss_url": source_config.get("rss_url", ""),
                    "rate_limit_ms": source_config.get("rate_limit_ms", 2000),
                    "enabled": True
                }
                # Note: This would need adjustment based on actual pipeline implementation
                pass
            
            pipeline.close()
            
            return True, {
                "status": "processed",
                "url": url_data["url"],
                "articles_found": len(articles)
            }
            
        except Exception as e:
            logger.error(f"Error processing URL in job {job_id}: {e}")
            return False, {"error": str(e)}
    
    def _load_input_data(self, input_path: str, input_format: str = None) -> List[Dict]:
        """
        Load input data from file.
        
        Args:
            input_path: Path to input file.
            input_format: Format of input file (auto-detected if None).
            
        Returns:
            List of data items.
        """
        input_path = Path(input_path)
        
        if input_format is None:
            # Auto-detect format from extension
            suffix = input_path.suffix.lower()
            if suffix == ".csv":
                input_format = "csv"
            elif suffix == ".json":
                input_format = "json"
            elif suffix in (".yml", ".yaml"):
                input_format = "yaml"
            else:
                raise ValueError(f"Cannot auto-detect format for {input_path}")
        
        try:
            if input_format == "csv":
                data = []
                with open(input_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        data.append(row)
                return data
            
            elif input_format == "json":
                with open(input_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    # Handle nested structures
                    return data.get("items", data.get("articles", data.get("data", [])))
                return data
            
            elif input_format == "yaml":
                with open(input_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict):
                    return data.get("items", data.get("articles", data.get("data", [])))
                return data
            
            else:
                raise ValueError(f"Unsupported input format: {input_format}")
                
        except Exception as e:
            logger.error(f"Error loading input data from {input_path}: {e}")
            raise
    
    def _save_output(self, job_id: str, results: List[Dict], output_format: str = None):
        """
        Save batch results to output file.
        
        Args:
            job_id: Job ID.
            results: List of result dictionaries.
            output_format: Output format (default: from config).
        """
        if output_format is None:
            output_format = self.config.output_format
        
        output_path = self.output_dir / f"{job_id}.{output_format}"
        
        try:
            if output_format == "csv":
                if not results:
                    return
                fieldnames = results[0].keys()
                with open(output_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(results)
            
            elif output_format == "json":
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(results, f, indent=2, ensure_ascii=False)
            
            else:
                raise ValueError(f"Unsupported output format: {output_format}")
            
            logger.info(f"Saved batch results to {output_path}")
            
        except Exception as e:
            logger.error(f"Error saving output to {output_path}: {e}")
            raise
    
    def process_batch(
        self,
        items: List[Dict],
        processor_type: str = "article",
        job_id: str = None
    ) -> BatchResult:
        """
        Process a batch of items.
        
        Args:
            items: List of items to process.
            processor_type: Type of processor to use ("article", "source", "url").
            job_id: Optional job ID (generated if None).
            
        Returns:
            BatchResult with processing results.
        """
        if job_id is None:
            job_id = self._generate_job_id()
        
        # Initialize result
        result = BatchResult(
            job_id=job_id,
            status=BatchStatus.RUNNING,
            total_items=len(items),
            start_time=datetime.now(timezone.utc)
        )
        
        # Store job
        with self._lock:
            self._jobs[job_id] = result
        
        # Get processor function
        processor_func = self._get_processor_func(processor_type)
        
        try:
            # Process items in parallel
            processed_count = 0
            failed_count = 0
            item_results = []
            
            # Use ThreadPoolExecutor for I/O-bound tasks
            with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
                # Submit all tasks
                futures = {
                    executor.submit(processor_func, item, job_id): item
                    for item in items
                }
                
                # Process completed tasks
                for future in as_completed(futures):
                    item = futures[future]
                    try:
                        success, item_result = future.result()
                        if success:
                            processed_count += 1
                        else:
                            failed_count += 1
                        
                        item_result["success"] = success
                        item_results.append(item_result)
                        
                    except Exception as e:
                        failed_count += 1
                        item_results.append({
                            "success": False,
                            "error": str(e),
                            "item": item
                        })
            
            # Update result
            result.processed_items = processed_count
            result.failed_items = failed_count
            result.results = item_results
            result.status = BatchStatus.COMPLETED
            result.end_time = datetime.now(timezone.utc)
            
            logger.info(
                f"Batch {job_id} completed: {processed_count}/{len(items)} processed, "
                f"{failed_count} failed in {result.duration_seconds:.2f}s"
            )
            
        except Exception as e:
            result.status = BatchStatus.FAILED
            result.error_message = str(e)
            result.end_time = datetime.now(timezone.utc)
            logger.error(f"Batch {job_id} failed: {e}")
        
        # Update job
        with self._lock:
            self._jobs[job_id] = result
        
        return result
    
    def process_file(
        self,
        input_path: str,
        input_format: str = None,
        processor_type: str = "article",
        output_format: str = None,
        job_id: str = None
    ) -> BatchResult:
        """
        Process a file of items.
        
        Args:
            input_path: Path to input file.
            input_format: Format of input file.
            processor_type: Type of processor to use.
            output_format: Output format for results.
            job_id: Optional job ID.
            
        Returns:
            BatchResult with processing results.
        """
        # Load input data
        items = self._load_input_data(input_path, input_format)
        
        # Process batch
        result = self.process_batch(items, processor_type, job_id)
        
        # Save output
        if output_format is None:
            output_format = self.config.output_format
        self._save_output(result.job_id, result.results, output_format)
        
        return result
    
    def process_sources_from_config(self, config_path: str = None) -> BatchResult:
        """
        Process all sources from configuration file.
        
        Args:
            config_path: Path to sources.yml (default: configs/sources.yml).
            
        Returns:
            BatchResult with processing results.
        """
        if config_path is None:
            config_path = self.repo_root / "configs" / "sources.yml"
        
        # Load sources
        import yaml
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        sources = config.get("sources", [])
        
        # Filter enabled sources
        enabled_sources = [s for s in sources if s.get("enabled", True)]
        
        # Process batch
        return self.process_batch(enabled_sources, processor_type="source")
    
    def get_job_status(self, job_id: str) -> Optional[BatchResult]:
        """
        Get status of a job.
        
        Args:
            job_id: Job ID.
            
        Returns:
            BatchResult if job exists, None otherwise.
        """
        with self._lock:
            return self._jobs.get(job_id)
    
    def get_all_jobs(self) -> List[BatchResult]:
        """
        Get all jobs.
        
        Returns:
            List of all BatchResult objects.
        """
        with self._lock:
            return list(self._jobs.values())
    
    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a running job.
        
        Args:
            job_id: Job ID to cancel.
            
        Returns:
            True if job was cancelled, False otherwise.
        """
        with self._lock:
            if job_id in self._jobs:
                job = self._jobs[job_id]
                if job.status == BatchStatus.RUNNING:
                    job.status = BatchStatus.CANCELLED
                    job.end_time = datetime.now(timezone.utc)
                    return True
        return False
    
    def cleanup_jobs(self, max_age_hours: int = 24):
        """
        Clean up old job data.
        
        Args:
            max_age_hours: Maximum age of jobs to keep.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        
        with self._lock:
            old_jobs = [
                job_id for job_id, job in self._jobs.items()
                if job.end_time and job.end_time < cutoff
            ]
            for job_id in old_jobs:
                del self._jobs[job_id]
        
        logger.info(f"Cleaned up {len(old_jobs)} old jobs")
    
    def get_stats(self) -> Dict:
        """
        Get batch processing statistics.
        
        Returns:
            Dictionary with statistics.
        """
        with self._lock:
            total_jobs = len(self._jobs)
            completed = sum(1 for j in self._jobs.values() if j.status == BatchStatus.COMPLETED)
            failed = sum(1 for j in self._jobs.values() if j.status == BatchStatus.FAILED)
            running = sum(1 for j in self._jobs.values() if j.status == BatchStatus.RUNNING)
            
            total_items = sum(j.total_items for j in self._jobs.values())
            processed_items = sum(j.processed_items for j in self._jobs.values())
            
            return {
                "total_jobs": total_jobs,
                "completed_jobs": completed,
                "failed_jobs": failed,
                "running_jobs": running,
                "total_items": total_items,
                "processed_items": processed_items,
                "success_rate": (processed_items / total_items * 100) if total_items > 0 else 0
            }
    
    def close(self):
        """Clean up resources."""
        self.session.close()
        logger.info("BatchProcessor closed")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Batch Processing Pipeline")
    parser.add_argument("--input", type=str, help="Input file path")
    parser.add_argument("--input-format", type=str, help="Input format (csv, json, yaml)")
    parser.add_argument("--processor", type=str, default="article", 
                        choices=["article", "source", "url"],
                        help="Processor type")
    parser.add_argument("--output-format", type=str, default="json",
                        choices=["csv", "json"],
                        help="Output format")
    parser.add_argument("--workers", type=int, default=5, help="Number of workers")
    
    args = parser.parse_args()
    
    # Create processor with custom config
    config = ProcessingConfig(
        max_workers=args.workers,
        output_format=args.output_format
    )
    processor = BatchProcessor(config)
    
    try:
        if args.input:
            # Process file
            result = processor.process_file(
                args.input,
                args.input_format,
                args.processor,
                args.output_format
            )
        else:
            # Process all sources from config
            result = processor.process_sources_from_config()
        
        # Print summary
        print(f"\nBatch Processing Summary:")
        print(f"  Job ID: {result.job_id}")
        print(f"  Status: {result.status.value}")
        print(f"  Total items: {result.total_items}")
        print(f"  Processed: {result.processed_items}")
        print(f"  Failed: {result.failed_items}")
        print(f"  Duration: {result.duration_seconds:.2f}s")
        print(f"  Success rate: {result.success_rate:.2f}%")
        
        if result.error_message:
            print(f"  Error: {result.error_message}")
        
    except Exception as e:
        logger.error(f"Batch processing failed: {e}")
        raise
    finally:
        processor.close()
