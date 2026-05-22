"""
Open Omniscience - Pipeline Tests

Tests for the main orchestration pipeline.

Author: Ideotion
License: GNU GPLv3
"""

import pytest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

# Add src to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from main_pipeline import (
    OpenOmnisciencePipeline,
    PipelineConfig,
    PipelineStatus,
    PipelineMode,
    PipelineResult,
    IngestedData,
    get_pipeline,
    process_single,
)


@pytest.fixture
def pipeline_config():
    """Create a test pipeline configuration."""
    return PipelineConfig(
        mode=PipelineMode.INGEST_ONLY,
        max_workers=2,
        batch_size=5,
        timeout=10.0,
        retry_attempts=2,
        log_level="DEBUG"
    )


@pytest.fixture
def pipeline(pipeline_config):
    """Create a pipeline instance for testing."""
    return OpenOmnisciencePipeline(config=pipeline_config)


class TestPipelineConfig:
    """Tests for PipelineConfig."""
    
    def test_default_config(self):
        """Test default pipeline configuration."""
        config = PipelineConfig()
        
        assert config.mode == PipelineMode.FULL
        assert config.max_workers == 5
        assert config.batch_size == 10
        assert config.timeout == 300.0
        assert config.retry_attempts == 3
        assert config.log_level == "INFO"
    
    def test_custom_config(self, pipeline_config):
        """Test custom pipeline configuration."""
        assert pipeline_config.mode == PipelineMode.INGEST_ONLY
        assert pipeline_config.max_workers == 2
        assert pipeline_config.batch_size == 5


class TestPipelineStatus:
    """Tests for PipelineStatus enum."""
    
    def test_status_values(self):
        """Test pipeline status values."""
        assert PipelineStatus.IDLE.value == "idle"
        assert PipelineStatus.RUNNING.value == "running"
        assert PipelineStatus.PAUSED.value == "paused"
        assert PipelineStatus.ERROR.value == "error"
        assert PipelineStatus.STOPPED.value == "stopped"


class TestPipelineMode:
    """Tests for PipelineMode enum."""
    
    def test_mode_values(self):
        """Test pipeline mode values."""
        assert PipelineMode.FULL.value == "full"
        assert PipelineMode.INGEST_ONLY.value == "ingest_only"
        assert PipelineMode.PROCESS_ONLY.value == "process_only"
        assert PipelineMode.ANALYZE_ONLY.value == "analyze_only"
        assert PipelineMode.LEGAL_ONLY.value == "legal_only"
        assert PipelineMode.CUSTOM.value == "custom"


class TestIngestedData:
    """Tests for IngestedData dataclass."""
    
    def test_ingested_data_creation(self):
        """Test IngestedData creation."""
        data = IngestedData(
            url="https://example.com",
            content="Test content",
            raw_content=b"Test content",
            headers={"Content-Type": "text/html"},
            source_type="web"
        )
        
        assert data.url == "https://example.com"
        assert data.content == "Test content"
        assert data.content_hash == "559aead08264d5795d3909718c465b00441f584f46645a01a95ab7d0e08fa79"
        assert data.domain == "example.com"
    
    def test_content_hash_consistency(self):
        """Test that content hash is consistent."""
        data1 = IngestedData(
            url="https://example.com",
            content="Test content",
            raw_content=b"Test content",
            headers={},
        )
        data2 = IngestedData(
            url="https://example.com",
            content="Test content",
            raw_content=b"Test content",
            headers={},
        )
        
        assert data1.content_hash == data2.content_hash
    
    def test_to_dict(self):
        """Test IngestedData to_dict method."""
        data = IngestedData(
            url="https://example.com",
            content="Test content",
            raw_content=b"Test content",
            headers={"Content-Type": "text/html"},
            source_type="web",
            metadata={"key": "value"}
        )
        
        result = data.to_dict()
        
        assert result["url"] == "https://example.com"
        assert result["content"] == "Test content"
        assert "content_hash" in result
        assert result["source_type"] == "web"
        assert result["metadata"]["key"] == "value"


