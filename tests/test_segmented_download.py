"""
C11 (2026-07-24 throughput brief, S-C): the segmented multi-circuit download
wiring over ``src.ingest.tor_throughput``'s pure cores.

Covers: byte-identical reassembly of a fixture split across segments, each
segment fetched with a DISTINCT (start, end) request (proving no duplicate/
missing work); the mandatory-integrity refusal (a corrupt/short segment,
already ``reassemble``'s own contract, PROPAGATES — never silently downgraded
to a fallback "success"); the bounded-RAM size gate; the no-checksum /
too-small-to-segment declines (return None, caller falls back); and
``choose_mirror``'s latency-based pick, unreachable-degrades-to-canonical,
empty-mirrors no-op, and probe-exception-reads-as-unreachable behaviour.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib

import pytest

from src.ingest.segmented_download import choose_mirror, segmented_fetch

PAYLOAD = b"0123456789" * 200  # 2000 bytes -- plenty to split into >= 2 segments
PAYLOAD_SHA256 = hashlib.sha256(PAYLOAD).hexdigest()


def _make_fetch_segment(payload: bytes, *, calls: list | None = None):
    def _fetch(url: str, start: int, end: int) -> bytes:
        if calls is not None:
            calls.append((url, start, end))
        return payload[start:end]

    return _fetch


# --------------------------------------------------------------------------- #
# segmented_fetch: happy path + no-engage declines.
# --------------------------------------------------------------------------- #


def test_segmented_fetch_reassembles_byte_identically():
    calls: list = []
    out = segmented_fetch(
        "https://example.test/big.bin",
        total_bytes=len(PAYLOAD),
        expected_sha256=PAYLOAD_SHA256,
        fetch_segment=_make_fetch_segment(PAYLOAD, calls=calls),
        n_segments=4,
        max_bytes=10_000,
        min_seg=100,  # PAYLOAD is a tiny fixture; the real default (1 MiB) is for real files
    )
    assert out == PAYLOAD
    # Every requested range is DISTINCT and non-overlapping (no duplicate work,
    # no gap) -- the exact contract plan_segments already guarantees, asserted
    # here at the wiring level.
    ranges = sorted((s, e) for _url, s, e in calls)
    assert len(ranges) == len(set(ranges)) >= 2
    covered = sum(e - s for s, e in ranges)
    assert covered == len(PAYLOAD)


def test_segmented_fetch_uses_the_url_for_every_segment_request():
    calls: list = []
    url = "https://mirror.example.test/artifact.bin"
    segmented_fetch(
        url,
        total_bytes=len(PAYLOAD),
        expected_sha256=PAYLOAD_SHA256,
        fetch_segment=_make_fetch_segment(PAYLOAD, calls=calls),
        n_segments=3,
        max_bytes=10_000,
        min_seg=100,
    )
    assert all(u == url for u, _s, _e in calls)


def test_segmented_fetch_declines_without_a_checksum():
    out = segmented_fetch(
        "https://example.test/big.bin",
        total_bytes=len(PAYLOAD),
        expected_sha256="",
        fetch_segment=_make_fetch_segment(PAYLOAD),
        max_bytes=10_000,
    )
    assert out is None


def test_segmented_fetch_declines_above_the_size_ceiling():
    out = segmented_fetch(
        "https://example.test/huge.bin",
        total_bytes=10_000_000,
        expected_sha256="deadbeef",
        fetch_segment=_make_fetch_segment(PAYLOAD),
        max_bytes=1_000_000,  # ceiling well below total_bytes
    )
    assert out is None


def test_segmented_fetch_declines_a_non_positive_total():
    out = segmented_fetch(
        "https://example.test/x.bin",
        total_bytes=0,
        expected_sha256=PAYLOAD_SHA256,
        fetch_segment=_make_fetch_segment(PAYLOAD),
    )
    assert out is None


def test_segmented_fetch_declines_a_file_too_small_to_split():
    tiny = b"hi"
    out = segmented_fetch(
        "https://example.test/tiny.bin",
        total_bytes=len(tiny),
        expected_sha256=hashlib.sha256(tiny).hexdigest(),
        fetch_segment=_make_fetch_segment(tiny),
        n_segments=4,
        min_seg=1024 * 1024,  # forces plan_segments -> a single whole-file segment
        max_bytes=10_000,
    )
    assert out is None  # < 2 segments -- not worth the parallel machinery


# --------------------------------------------------------------------------- #
# segmented_fetch: mandatory-integrity refusal propagates (never a silent
# fallback "success" — a corrupt/short segment must surface as a real defect).
# --------------------------------------------------------------------------- #


def test_a_corrupt_segment_raises_never_silently_falls_back():
    tampered = bytearray(PAYLOAD)
    tampered[0:4] = b"XXXX"  # flips content without changing length

    def fetch_segment(url: str, start: int, end: int) -> bytes:
        return bytes(tampered[start:end])

    with pytest.raises(ValueError, match="checksum mismatch"):
        segmented_fetch(
            "https://example.test/big.bin",
            total_bytes=len(PAYLOAD),
            expected_sha256=PAYLOAD_SHA256,  # the ORIGINAL (untampered) checksum
            fetch_segment=fetch_segment,
            n_segments=4,
            max_bytes=10_000,
            min_seg=100,
        )


def test_a_short_segment_raises_never_silently_falls_back():
    def fetch_segment(url: str, start: int, end: int) -> bytes:
        return PAYLOAD[start:end][:-1]  # truncate every segment by one byte

    with pytest.raises(ValueError):
        segmented_fetch(
            "https://example.test/big.bin",
            total_bytes=len(PAYLOAD),
            expected_sha256=PAYLOAD_SHA256,
            fetch_segment=fetch_segment,
            n_segments=4,
            max_bytes=10_000,
            min_seg=100,
        )


def test_a_segment_fetch_exception_propagates():
    def fetch_segment(url: str, start: int, end: int) -> bytes:
        raise OSError("connection reset")

    with pytest.raises(OSError, match="connection reset"):
        segmented_fetch(
            "https://example.test/big.bin",
            total_bytes=len(PAYLOAD),
            expected_sha256=PAYLOAD_SHA256,
            fetch_segment=fetch_segment,
            n_segments=4,
            max_bytes=10_000,
            min_seg=100,
        )


# --------------------------------------------------------------------------- #
# choose_mirror.
# --------------------------------------------------------------------------- #


def test_choose_mirror_returns_canonical_unchanged_when_no_mirrors():
    def probe(url):
        raise AssertionError("must never probe when mirrors is empty")

    picked = choose_mirror("https://canonical.example/a.bin", [], probe=probe)
    assert picked == "https://canonical.example/a.bin"


def test_choose_mirror_picks_the_lowest_latency_reachable_candidate():
    latencies = {
        "https://canonical.example/a.bin": 900.0,
        "https://mirror-a.example/a.bin": 100.0,
        "https://mirror-b.example/a.bin": 500.0,
    }

    def probe(url):
        return {"ok": True, "latency_ms": latencies[url]}

    picked = choose_mirror(
        "https://canonical.example/a.bin",
        ["https://mirror-a.example/a.bin", "https://mirror-b.example/a.bin"],
        probe=probe,
    )
    assert picked == "https://mirror-a.example/a.bin"


def test_choose_mirror_degrades_to_canonical_when_every_candidate_unreachable():
    def probe(url):
        return {"ok": False, "latency_ms": None}

    picked = choose_mirror(
        "https://canonical.example/a.bin",
        ["https://mirror-a.example/a.bin", "https://mirror-b.example/a.bin"],
        probe=probe,
    )
    assert picked == "https://canonical.example/a.bin"


def test_choose_mirror_skips_an_unreachable_mirror_in_favour_of_a_reachable_one():
    def probe(url):
        if "mirror-a" in url:
            return {"ok": False, "latency_ms": None}
        if "mirror-b" in url:
            return {"ok": True, "latency_ms": 50.0}
        return {"ok": True, "latency_ms": 900.0}  # canonical: reachable but slow

    picked = choose_mirror(
        "https://canonical.example/a.bin",
        ["https://mirror-a.example/a.bin", "https://mirror-b.example/a.bin"],
        probe=probe,
    )
    assert picked == "https://mirror-b.example/a.bin"


def test_choose_mirror_treats_a_probe_exception_as_unreachable_not_a_crash():
    def probe(url):
        if "mirror-a" in url:
            raise TimeoutError("no route")
        if "mirror-b" in url:
            return {"ok": True, "latency_ms": 42.0}
        return {"ok": True, "latency_ms": 900.0}  # canonical: reachable but slow

    picked = choose_mirror(
        "https://canonical.example/a.bin",
        ["https://mirror-a.example/a.bin", "https://mirror-b.example/a.bin"],
        probe=probe,
    )
    assert picked == "https://mirror-b.example/a.bin"
