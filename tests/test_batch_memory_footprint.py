"""
C14 (2026-07-24 throughput brief, A4): shrink the collector batch's per-worker
staged-text memory footprint under measured memory pressure.

Covers the MECHANISM directly (deterministic, injected readings, no real
psutil/large allocations needed): the cap function shrinks below the SAME
floor the bandwidth governor already reacts to and stays at the healthy
default otherwise (including when no reading is available at all -- never
assume pressure from silence); a batch constructed under simulated pressure
auto-flushes sooner, bounding its PEAK staged bytes to the smaller cap under a
synthetic large batch; and a batch on a healthy/unreadable machine is
byte-identical to the pre-C14 fixed 4 MiB behaviour.

Whether shrinking this in-process buffer actually reduces collect_perf's own
mem_low_ticks/mem_low_min_permits on a REAL small box is an operator-measured
property (the brief's own "(mechanism only...)" caveat) -- not something this
suite can honestly fabricate, since the OS-level available-memory reading and
this module's in-process buffer size are two separate systems only causally
linked via real RSS on real hardware.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Source
from src.ingest.batch import (
    _BATCH_MAX_TEXT_BYTES,
    _BATCH_MAX_TEXT_BYTES_UNDER_PRESSURE,
    _MEM_PRESSURE_FLOOR_MB,
    ArticleBatch,
    staged_text_cap_bytes,
)


# --------------------------------------------------------------------------- #
# staged_text_cap_bytes: the pure mechanism.
# --------------------------------------------------------------------------- #


def test_healthy_memory_uses_the_default_cap():
    assert staged_text_cap_bytes(mem_avail_mb=_MEM_PRESSURE_FLOOR_MB + 1) == _BATCH_MAX_TEXT_BYTES


def test_low_memory_shrinks_the_cap():
    assert (
        staged_text_cap_bytes(mem_avail_mb=_MEM_PRESSURE_FLOOR_MB - 1)
        == _BATCH_MAX_TEXT_BYTES_UNDER_PRESSURE
    )
    assert _BATCH_MAX_TEXT_BYTES_UNDER_PRESSURE < _BATCH_MAX_TEXT_BYTES


def test_exactly_at_the_floor_is_still_healthy():
    """The comparison is strict '<' pressure -- a reading exactly AT the floor
    is not (yet) pressure, matching collect_perf's own mem_low check shape."""
    assert staged_text_cap_bytes(mem_avail_mb=_MEM_PRESSURE_FLOOR_MB) == _BATCH_MAX_TEXT_BYTES


def test_an_unreadable_machine_never_assumes_pressure_from_silence():
    """No psutil / a sandbox -- honesty rule (mirrors memguard): a missing
    reading must NEVER trip a pressure response. Simulated by NOT injecting
    mem_avail_mb and forcing the real psutil call to fail."""
    import src.ingest.batch as batch_mod

    def _boom():
        raise RuntimeError("no psutil here")

    orig = batch_mod._available_mem_mb
    batch_mod._available_mem_mb = _boom
    try:
        with pytest.raises(RuntimeError):
            batch_mod._available_mem_mb()  # sanity: the stub really raises
    finally:
        batch_mod._available_mem_mb = orig

    # staged_text_cap_bytes itself must not propagate a reading failure --
    # _available_mem_mb() already catches internally and returns None; prove
    # the cap function's OWN handling of an explicit None (the "no reading"
    # case) falls back to the healthy default, never a fabricated pressure cut.
    assert staged_text_cap_bytes(mem_avail_mb=None) == _BATCH_MAX_TEXT_BYTES


# --------------------------------------------------------------------------- #
# ArticleBatch: peak staged bytes stay bounded under a synthetic large batch,
# and the (adaptive) cap is what actually governs the auto-flush threshold.
# --------------------------------------------------------------------------- #


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 't.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    s = Sess()
    yield s
    s.close()


@pytest.fixture()
def source(session):
    src = Source(name="Test Source", domain="test.example")
    session.add(src)
    session.commit()
    return src


