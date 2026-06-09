"""Compressed-text storage must never 500 the corpus over a codec quirk.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Regression: the zstandard codec was called as ``zstd.compress(data, threads=…)``,
but python-zstandard only takes ``threads`` on the ZstdCompressor class — so storing
a large compressed field (e.g. a 300 KB Wikipedia baseline) raised CompressionError
and 500'd the write. The fix uses the class API and, as a floor, falls back to zlib
if any codec raises so a journalist's corpus is never blocked.
"""

import inspect

import src.utils.compression as C
from src.utils.compression import CompressionAlgorithm as Algo
from src.utils.compression import CompressionError


def _storage():
    klass = next(
        o for _, o in inspect.getmembers(C, inspect.isclass)
        if hasattr(o, "compress_text_for_storage") and hasattr(o, "decompress_text_from_storage")
    )
    return klass()


def test_large_unicode_text_round_trips():
    w = _storage()
    text = "Climate change — βaseline ✓ " * 20000
    blob = w.compress_text_for_storage(text)
    assert isinstance(blob, (bytes, bytearray))
    assert w.decompress_text_from_storage(blob) == text


def test_storage_falls_back_to_zlib_when_a_codec_raises():
    """A broken-but-'available' codec (the zstandard threads bug) must not 500 storage."""
    w = _storage()
    text = "tamper-evident corpus " * 5000
    w.compressor._ALGORITHMS[Algo.ZSTANDARD] = {
        "compress": lambda data, config: (_ for _ in ()).throw(CompressionError("threads boom")),
        "decompress": lambda data, config: data,
        "available": True,
    }
    blob = w.compress_text_for_storage(text)          # must succeed via zlib, not raise
    assert w.decompress_text_from_storage(blob) == text
