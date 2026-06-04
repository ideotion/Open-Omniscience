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
Tests for StreamProcessor module
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from src.monitoring.stream_processor import (
    StreamProcessor,
    BatchStreamProcessor,
    StreamConfig,
    StreamStatus,
    StreamType,
    StreamStats,
    ProcessedItem,
)


@pytest.fixture
def stream_config():
    return StreamConfig(
        stream_id="test_stream",
        stream_type=StreamType.RSS,
        source_url="https://example.com/rss",
        name="Test Stream",
        description="A test stream",
        batch_size=50,
        batch_timeout=2.0,
        max_retries=3,
        retry_delay=1.0
    )


@pytest.fixture
def stream_processor():
    return StreamProcessor(max_concurrent_streams=2, max_queue_size=100)


@pytest.fixture
def batch_stream_processor():
    return BatchStreamProcessor(max_concurrent_streams=2, max_queue_size=100)


class TestStreamConfig:
    def test_stream_config_creation(self, stream_config):
        assert stream_config.stream_id == "test_stream"
        assert stream_config.stream_type == StreamType.RSS
        assert stream_config.source_url == "https://example.com/rss"
        assert stream_config.batch_size == 50
        assert stream_config.batch_timeout == 2.0
    
    def test_stream_config_to_dict(self, stream_config):
        config_dict = stream_config.to_dict()
        assert config_dict["stream_id"] == "test_stream"
        assert config_dict["stream_type"] == "rss"
        assert config_dict["source_url"] == "https://example.com/rss"
    
    def test_stream_config_from_dict(self, stream_config):
        config_dict = stream_config.to_dict()
        new_config = StreamConfig.from_dict(config_dict)
        assert new_config.stream_id == stream_config.stream_id
        assert new_config.stream_type == stream_config.stream_type
        assert new_config.source_url == stream_config.source_url


class TestStreamStats:
    def test_stream_stats_creation(self):
        stats = StreamStats(stream_id="test")
        assert stats.stream_id == "test"
        assert stats.items_processed == 0
        assert stats.items_failed == 0
        assert stats.success_rate == 0.0
    
    def test_stream_stats_success_rate(self):
        stats = StreamStats(stream_id="test")
        stats.items_processed = 10
        stats.items_failed = 2
        assert stats.success_rate == 0.8
    
    def test_stream_stats_to_dict(self):
        stats = StreamStats(stream_id="test")
        stats_dict = stats.to_dict()
        assert stats_dict["stream_id"] == "test"
        assert stats_dict["items_processed"] == 0


class TestProcessedItem:
    def test_processed_item_creation(self):
        data = {"title": "Test", "content": "Hello"}
        item = ProcessedItem(data=data, stream_id="test_stream")
        assert item.data == data
        assert item.stream_id == "test_stream"
        assert item.item_id != ""
        assert len(item.item_id) == 16
    
    def test_processed_item_to_dict(self):
        data = {"title": "Test"}
        item = ProcessedItem(data=data, stream_id="test")
        item_dict = item.to_dict()
        assert item_dict["stream_id"] == "test"
        assert item_dict["data"] == data


class TestStreamProcessor:
    def test_initialization(self, stream_processor):
        assert stream_processor is not None
        assert stream_processor.max_concurrent_streams == 2
        assert stream_processor.max_queue_size == 100
        assert not stream_processor.is_running
    
    @pytest.mark.asyncio
    async def test_add_stream(self, stream_processor, stream_config):
        await stream_processor.add_stream(stream_config)
        assert "test_stream" in stream_processor.streams
        assert stream_processor.streams["test_stream"].name == "Test Stream"
    
    @pytest.mark.asyncio
    async def test_add_duplicate_stream(self, stream_processor, stream_config):
        await stream_processor.add_stream(stream_config)
        # Adding again should update
        await stream_processor.add_stream(stream_config)
        assert len(stream_processor.streams) == 1
    
    @pytest.mark.asyncio
    async def test_remove_stream(self, stream_processor, stream_config):
        await stream_processor.add_stream(stream_config)
        result = await stream_processor.remove_stream("test_stream")
        assert result is True
        assert "test_stream" not in stream_processor.streams
    
    @pytest.mark.asyncio
    async def test_remove_nonexistent_stream(self, stream_processor):
        result = await stream_processor.remove_stream("nonexistent")
        assert result is False
    
    @pytest.mark.asyncio
    async def test_start_stop(self, stream_processor):
        await stream_processor.start()
        assert stream_processor.is_running
        
        await stream_processor.stop()
        assert not stream_processor.is_running
    
    @pytest.mark.asyncio
    async def test_get_status(self, stream_processor, stream_config):
        await stream_processor.add_stream(stream_config)
        status = stream_processor.get_status()
        assert "running" in status
        assert "streams" in status
        assert "test_stream" in status["streams"]
    
    @pytest.mark.asyncio
    async def test_get_stream_stats(self, stream_processor, stream_config):
        await stream_processor.add_stream(stream_config)
        stats = stream_processor.get_stream_stats("test_stream")
        assert stats is not None
        assert stats.stream_id == "test_stream"
    
    @pytest.mark.asyncio
    async def test_get_all_stats(self, stream_processor, stream_config):
        await stream_processor.add_stream(stream_config)
        all_stats = stream_processor.get_all_stats()
        assert len(all_stats) == 1
        assert "test_stream" in all_stats


class TestBatchStreamProcessor:
    def test_initialization(self, batch_stream_processor):
        assert batch_stream_processor is not None
        assert isinstance(batch_stream_processor, StreamProcessor)
    
    @pytest.mark.asyncio
    async def test_add_stream_with_batch_callback(self, batch_stream_processor, stream_config):
        batch_called = []
        
        async def batch_callback(items):
            batch_called.append(len(items))
        
        await batch_stream_processor.add_stream(
            stream_config,
            batch_callback=batch_callback
        )
        
        assert "test_stream" in batch_stream_processor.batch_callbacks
        assert len(batch_stream_processor.batch_callbacks["test_stream"]) == 1


class TestStreamProcessorIntegration:
    @pytest.mark.asyncio
    async def test_processor_lifecycle(self, stream_processor, stream_config):
        # Add stream
        await stream_processor.add_stream(stream_config)
        
        # Start processor
        await stream_processor.start()
        assert stream_processor.is_running
        
        # Check status
        status = stream_processor.get_status()
        assert status["running"] is True
        
        # Stop processor
        await stream_processor.stop()
        assert not stream_processor.is_running
    
    @pytest.mark.asyncio
    async def test_multiple_streams(self, stream_processor):
        configs = [
            StreamConfig(
                stream_id=f"stream_{i}",
                stream_type=StreamType.RSS,
                source_url=f"https://example.com/rss_{i}",
                batch_size=10
            )
            for i in range(3)
        ]
        
        for config in configs:
            await stream_processor.add_stream(config)
        
        assert len(stream_processor.streams) == 3
        
        status = stream_processor.get_status()
        assert len(status["streams"]) == 3