class TestPipelineResult:
    """Tests for PipelineResult dataclass."""
    
    def test_pipeline_result_creation(self):
        """Test PipelineResult creation."""
        result = PipelineResult(
            success=True,
            data={"key": "value"},
            errors=["Error 1"],
            warnings=["Warning 1"],
            start_time=1000.0,
            end_time=2000.0,
            duration=1000.0,
            metadata={"url": "https://example.com"}
        )
        
        assert result.success is True
        assert result.data == {"key": "value"}
        assert result.errors == ["Error 1"]
        assert result.duration == 1000.0


class TestOpenOmnisciencePipeline:
    """Tests for OpenOmnisciencePipeline class."""
    
    def test_pipeline_initialization(self, pipeline):
        """Test pipeline initialization."""
        assert pipeline.config is not None
        assert pipeline.status == PipelineStatus.IDLE
        assert pipeline.running is False
        assert pipeline.stats is not None
    
    def test_pipeline_start_stop(self, pipeline):
        """Test pipeline start and stop."""
        pipeline.start()
        
        assert pipeline.status == PipelineStatus.RUNNING
        assert pipeline.running is True
        
        pipeline.stop()
        
        assert pipeline.status == PipelineStatus.STOPPED
        assert pipeline.running is False
    
    def test_pipeline_pause_resume(self, pipeline):
        """Test pipeline pause and resume."""
        pipeline.start()
        pipeline.pause()
        
        assert pipeline.status == PipelineStatus.PAUSED
        
        pipeline.resume()
        
        assert pipeline.status == PipelineStatus.RUNNING
    
    def test_get_stats(self, pipeline):
        """Test get_stats method."""
        stats = pipeline.get_stats()
        
        assert "status" in stats
        assert "running" in stats
        assert "total_runs" in stats
        assert "config" in stats
    
    def test_reset_stats(self, pipeline):
        """Test reset_stats method."""
        # Modify some stats
        pipeline.stats["total_runs"] = 10
        pipeline.stats["errors"] = 5
        
        pipeline.reset_stats()
        
        assert pipeline.stats["total_runs"] == 0
        assert pipeline.stats["errors"] == 0
    
    @patch('pipeline.OpenOmnisciencePipeline._ingest')
    def test_process_url_ingest_only(self, mock_ingest, pipeline_config):
        """Test process_url with INGEST_ONLY mode."""
        # Setup mock
        mock_ingest.return_value = IngestedData(
            url="https://example.com",
            content="Test content",
            raw_content=b"Test content",
            headers={},
        )
        
        # Create pipeline with INGEST_ONLY mode
        pipeline_config.mode = PipelineMode.INGEST_ONLY
        pipeline = OpenOmnisciencePipeline(config=pipeline_config)
        
        result = pipeline.process_url("https://example.com")
        
        assert result.success is True
        assert "pillar1" in result.pillar_results
        assert result.metadata["url"] == "https://example.com"
        
        # Verify _ingest was called
        mock_ingest.assert_called_once_with("https://example.com")


class TestGlobalPipeline:
    """Tests for global pipeline functions."""
    
    def test_get_pipeline(self):
        """Test get_pipeline function."""
        pipeline1 = get_pipeline()
        pipeline2 = get_pipeline()
        
        # Should return the same instance
        assert pipeline1 is pipeline2
    
    def test_get_pipeline_with_config(self):
        """Test get_pipeline with custom config."""
        config = PipelineConfig(mode=PipelineMode.INGEST_ONLY)
        pipeline = get_pipeline(config)
        
        assert pipeline.config.mode == PipelineMode.INGEST_ONLY


class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    @patch('pipeline.get_pipeline')
    def test_process_single(self, mock_get_pipeline):
        """Test process_single function."""
        mock_pipeline = Mock()
        mock_pipeline.process_url = Mock(return_value=PipelineResult(success=True))
        mock_get_pipeline.return_value = mock_pipeline
        
        result = process_single("https://example.com")
        
        assert result.success is True
        mock_pipeline.process_url.assert_called_once_with("https://example.com")
        mock_pipeline.start.assert_called_once()
        mock_pipeline.stop.assert_called_once()
