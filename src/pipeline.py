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
Open-Omniscience - Main Pipeline

Orchestrates the flow of data through all pillars:
1. Data Ingestion (Pillar 1)
2. Data Processing (Pillar 2)
3. Analytics & Intelligence (Pillar 3)
4. Legal Admissibility (Pillar 4)
"""

import time
import hashlib
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable, Union
from enum import Enum
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse


class PipelineStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    STOPPED = "stopped"


class PipelineMode(Enum):
    FULL = "full"  # Run all pillars
    INGEST_ONLY = "ingest_only"  # Pillar 1 only
    PROCESS_ONLY = "process_only"  # Pillar 2 only
    ANALYZE_ONLY = "analyze_only"  # Pillar 3 only
    LEGAL_ONLY = "legal_only"  # Pillar 4 only
    CUSTOM = "custom"  # Custom pipeline


@dataclass
class PipelineConfig:
    """Configuration for the pipeline."""
    mode: PipelineMode = PipelineMode.FULL
    max_workers: int = 5
    batch_size: int = 10
    timeout: float = 300.0  # 5 minutes
    retry_attempts: int = 3
    log_level: str = "INFO"
    
    # Pillar-specific configs
    pillar1: Dict[str, Any] = field(default_factory=dict)
    pillar2: Dict[str, Any] = field(default_factory=dict)
    pillar3: Dict[str, Any] = field(default_factory=dict)
    pillar4: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Result of a pipeline execution."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    duration: float = 0.0
    pillar_results: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestedData:
    """Data ingested from a source."""
    url: str
    content: str
    raw_content: bytes
    headers: Dict[str, str]
    timestamp: float = field(default_factory=time.time)
    source_type: str = "web"
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def content_hash(self) -> str:
        """Get SHA-256 hash of the content."""
        return hashlib.sha256(self.raw_content).hexdigest()
    
    @property
    def domain(self) -> str:
        """Get the domain of the URL."""
        return urlparse(self.url).netloc
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "url": self.url,
            "content": self.content,
            "content_hash": self.content_hash,
            "headers": self.headers,
            "timestamp": self.timestamp,
            "source_type": self.source_type,
            "metadata": self.metadata,
        }


class OpenOmnisciencePipeline:
    """
    Main pipeline that orchestrates data flow through all pillars.
    
    The pipeline:
    1. Ingests data from various sources (Pillar 1)
    2. Processes and validates the data (Pillar 2)
    3. Analyzes the data for insights (Pillar 3)
    4. Ensures legal compliance (Pillar 4)
    
    Each step can be run independently or as part of the full pipeline.
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        """
        Initialize the pipeline.
        
        Args:
            config: Pipeline configuration.
        """
        self.config = config if config else PipelineConfig()
        self.logger = logging.getLogger("OpenOmnisciencePipeline")
        
        # State
        self.status = PipelineStatus.IDLE
        self.running = False
        self.executor = ThreadPoolExecutor(max_workers=self.config.max_workers)
        
        # Initialize pillars
        self._init_pillars()
        
        # Statistics
        self.stats = {
            "total_runs": 0,
            "successful_runs": 0,
            "failed_runs": 0,
            "total_items": 0,
            "processed_items": 0,
            "errors": 0,
        }

    def _init_pillars(self) -> None:
        """Initialize all pillars."""
        # Pillar 1: Data Ingestion
        self.pillar1 = self._init_pillar1()
        
        # Pillar 2: Data Processing
        self.pillar2 = self._init_pillar2()
        
        # Pillar 3: Analytics & Intelligence
        self.pillar3 = self._init_pillar3()
        
        # Pillar 4: Legal Admissibility
        self.pillar4 = self._init_pillar4()

    def _init_pillar1(self):
        """Initialize Pillar 1 (Data Ingestion)."""
        # Pillar 1 uses the built-in scraper (src/scraper/scraper.py)
        from scraper.scraper import Scraper
        return Scraper()

    def _init_pillar2(self):
        """Initialize Pillar 2 (Data Processing)."""
        try:
            from pillar2.src.analysis.statistical_tests import StatisticalTests
            from pillar2.src.analysis.peer_review import PeerReviewSimulator
            from pillar2.src.analysis.reproducibility import ReproducibilityCalculator
            
            return {
                "statistical_tests": StatisticalTests(),
                "peer_review": PeerReviewSimulator(),
                "reproducibility": ReproducibilityCalculator(),
            }
        except ImportError as e:
            self.logger.warning(f"Could not import Pillar 2: {e}")
            return None

    def _init_pillar3(self):
        """Initialize Pillar 3 (Analytics & Intelligence)."""
        try:
            from pillar3.src.analysis.deepfake_detector import DeepfakeDetector
            from pillar3.src.analysis.propaganda import PropagandaDetector
            
            return {
                "deepfake_detector": DeepfakeDetector(),
                "propaganda_detector": PropagandaDetector(),
            }
        except ImportError as e:
            self.logger.warning(f"Could not import Pillar 3: {e}")
            return None

    def _init_pillar4(self):
        """Initialize Pillar 4 (Legal Admissibility)."""
        try:
            from pillar4.src.legal.validator import LegalValidator
            from pillar4.src.crypto.provenance import DataLineageTracker
            from pillar4.src.audit.chain_of_custody import DataLineageTracker as ChainOfCustodyTracker
            from pillar4.src.compliance.gdpr import GDPRComplianceChecker
            from pillar4.src.compliance.copyright import CopyrightComplianceChecker
            
            return {
                "validator": LegalValidator(),
                "provenance": DataLineageTracker(),
                "chain_of_custody": ChainOfCustodyTracker(),
                "gdpr": GDPRComplianceChecker(),
                "copyright": CopyrightComplianceChecker(),
            }
        except ImportError as e:
            self.logger.warning(f"Could not import Pillar 4: {e}")
            return None

    def start(self) -> None:
        """Start the pipeline."""
        if self.running:
            return
        
        self.running = True
        self.status = PipelineStatus.RUNNING
        self.logger.info("Pipeline started")

    def stop(self) -> None:
        """Stop the pipeline."""
        self.running = False
        self.status = PipelineStatus.STOPPED
        self.executor.shutdown(wait=True)
        self.logger.info("Pipeline stopped")

    def pause(self) -> None:
        """Pause the pipeline."""
        self.status = PipelineStatus.PAUSED
        self.logger.info("Pipeline paused")

    def resume(self) -> None:
        """Resume the pipeline."""
        if self.status == PipelineStatus.PAUSED:
            self.status = PipelineStatus.RUNNING
            self.logger.info("Pipeline resumed")

    def process_url(self, url: str) -> PipelineResult:
        """
        Process a single URL through the pipeline.
        
        Args:
            url: URL to process.
        
        Returns:
            PipelineResult with the processing outcome.
        """
        start_time = time.time()
        result = PipelineResult(
            success=False,
            start_time=start_time,
            metadata={"url": url},
        )
        
        try:
            # Step 1: Ingest data (Pillar 1)
            if self.config.mode in [PipelineMode.FULL, PipelineMode.INGEST_ONLY]:
                ingest_result = self._ingest(url)
                if ingest_result is None:
                    raise ValueError(f"Failed to ingest URL: {url}")
                result.pillar_results["pillar1"] = ingest_result.to_dict()
                result.data = ingest_result.to_dict()
            
            # Step 2: Process data (Pillar 2)
            if self.config.mode in [PipelineMode.FULL, PipelineMode.PROCESS_ONLY]:
                if result.data is None:
                    raise ValueError("No data to process")
                process_result = self._process(result.data)
                result.pillar_results["pillar2"] = process_result
                result.data["pillar2"] = process_result
            
            # Step 3: Analyze data (Pillar 3)
            if self.config.mode in [PipelineMode.FULL, PipelineMode.ANALYZE_ONLY]:
                if result.data is None:
                    raise ValueError("No data to analyze")
                analyze_result = self._analyze(result.data)
                result.pillar_results["pillar3"] = analyze_result
                result.data["pillar3"] = analyze_result
            
            # Step 4: Validate legally (Pillar 4)
            if self.config.mode in [PipelineMode.FULL, PipelineMode.LEGAL_ONLY]:
                if result.data is None:
                    raise ValueError("No data to validate")
                legal_result = self._validate_legal(result.data)
                result.pillar_results["pillar4"] = legal_result.to_dict() if hasattr(legal_result, 'to_dict') else legal_result
                result.data["pillar4"] = result.pillar_results["pillar4"]
            
            # Success
            result.success = True
            result.end_time = time.time()
            result.duration = result.end_time - start_time
            
            # Update stats
            self.stats["total_runs"] += 1
            self.stats["successful_runs"] += 1
            self.stats["processed_items"] += 1
            
            self.logger.info(f"Processed URL: {url} in {result.duration:.2f}s")
            
        except Exception as e:
            result.errors.append(str(e))
            result.end_time = time.time()
            result.duration = result.end_time - start_time
            
            self.stats["total_runs"] += 1
            self.stats["failed_runs"] += 1
            self.stats["errors"] += 1
            
            self.logger.error(f"Error processing URL {url}: {e}")
        
        return result

    def process_urls(self, urls: List[str]) -> List[PipelineResult]:
        """
        Process multiple URLs through the pipeline.
        
        Args:
            urls: List of URLs to process.
        
        Returns:
            List of PipelineResult objects.
        """
        results = []
        
        # Use thread pool for parallel processing
        futures = []
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            for url in urls:
                futures.append(executor.submit(self.process_url, url))
            
            for future in futures:
                try:
                    results.append(future.result(timeout=self.config.timeout))
                except Exception as e:
                    results.append(PipelineResult(
                        success=False,
                        errors=[str(e)],
                        metadata={"url": "unknown"},
                    ))
        
        return results

    async def process_urls_async(self, urls: List[str]) -> List[PipelineResult]:
        """
        Process multiple URLs asynchronously.
        
        Args:
            urls: List of URLs to process.
        
        Returns:
            List of PipelineResult objects.
        """
        results = []
        tasks = []
        
        async def process_single(url: str) -> PipelineResult:
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as pool:
                return await loop.run_in_executor(pool, self.process_url, url)
        
        for url in urls:
            tasks.append(process_single(url))
        
        # Run in batches to avoid overwhelming the system
        for i in range(0, len(tasks), self.config.batch_size):
            batch = tasks[i:i + self.config.batch_size]
            batch_results = await asyncio.gather(*batch, return_exceptions=True)
            
            for result in batch_results:
                if isinstance(result, Exception):
                    results.append(PipelineResult(
                        success=False,
                        errors=[str(result)],
                        metadata={"url": "unknown"},
                    ))
                else:
                    results.append(result)
        
        return results

    def _ingest(self, url: str) -> IngestedData:
        """
        Ingest data from a URL (Pillar 1).
        
        Args:
            url: URL to ingest.
        
        Returns:
            IngestedData with the ingested content.
        """
        if self.pillar1:
            # Use HTTrack wrapper
            result = self.pillar1.download_page(url)
            if result and result.status.value == "SUCCESS":
                # For now, we'll use a simple approach
                # In a full implementation, we would extract content from the downloaded files
                import requests
                response = requests.get(url, timeout=30)
                return IngestedData(
                    url=url,
                    content=response.text,
                    raw_content=response.content,
                    headers=dict(response.headers),
                    source_type="web",
                    metadata={
                        "status_code": response.status_code,
                        "content_type": response.headers.get('Content-Type', ''),
                    },
                )
        
        # Fallback to requests
        import requests
        response = requests.get(url, timeout=30)
        return IngestedData(
            url=url,
            content=response.text,
            raw_content=response.content,
            headers=dict(response.headers),
            source_type="web",
            metadata={
                "status_code": response.status_code,
                "content_type": response.headers.get('Content-Type', ''),
            },
        )

    def _process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process data (Pillar 2).
        
        Args:
            data: Data to process.
        
        Returns:
            Dictionary with processing results.
        """
        results = {}
        
        if self.pillar2:
            # Statistical analysis
            if "statistical_tests" in self.pillar2:
                # Example: Run a simple statistical test
                # In a real implementation, we would extract numerical data from the content
                results["statistical_analysis"] = {
                    "status": "placeholder",
                    "note": "Statistical analysis would be performed here",
                }
            
            # Peer review simulation
            if "peer_review" in self.pillar2:
                content = data.get("content", "")
                if content:
                    # Run peer review on the content
                    session = self.pillar2["peer_review"].conduct_multi_model_review(content)
                    results["peer_review"] = session.to_dict()
            
            # Reproducibility scoring
            if "reproducibility" in self.pillar2:
                score = self.pillar2["reproducibility"].calculate_score()
                results["reproducibility"] = score.to_dict()
        
        return results

    def _analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze data (Pillar 3).
        
        Args:
            data: Data to analyze.
        
        Returns:
            Dictionary with analysis results.
        """
        results = {}
        
        if self.pillar3:
            content = data.get("content", "")
            url = data.get("url", "")
            
            # Deepfake detection (for images/videos in content)
            if "deepfake_detector" in self.pillar3:
                # In a real implementation, we would extract images/videos from the content
                # and run deepfake detection on them
                results["deepfake_detection"] = {
                    "status": "placeholder",
                    "note": "Deepfake detection would be performed on extracted media",
                }
            
            # Propaganda detection
            if "propaganda_detector" in self.pillar3 and content:
                propaganda_result = self.pillar3["propaganda_detector"].detect(content)
                results["propaganda_detection"] = propaganda_result.to_dict()
        
        return results

    def _validate_legal(self, data: Dict[str, Any]) -> Any:
        """
        Validate data for legal compliance (Pillar 4).
        
        Args:
            data: Data to validate.
        
        Returns:
            Legal validation result.
        """
        if self.pillar4 and "validator" in self.pillar4:
            url = data.get("url", "")
            content = data.get("content", "")
            metadata = data.get("metadata", {})
            
            # Run legal validation
            result = self.pillar4["validator"].validate_all(
                data={"content": content, "url": url},
                source_url=url,
                ingestion_metadata=metadata,
            )
            return result
        
        return {"status": "not_validated", "note": "Legal validation not available"}

    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        pillar_stats = {}
        
        if self.pillar2:
            if "statistical_tests" in self.pillar2:
                pass  # Add stats if available
        
        if self.pillar4 and "validator" in self.pillar4:
            pillar_stats["pillar4"] = self.pillar4["validator"].get_stats()
        
        return {
            "status": self.status.value,
            "running": self.running,
            "total_runs": self.stats["total_runs"],
            "successful_runs": self.stats["successful_runs"],
            "failed_runs": self.stats["failed_runs"],
            "processed_items": self.stats["processed_items"],
            "errors": self.stats["errors"],
            "pillars": pillar_stats,
            "config": {
                "mode": self.config.mode.value,
                "max_workers": self.config.max_workers,
                "batch_size": self.config.batch_size,
                "timeout": self.config.timeout,
            },
        }

    def reset_stats(self) -> None:
        """Reset pipeline statistics."""
        self.stats = {
            "total_runs": 0,
            "successful_runs": 0,
            "failed_runs": 0,
            "total_items": 0,
            "processed_items": 0,
            "errors": 0,
        }
        self.logger.info("Pipeline statistics reset")


# Global pipeline instance (optional)
_default_pipeline = None


def get_pipeline(config: Optional[PipelineConfig] = None) -> OpenOmnisciencePipeline:
    """
    Get or create the default pipeline.
    
    Args:
        config: Pipeline configuration.
    
    Returns:
        OpenOmnisciencePipeline instance.
    """
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = OpenOmnisciencePipeline(config)
    return _default_pipeline


# Convenience functions
def process_single(url: str) -> PipelineResult:
    """
    Process a single URL through the pipeline.
    
    Args:
        url: URL to process.
    
    Returns:
        PipelineResult with the processing outcome.
    """
    pipeline = get_pipeline()
    pipeline.start()
    try:
        return pipeline.process_url(url)
    finally:
        pipeline.stop()


async def process_multiple(urls: List[str]) -> List[PipelineResult]:
    """
    Process multiple URLs through the pipeline asynchronously.
    
    Args:
        urls: List of URLs to process.
    
    Returns:
        List of PipelineResult objects.
    """
    pipeline = get_pipeline()
    pipeline.start()
    try:
        return await pipeline.process_urls_async(urls)
    finally:
        pipeline.stop()
