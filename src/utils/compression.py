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
Compression Utilities for Open Omniscience

This module provides comprehensive compression functionality for long-term storage
optimization using open-source algorithms. It supports multiple compression algorithms
with different trade-offs between compression ratio and speed.

Features:
- Multiple compression algorithms (zlib, bz2, lzma, zstandard, lz4, blosc)
- Automatic algorithm selection based on content type and size
- Compression level optimization
- Chunked compression for large data
- Streaming compression/decompression
- Compression benchmarking
- Metadata preservation

Author: Ideotion
"""

import bz2
import hashlib
import json
import logging
import lzma
import struct
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# =============================================================================
# Compression Algorithm Definitions
# =============================================================================

class CompressionAlgorithm(str, Enum):
    """Supported compression algorithms."""
    NONE = "none"
    ZLIB = "zlib"
    BZ2 = "bz2"
    LZMA = "lzma"
    ZSTANDARD = "zstandard"
    LZ4 = "lz4"
    BLOSC = "blosc"
    GZIP = "gzip"
    SNAPPY = "snappy"


# Stable 1-byte id per algorithm for the header. The previous scheme stored only
# the first byte of the name, so bz2/blosc, zlib/zstandard and lzma/lz4 collided
# and decompressed with the WRONG codec (data loss). These ids are unique.
_ALGO_IDS: dict[CompressionAlgorithm, int] = {
    CompressionAlgorithm.NONE: 0,
    CompressionAlgorithm.ZLIB: 1,
    CompressionAlgorithm.BZ2: 2,
    CompressionAlgorithm.LZMA: 3,
    CompressionAlgorithm.ZSTANDARD: 4,
    CompressionAlgorithm.LZ4: 5,
    CompressionAlgorithm.BLOSC: 6,
    CompressionAlgorithm.GZIP: 7,
    CompressionAlgorithm.SNAPPY: 8,
}
_ID_ALGOS: dict[int, CompressionAlgorithm] = {v: k for k, v in _ALGO_IDS.items()}


@dataclass
class CompressionConfig:
    """Configuration for compression operations."""
    algorithm: CompressionAlgorithm = CompressionAlgorithm.ZSTANDARD
    level: int = 6  # 0-9 for most algorithms
    chunk_size: int = 65536  # 64KB chunks
    threads: int = 1  # Number of threads (for multi-threaded algorithms)
    
    # Algorithm-specific settings
    zlib_wbits: int = zlib.MAX_WBITS
    zstandard_dict_size: int = 0  # Dictionary size for zstandard
    blosc_cname: str = "lz4"  # Blosc compressor name
    blosc_shuffle: int = 1  # Blosc shuffle mode
    
    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "algorithm": self.algorithm.value,
            "level": self.level,
            "chunk_size": self.chunk_size,
            "threads": self.threads,
            "zlib_wbits": self.zlib_wbits,
            "zstandard_dict_size": self.zstandard_dict_size,
            "blosc_cname": self.blosc_cname,
            "blosc_shuffle": self.blosc_shuffle
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompressionConfig":
        """Create configuration from dictionary."""
        return cls(
            algorithm=CompressionAlgorithm(data.get("algorithm", "zstandard")),
            level=data.get("level", 6),
            chunk_size=data.get("chunk_size", 65536),
            threads=data.get("threads", 1),
            zlib_wbits=data.get("zlib_wbits", zlib.MAX_WBITS),
            zstandard_dict_size=data.get("zstandard_dict_size", 0),
            blosc_cname=data.get("blosc_cname", "lz4"),
            blosc_shuffle=data.get("blosc_shuffle", 1)
        )


# =============================================================================
# Compression Statistics
# =============================================================================

@dataclass
class CompressionStats:
    """Statistics for compression operations."""
    algorithm: CompressionAlgorithm
    original_size: int
    compressed_size: int
    compression_time: float
    decompression_time: float
    compression_ratio: float
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "algorithm": self.algorithm.value,
            "original_size": self.original_size,
            "compressed_size": self.compressed_size,
            "compression_time": round(self.compression_time, 6),
            "decompression_time": round(self.decompression_time, 6),
            "compression_ratio": round(self.compression_ratio, 4),
            "space_saved": self.original_size - self.compressed_size,
            "space_saved_percentage": round(((self.original_size - self.compressed_size) / self.original_size * 100), 2)
        }


# =============================================================================
# Compression Header Format
# =============================================================================

# Header format: [magic:4][algorithm:1][level:1][original_size:8][hash:32]
# Total: 44 bytes
COMPRESSION_MAGIC = b'OMNC'  # Open Omniscience Compression
# struct '<4sBBHQ32s' = 4 + 1 + 1 + 2 + 8 + 32 = 48 bytes (was wrongly 44).
HEADER_SIZE = 48


# =============================================================================
# Compression Implementations
# =============================================================================

class CompressionError(Exception):
    """Exception raised for compression errors."""
    pass


class Compressor:
    """
    Unified compressor interface supporting multiple algorithms.
    
    This class provides a consistent interface for compressing and decompressing
    data using various open-source compression algorithms.
    """
    
    # Algorithm implementations
    _ALGORITHMS: dict[CompressionAlgorithm, dict[str, Any]] = {
        CompressionAlgorithm.NONE: {
            "compress": lambda data, config: data,
            "decompress": lambda data, config: data,
            "available": True
        },
        CompressionAlgorithm.ZLIB: {
            "compress": lambda data, config: zlib.compress(data, config.level, config.zlib_wbits),
            "decompress": lambda data, config: zlib.decompress(data, config.zlib_wbits),
            "available": True
        },
        CompressionAlgorithm.BZ2: {
            "compress": lambda data, config: bz2.compress(data, config.level),
            "decompress": lambda data, config: bz2.decompress(data),
            "available": True
        },
        CompressionAlgorithm.LZMA: {
            "compress": lambda data, config: lzma.compress(data, format=lzma.FORMAT_XZ, preset=config.level),
            "decompress": lambda data, config: lzma.decompress(data, format=lzma.FORMAT_XZ),
            "available": True
        }
    }
    
    # Default configurations for each algorithm
    _DEFAULT_CONFIGS: dict[CompressionAlgorithm, CompressionConfig] = {
        CompressionAlgorithm.NONE: CompressionConfig(algorithm=CompressionAlgorithm.NONE, level=0),
        CompressionAlgorithm.ZLIB: CompressionConfig(algorithm=CompressionAlgorithm.ZLIB, level=6),
        CompressionAlgorithm.BZ2: CompressionConfig(algorithm=CompressionAlgorithm.BZ2, level=6),
        CompressionAlgorithm.LZMA: CompressionConfig(algorithm=CompressionAlgorithm.LZMA, level=6),
        CompressionAlgorithm.ZSTANDARD: CompressionConfig(algorithm=CompressionAlgorithm.ZSTANDARD, level=6),
        CompressionAlgorithm.LZ4: CompressionConfig(algorithm=CompressionAlgorithm.LZ4, level=6),
        CompressionAlgorithm.BLOSC: CompressionConfig(algorithm=CompressionAlgorithm.BLOSC, level=6),
        CompressionAlgorithm.GZIP: CompressionConfig(algorithm=CompressionAlgorithm.GZIP, level=6),
        CompressionAlgorithm.SNAPPY: CompressionConfig(algorithm=CompressionAlgorithm.SNAPPY, level=6)
    }
    
    def __init__(self, config: CompressionConfig | None = None):
        """
        Initialize the compressor.
        
        Args:
            config: Compression configuration. Uses defaults if not provided.
        """
        self.config = config or self._DEFAULT_CONFIGS[CompressionAlgorithm.ZSTANDARD]
        self._load_optional_algorithms()
    
    def _load_optional_algorithms(self) -> None:
        """Load optional compression libraries if available."""
        try:
            import zstandard as zstd
            self._ALGORITHMS[CompressionAlgorithm.ZSTANDARD] = {
                "compress": lambda data, config: zstd.compress(data, level=config.level, threads=config.threads),
                "decompress": lambda data, config: zstd.decompress(data, threads=config.threads),
                "available": True
            }
        except ImportError:
            self._ALGORITHMS[CompressionAlgorithm.ZSTANDARD] = {
                "compress": None,
                "decompress": None,
                "available": False
            }
            logger.warning("zstandard library not available. Install with: pip install zstandard")
        
        try:
            import lz4.frame
            self._ALGORITHMS[CompressionAlgorithm.LZ4] = {
                "compress": lambda data, config: lz4.frame.compress(data, compression_level=config.level),
                "decompress": lambda data, config: lz4.frame.decompress(data),
                "available": True
            }
        except ImportError:
            self._ALGORITHMS[CompressionAlgorithm.LZ4] = {
                "compress": None,
                "decompress": None,
                "available": False
            }
            logger.warning("lz4 library not available. Install with: pip install lz4")
        
        try:
            import blosc
            self._ALGORITHMS[CompressionAlgorithm.BLOSC] = {
                "compress": lambda data, config: blosc.compress(
                    data, 
                    typesize=1,  # Byte data
                    cname=config.blosc_cname,
                    clevel=config.level,
                    shuffle=config.blosc_shuffle
                ),
                "decompress": lambda data, config: blosc.decompress(data),
                "available": True
            }
        except ImportError:
            self._ALGORITHMS[CompressionAlgorithm.BLOSC] = {
                "compress": None,
                "decompress": None,
                "available": False
            }
            logger.warning("blosc library not available. Install with: pip install blosc")
        
        try:
            import gzip
            self._ALGORITHMS[CompressionAlgorithm.GZIP] = {
                "compress": lambda data, config: gzip.compress(data, compresslevel=config.level),
                "decompress": lambda data, config: gzip.decompress(data),
                "available": True
            }
        except ImportError:
            self._ALGORITHMS[CompressionAlgorithm.GZIP] = {
                "compress": None,
                "decompress": None,
                "available": False
            }
        
        try:
            import snappy
            self._ALGORITHMS[CompressionAlgorithm.SNAPPY] = {
                "compress": lambda data, config: snappy.compress(data),
                "decompress": lambda data, config: snappy.decompress(data),
                "available": True
            }
        except ImportError:
            self._ALGORITHMS[CompressionAlgorithm.SNAPPY] = {
                "compress": None,
                "decompress": None,
                "available": False
            }
            logger.warning("snappy library not available. Install with: pip install python-snappy")
    
    def is_available(self, algorithm: CompressionAlgorithm) -> bool:
        """Check if a compression algorithm is available."""
        return self._ALGORITHMS[algorithm]["available"]
    
    def get_available_algorithms(self) -> list[CompressionAlgorithm]:
        """Get list of available compression algorithms."""
        return [alg for alg in CompressionAlgorithm if self.is_available(alg)]
    
    def compress(
        self, 
        data: str | bytes,
        algorithm: CompressionAlgorithm | None = None,
        config: CompressionConfig | None = None
    ) -> bytes:
        """
        Compress data using the specified algorithm.
        
        Args:
            data: Data to compress (string or bytes).
            algorithm: Compression algorithm to use. Uses config.algorithm if not specified.
            config: Compression configuration. Uses instance config if not specified.
            
        Returns:
            Compressed data with header.
            
        Raises:
            CompressionError: If compression fails.
        """
        # Use provided config or instance config
        effective_config = config or self.config
        effective_algorithm = algorithm or effective_config.algorithm
        
        # Check if algorithm is available
        if not self.is_available(effective_algorithm):
            raise CompressionError(f"Algorithm {effective_algorithm.value} is not available")
        
        # Convert string to bytes if necessary
        if isinstance(data, str):
            data_bytes = data.encode('utf-8')
        else:
            data_bytes = data
        
        # Get the compression function
        compress_func = self._ALGORITHMS[effective_algorithm]["compress"]
        
        # Create config for this algorithm
        algo_config = CompressionConfig(
            algorithm=effective_algorithm,
            level=effective_config.level,
            zlib_wbits=effective_config.zlib_wbits,
            zstandard_dict_size=effective_config.zstandard_dict_size,
            blosc_cname=effective_config.blosc_cname,
            blosc_shuffle=effective_config.blosc_shuffle
        )
        
        # Compress the data
        try:
            compressed_data = compress_func(data_bytes, algo_config)
        except Exception as e:
            raise CompressionError(f"Compression failed: {e}")
        
        # Create header
        header = self._create_header(
            algorithm=effective_algorithm,
            level=algo_config.level,
            original_size=len(data_bytes),
            data_hash=self._compute_hash(data_bytes)
        )
        
        # Return header + compressed data
        return header + compressed_data
    
    def decompress(
        self, 
        compressed_data: bytes,
        expected_algorithm: CompressionAlgorithm | None = None
    ) -> bytes:
        """
        Decompress data.
        
        Args:
            compressed_data: Compressed data with header.
            expected_algorithm: Expected algorithm (for validation).
            
        Returns:
            Decompressed data.
            
        Raises:
            CompressionError: If decompression fails or header is invalid.
        """
        if len(compressed_data) < HEADER_SIZE:
            raise CompressionError(f"Invalid compressed data: too short ({len(compressed_data)} bytes)")
        
        # Parse header
        header = compressed_data[:HEADER_SIZE]
        algorithm, level, original_size, data_hash = self._parse_header(header)
        
        # Validate algorithm if expected
        if expected_algorithm and algorithm != expected_algorithm:
            raise CompressionError(
                f"Algorithm mismatch: expected {expected_algorithm.value}, got {algorithm.value}"
            )
        
        # Check if algorithm is available
        if not self.is_available(algorithm):
            raise CompressionError(f"Algorithm {algorithm.value} is not available for decompression")
        
        # Get the decompression function
        decompress_func = self._ALGORITHMS[algorithm]["decompress"]
        
        # Create config for this algorithm
        algo_config = CompressionConfig(
            algorithm=algorithm,
            level=level
        )
        
        # Extract compressed data
        actual_compressed_data = compressed_data[HEADER_SIZE:]
        
        # Decompress the data
        try:
            decompressed_data = decompress_func(actual_compressed_data, algo_config)
        except Exception as e:
            raise CompressionError(f"Decompression failed: {e}")
        
        # Validate size
        if len(decompressed_data) != original_size:
            raise CompressionError(
                f"Size mismatch: expected {original_size}, got {len(decompressed_data)}"
            )
        
        # Validate hash
        actual_hash = self._compute_hash(decompressed_data)
        if actual_hash != data_hash:
            raise CompressionError("Data integrity check failed: hash mismatch")
        
        return decompressed_data
    
    def _create_header(
        self, 
        algorithm: CompressionAlgorithm, 
        level: int, 
        original_size: int, 
        data_hash: bytes
    ) -> bytes:
        """Create a compression header."""
        # Pack the header
        # Format: [magic:4][algorithm:1][level:1][reserved:2][original_size:8][hash:32]
        header = struct.pack(
            '<4sBBHQ32s',
            COMPRESSION_MAGIC,
            _ALGO_IDS[algorithm],  # unique algorithm id (not the ambiguous first byte)
            level,
            0,  # Reserved
            original_size,
            data_hash
        )
        return header
    
    def _parse_header(self, header: bytes) -> tuple[CompressionAlgorithm, int, int, bytes]:
        """Parse a compression header."""
        if len(header) != HEADER_SIZE:
            raise CompressionError(f"Invalid header size: {len(header)}")
        
        # Unpack the header
        magic, algo_byte, level, reserved, original_size, data_hash = struct.unpack(
            '<4sBBHQ32s',
            header
        )
        
        # Validate magic
        if magic != COMPRESSION_MAGIC:
            raise CompressionError(f"Invalid magic number: {magic}")
        
        # Convert the unique algorithm id back to a CompressionAlgorithm
        algorithm = _ID_ALGOS.get(algo_byte)
        if algorithm is None:
            raise CompressionError(f"Unknown algorithm id: {algo_byte}")

        return algorithm, level, original_size, data_hash
    
    def _compute_hash(self, data: bytes) -> bytes:
        """Compute SHA-256 hash of data."""
        return hashlib.sha256(data).digest()
    
    def compress_with_stats(
        self, 
        data: str | bytes,
        algorithm: CompressionAlgorithm | None = None,
        config: CompressionConfig | None = None
    ) -> tuple[bytes, CompressionStats]:
        """
        Compress data and return statistics.
        
        Args:
            data: Data to compress.
            algorithm: Compression algorithm to use.
            config: Compression configuration.
            
        Returns:
            Tuple of (compressed_data, stats).
        """
        # Convert string to bytes if necessary
        if isinstance(data, str):
            data_bytes = data.encode('utf-8')
        else:
            data_bytes = data
        
        original_size = len(data_bytes)
        
        # Compress
        start_time = time.time()
        compressed_data = self.compress(data_bytes, algorithm, config)
        compression_time = time.time() - start_time
        
        compressed_size = len(compressed_data)
        compression_ratio = compressed_size / original_size if original_size > 0 else 0
        
        # Decompress to measure decompression time
        start_time = time.time()
        self.decompress(compressed_data)
        decompression_time = time.time() - start_time
        
        # Determine algorithm from compressed data
        effective_algorithm = algorithm or self.config.algorithm
        
        stats = CompressionStats(
            algorithm=effective_algorithm,
            original_size=original_size,
            compressed_size=compressed_size,
            compression_time=compression_time,
            decompression_time=decompression_time,
            compression_ratio=compression_ratio
        )
        
        return compressed_data, stats
    
    def benchmark(
        self, 
        data: str | bytes,
        algorithms: list[CompressionAlgorithm] | None = None
    ) -> list[CompressionStats]:
        """
        Benchmark compression performance across multiple algorithms.
        
        Args:
            data: Data to compress.
            algorithms: List of algorithms to benchmark. Uses all available if not specified.
            
        Returns:
            List of compression statistics for each algorithm.
        """
        if algorithms is None:
            algorithms = self.get_available_algorithms()
        
        results = []
        for algorithm in algorithms:
            try:
                _, stats = self.compress_with_stats(data, algorithm)
                results.append(stats)
            except Exception as e:
                logger.warning(f"Benchmark failed for {algorithm.value}: {e}")
        
        return results
    
    def get_best_algorithm(
        self, 
        data: str | bytes,
        algorithms: list[CompressionAlgorithm] | None = None,
        optimize_for: str = "ratio"  # "ratio", "speed", or "balanced"
    ) -> tuple[CompressionAlgorithm, CompressionStats]:
        """
        Find the best compression algorithm for the given data.
        
        Args:
            data: Data to compress.
            algorithms: List of algorithms to consider.
            optimize_for: Optimization target ("ratio" for best compression, 
                        "speed" for fastest, "balanced" for best ratio/speed tradeoff).
            
        Returns:
            Tuple of (best_algorithm, stats).
        """
        stats_list = self.benchmark(data, algorithms)
        
        if not stats_list:
            raise CompressionError("No algorithms available for benchmarking")
        
        if optimize_for == "ratio":
            # Best compression ratio (smallest compressed size)
            best_stat = min(stats_list, key=lambda x: x.compression_ratio)
        elif optimize_for == "speed":
            # Fastest compression
            best_stat = min(stats_list, key=lambda x: x.compression_time)
        else:  # balanced
            # Best ratio/speed tradeoff (compression ratio / (compression_time + decompression_time))
            best_stat = max(
                stats_list, 
                key=lambda x: x.compression_ratio / (x.compression_time + x.decompression_time + 0.0001)
            )
        
        return best_stat.algorithm, best_stat


# =============================================================================
# Chunked Compression for Large Data
# =============================================================================

class ChunkedCompressor:
    """
    Compress large data in chunks for better memory efficiency.
    
    This is particularly useful for compressing large files or database dumps
    where loading the entire data into memory is not feasible.
    """
    
    def __init__(self, compressor: Compressor | None = None, chunk_size: int = 65536):
        """
        Initialize the chunked compressor.
        
        Args:
            compressor: Compressor instance to use.
            chunk_size: Size of chunks in bytes.
        """
        self.compressor = compressor or Compressor()
        self.chunk_size = chunk_size
    
    def compress_file(
        self, 
        input_path: str | Path,
        output_path: str | Path,
        algorithm: CompressionAlgorithm | None = None
    ) -> CompressionStats:
        """
        Compress a file in chunks.
        
        Args:
            input_path: Path to input file.
            output_path: Path to output compressed file.
            algorithm: Compression algorithm to use.
            
        Returns:
            Compression statistics.
        """
        input_path = Path(input_path)
        output_path = Path(output_path)
        
        total_original_size = 0
        total_compressed_size = 0
        start_time = time.time()
        
        with open(output_path, 'wb') as output_file:
            # Write header placeholder (will be updated later)
            output_file.write(b'\x00' * HEADER_SIZE)
            
            with open(input_path, 'rb') as input_file:
                while True:
                    chunk = input_file.read(self.chunk_size)
                    if not chunk:
                        break
                    
                    total_original_size += len(chunk)
                    
                    # Compress this chunk
                    compressed_chunk = self.compressor.compress(
                        chunk, 
                        algorithm=algorithm,
                        config=CompressionConfig(
                            algorithm=algorithm or self.compressor.config.algorithm,
                            level=self.compressor.config.level,
                            chunk_size=self.chunk_size
                        )
                    )
                    
                    total_compressed_size += len(compressed_chunk)
                    output_file.write(compressed_chunk)
            
            # Seek back and write the actual header
            output_file.seek(0)
            header = self.compressor._create_header(
                algorithm=algorithm or self.compressor.config.algorithm,
                level=self.compressor.config.level,
                original_size=total_original_size,
                data_hash=self._compute_file_hash(input_path)
            )
            output_file.write(header)
        
        compression_time = time.time() - start_time
        compression_ratio = total_compressed_size / total_original_size if total_original_size > 0 else 0
        
        return CompressionStats(
            algorithm=algorithm or self.compressor.config.algorithm,
            original_size=total_original_size,
            compressed_size=total_compressed_size,
            compression_time=compression_time,
            decompression_time=0,  # Will be measured during decompression
            compression_ratio=compression_ratio
        )
    
    def decompress_file(
        self, 
        input_path: str | Path,
        output_path: str | Path
    ) -> CompressionStats:
        """
        Decompress a file in chunks.
        
        Args:
            input_path: Path to input compressed file.
            output_path: Path to output decompressed file.
            
        Returns:
            Compression statistics.
        """
        input_path = Path(input_path)
        output_path = Path(output_path)
        
        start_time = time.time()
        
        with open(input_path, 'rb') as input_file:
            # Read and parse header
            header = input_file.read(HEADER_SIZE)
            algorithm, level, original_size, data_hash = self.compressor._parse_header(header)
            
            with open(output_path, 'wb') as output_file:
                while True:
                    compressed_chunk = input_file.read(self.chunk_size * 2)  # Read larger chunks
                    if not compressed_chunk:
                        break
                    
                    # Decompress this chunk
                    decompressed_chunk = self.compressor.decompress(
                        compressed_chunk,
                        expected_algorithm=algorithm
                    )
                    output_file.write(decompressed_chunk)
        
        decompression_time = time.time() - start_time
        compressed_size = input_path.stat().st_size
        
        # Verify the decompressed file
        actual_hash = self._compute_file_hash(output_path)
        if actual_hash != data_hash:
            raise CompressionError("File integrity check failed after decompression")
        
        return CompressionStats(
            algorithm=algorithm,
            original_size=original_size,
            compressed_size=compressed_size,
            compression_time=0,  # Not measured during decompression
            decompression_time=decompression_time,
            compression_ratio=compressed_size / original_size if original_size > 0 else 0
        )
    
    def _compute_file_hash(self, file_path: str | Path) -> bytes:
        """Compute SHA-256 hash of a file."""
        hasher = hashlib.sha256()
        file_path = Path(file_path)
        
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(self.chunk_size)
                if not chunk:
                    break
                hasher.update(chunk)
        
        return hasher.digest()


# =============================================================================
# Streaming Compression
# =============================================================================

class StreamingCompressor:
    """
    Streaming compressor for handling large data streams.
    """
    
    def __init__(self, compressor: Compressor | None = None):
        """
        Initialize the streaming compressor.
        
        Args:
            compressor: Compressor instance to use.
        """
        self.compressor = compressor or Compressor()
    
    def compress_stream(
        self, 
        input_stream: BinaryIO,
        output_stream: BinaryIO,
        algorithm: CompressionAlgorithm | None = None,
        chunk_size: int = 65536
    ) -> CompressionStats:
        """
        Compress a data stream.
        
        Args:
            input_stream: Input stream to compress.
            output_stream: Output stream for compressed data.
            algorithm: Compression algorithm to use.
            chunk_size: Chunk size for reading.
            
        Returns:
            Compression statistics.
        """
        total_original_size = 0
        total_compressed_size = 0
        start_time = time.time()
        hasher = hashlib.sha256()
        
        # Write header placeholder
        output_stream.write(b'\x00' * HEADER_SIZE)
        
        while True:
            chunk = input_stream.read(chunk_size)
            if not chunk:
                break
            
            total_original_size += len(chunk)
            hasher.update(chunk)
            
            # Compress this chunk
            compressed_chunk = self.compressor.compress(
                chunk, 
                algorithm=algorithm
            )
            
            total_compressed_size += len(compressed_chunk)
            output_stream.write(compressed_chunk)
        
        # Write actual header
        output_stream.seek(0)
        header = self.compressor._create_header(
            algorithm=algorithm or self.compressor.config.algorithm,
            level=self.compressor.config.level,
            original_size=total_original_size,
            data_hash=hasher.digest()
        )
        output_stream.write(header)
        
        compression_time = time.time() - start_time
        compression_ratio = total_compressed_size / total_original_size if total_original_size > 0 else 0
        
        return CompressionStats(
            algorithm=algorithm or self.compressor.config.algorithm,
            original_size=total_original_size,
            compressed_size=total_compressed_size,
            compression_time=compression_time,
            decompression_time=0,
            compression_ratio=compression_ratio
        )
    
    def decompress_stream(
        self, 
        input_stream: BinaryIO,
        output_stream: BinaryIO
    ) -> CompressionStats:
        """
        Decompress a data stream.
        
        Args:
            input_stream: Input stream of compressed data.
            output_stream: Output stream for decompressed data.
            
        Returns:
            Compression statistics.
        """
        start_time = time.time()
        
        # Read and parse header
        header = input_stream.read(HEADER_SIZE)
        algorithm, level, original_size, data_hash = self.compressor._parse_header(header)
        
        hasher = hashlib.sha256()
        total_decompressed_size = 0
        
        while True:
            compressed_chunk = input_stream.read(65536 * 2)
            if not compressed_chunk:
                break
            
            # Decompress this chunk
            decompressed_chunk = self.compressor.decompress(
                compressed_chunk,
                expected_algorithm=algorithm
            )
            
            total_decompressed_size += len(decompressed_chunk)
            output_stream.write(decompressed_chunk)
            hasher.update(decompressed_chunk)
        
        decompression_time = time.time() - start_time
        compressed_size = input_stream.tell() - HEADER_SIZE
        
        # Verify hash
        if hasher.digest() != data_hash:
            raise CompressionError("Stream integrity check failed")
        
        return CompressionStats(
            algorithm=algorithm,
            original_size=original_size,
            compressed_size=compressed_size,
            compression_time=0,
            decompression_time=decompression_time,
            compression_ratio=compressed_size / original_size if original_size > 0 else 0
        )


# =============================================================================
# Database-Specific Compression
# =============================================================================

class DatabaseCompressor:
    """
    Compression utilities specifically for database storage.
    
    This class provides methods for compressing database fields,
    particularly large text fields like article content.
    """
    
    def __init__(self, compressor: Compressor | None = None):
        """
        Initialize the database compressor.
        
        Args:
            compressor: Compressor instance to use.
        """
        self.compressor = compressor or Compressor()
        self._field_configs: dict[str, CompressionConfig] = {}
    
    def set_field_config(self, field_name: str, config: CompressionConfig) -> None:
        """
        Set compression configuration for a specific field.
        
        Args:
            field_name: Name of the database field.
            config: Compression configuration to use.
        """
        self._field_configs[field_name] = config
    
    def compress_field(
        self, 
        field_name: str, 
        value: str | bytes | None
    ) -> bytes | None:
        """
        Compress a database field value.
        
        Args:
            field_name: Name of the field.
            value: Value to compress.
            
        Returns:
            Compressed value, or None if value is None.
        """
        if value is None:
            return None
        
        # Get configuration for this field
        config = self._field_configs.get(field_name, self.compressor.config)
        
        # Use ZSTANDARD for text fields (good compression, fast decompression)
        if isinstance(value, str):
            algorithm = CompressionAlgorithm.ZSTANDARD if self.compressor.is_available(CompressionAlgorithm.ZSTANDARD) else CompressionAlgorithm.ZLIB
        else:
            algorithm = config.algorithm
        
        return self.compressor.compress(value, algorithm=algorithm, config=config)
    
    def decompress_field(
        self, 
        field_name: str, 
        value: bytes | None
    ) -> str | bytes | None:
        """
        Decompress a database field value.
        
        Args:
            field_name: Name of the field.
            value: Compressed value.
            
        Returns:
            Decompressed value, or None if value is None.
        """
        if value is None:
            return None
        
        return self.compressor.decompress(value)
    
    def compress_text_for_storage(self, text: str) -> bytes:
        """
        Compress text for database storage using optimal settings.
        
        Args:
            text: Text to compress.
            
        Returns:
            Compressed text.
        """
        # Use ZSTANDARD if available (best for text), otherwise ZLIB
        algorithm = CompressionAlgorithm.ZSTANDARD if self.compressor.is_available(CompressionAlgorithm.ZSTANDARD) else CompressionAlgorithm.ZLIB
        
        # Use level 6 for good compression/speed balance
        config = CompressionConfig(algorithm=algorithm, level=6)
        
        return self.compressor.compress(text, algorithm=algorithm, config=config)
    
    def decompress_text_from_storage(self, compressed_text: bytes) -> str:
        """
        Decompress text from database storage.
        
        Args:
            compressed_text: Compressed text.
            
        Returns:
            Decompressed text.
        """
        decompressed = self.compressor.decompress(compressed_text)
        return decompressed.decode('utf-8')


# =============================================================================
# Utility Functions
# =============================================================================

def get_compression_algorithm_by_name(name: str) -> CompressionAlgorithm:
    """Get compression algorithm by name."""
    for algorithm in CompressionAlgorithm:
        if algorithm.value.lower() == name.lower():
            return algorithm
    raise ValueError(f"Unknown compression algorithm: {name}")


def create_compressor(algorithm: str = "zstandard", level: int = 6) -> Compressor:
    """Create a compressor with the specified algorithm and level."""
    algo = get_compression_algorithm_by_name(algorithm)
    config = CompressionConfig(algorithm=algo, level=level)
    return Compressor(config)


# =============================================================================
# Default Compressor Instance
# =============================================================================

# Create default compressor (uses ZSTANDARD if available, otherwise ZLIB)
default_compressor = Compressor()

# Create database compressor
database_compressor = DatabaseCompressor()

# Create chunked compressor
chunked_compressor = ChunkedCompressor()

# Create streaming compressor
streaming_compressor = StreamingCompressor()


__all__ = [
    # Algorithm definitions
    'CompressionAlgorithm', 'CompressionConfig', 'CompressionError',
    
    # Statistics
    'CompressionStats',
    
    # Main compressor
    'Compressor',
    
    # Specialized compressors
    'ChunkedCompressor', 'StreamingCompressor', 'DatabaseCompressor',
    
    # Default instances
    'default_compressor', 'database_compressor', 'chunked_compressor', 'streaming_compressor',
    
    # Utility functions
    'get_compression_algorithm_by_name', 'create_compressor',
    
    # Constants
    'COMPRESSION_MAGIC', 'HEADER_SIZE'
]