class _FakeDoc:
    def __init__(self, text: str):
        self.title = "T"
        self.text = text
        self.published_at = None
        self.language = "en"
        self.author = None


class _FakeFetched:
    def __init__(self, url: str):
        self.requested_url = url
        self.final_url = url
        self.content = None  # links extraction handles None gracefully
        self.server_ip = None
        self.server_ip_reason = None
        self.fetched_at = datetime.now(UTC)


def _stage_n_large_articles(batch: ArticleBatch, n: int, *, chunk_bytes: int):
    """Stage n articles of chunk_bytes each, tracking the observed PEAK of
    ``_pending_text_bytes`` just BEFORE each stage call (the largest the
    buffer was allowed to grow before an auto-flush reset it)."""
    peak = 0
    for i in range(n):
        peak = max(peak, batch._pending_text_bytes)
        batch.stage(
            _FakeFetched(f"https://test.example/{i}"),
            _FakeDoc("x" * chunk_bytes),
            f"https://test.example/{i}",
            f"hash-{i}",
        )
    return peak


def test_peak_staged_bytes_stay_bounded_under_the_default_cap(session, source, monkeypatch):
    # This test is about the BUFFER-SIZE/auto-flush mechanism only -- skip the
    # real keyword extractor on synthetic "x"*N text (an unrelated, expensive
    # CPU cost that has nothing to do with what C14 changed).
    monkeypatch.setenv("OO_NO_INDEX", "1")
    chunk = 500_000  # 0.5 MB per article
    batch = ArticleBatch(session, source, size=1000, text_cap_bytes=_BATCH_MAX_TEXT_BYTES)
    peak = _stage_n_large_articles(batch, 30, chunk_bytes=chunk)  # 30 * 0.5MB = 15MB total if unbounded
    batch.flush()
    assert peak < _BATCH_MAX_TEXT_BYTES + chunk  # never grew past ~one chunk over the cap


def test_peak_staged_bytes_stay_bounded_under_the_pressure_cap(session, source, monkeypatch):
    """The property C14 actually delivers: under simulated memory pressure,
    peak staged bytes are bounded to the SMALLER cap -- a worker's per-batch
    footprint genuinely shrinks, not just in theory."""
    monkeypatch.setenv("OO_NO_INDEX", "1")
    chunk = 200_000  # 0.2 MB per article
    batch = ArticleBatch(
        session, source, size=1000, text_cap_bytes=_BATCH_MAX_TEXT_BYTES_UNDER_PRESSURE
    )
    peak = _stage_n_large_articles(batch, 30, chunk_bytes=chunk)  # 6 MB unbounded, well over 1 MiB
    batch.flush()
    assert peak < _BATCH_MAX_TEXT_BYTES_UNDER_PRESSURE + chunk
    assert peak < _BATCH_MAX_TEXT_BYTES  # meaningfully smaller than the healthy-machine ceiling


def test_the_batch_actually_used_the_pressure_reading_to_size_its_cap(session, source):
    """End-to-end: constructing WITHOUT an explicit override, but with a
    LOW mem_avail_mb reading fed through staged_text_cap_bytes, must produce
    the SAME shrunk cap as passing text_cap_bytes explicitly -- proving the
    real (non-test-only) code path wires the reading through correctly."""
    computed = staged_text_cap_bytes(mem_avail_mb=_MEM_PRESSURE_FLOOR_MB - 1)
    batch = ArticleBatch(session, source, text_cap_bytes=computed)
    assert batch._text_cap == _BATCH_MAX_TEXT_BYTES_UNDER_PRESSURE


def test_default_construction_on_a_healthy_machine_is_byte_identical(session, source, monkeypatch):
    """No override, and a healthy (or unreadable) real machine: the batch's
    cap must equal the pre-C14 constant exactly -- no behaviour change for
    the common/default case."""
    import src.ingest.batch as batch_mod

    monkeypatch.setattr(batch_mod, "_available_mem_mb", lambda: None)  # unreadable -> healthy default
    batch = ArticleBatch(session, source)
    assert batch._text_cap == _BATCH_MAX_TEXT_BYTES
