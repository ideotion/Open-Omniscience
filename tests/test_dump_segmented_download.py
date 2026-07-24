"""
C11 (2026-07-24 throughput brief, S-C): the segmented-download + mirror-ranking
wiring INSIDE ``DumpDownloadManager`` — the consumer-level tests (the pure
mechanism itself is covered by ``tests/test_segmented_download.py``).

Covers: a fresh download with an ``expected_sha256`` set engages the segmented
path and reassembles byte-identically to disk; a resumed (partial-file) download
NEVER engages segmentation even with a checksum set (falls to the proven
sequential Range path); a mirror is chosen via the injected probe and used for
BOTH the segmented and sequential paths; a corrupt segmented download is
recorded as a genuine ``error`` (never silently downgraded to a fallback
"success"); every entry with the C11 fields left at their defaults (mirrors=[],
expected_sha256="") behaves BYTE-IDENTICALLY to the pre-C11 sequential path.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.wiki.dumps import DumpDownloadManager

PAYLOAD = b"segmented-dump-fixture-" * 100  # a few KB
PAYLOAD_SHA256 = hashlib.sha256(PAYLOAD).hexdigest()


class _HeadResp:
    def __init__(self, length: int):
        self.headers = {"Content-Length": str(length)}

    def raise_for_status(self):
        return None


def _fetch_segment(payload: bytes, calls: list | None = None):
    def _fetch(url: str, start: int, end: int) -> bytes:
        if calls is not None:
            calls.append((url, start, end))
        return payload[start:end]

    return _fetch


def _no_probe(url: str) -> dict:
    return {"ok": True, "latency_ms": 10.0}


def test_fresh_download_with_a_checksum_uses_the_segmented_path(tmp_path):
    calls: list = []
    m = DumpDownloadManager(
        base_dir=tmp_path,
        http_head=lambda url: _HeadResp(len(PAYLOAD)),
        fetch_segment=_fetch_segment(PAYLOAD, calls=calls),
        mirror_probe=_no_probe,
        segment_min_bytes=100,  # PAYLOAD is a tiny fixture; the real default is 1 MiB
    )
    entry = m._entry_for("en", "pages-articles", expected_sha256=PAYLOAD_SHA256)
    res = m._download(entry)
    assert res.status == "done"
    assert Path(res.dest).read_bytes() == PAYLOAD
    assert calls, "the segmented fetch_segment must have been invoked"
    assert len({(s, e) for _u, s, e in calls}) >= 2, "must actually split into segments"


def test_expected_sha256_absent_never_engages_segmentation(tmp_path):
    """The default (byte-identical) case: no checksum configured -> the
    sequential path runs unchanged, fetch_segment is never called."""
    calls: list = []

    class _Resp:
        def __init__(self):
            self.status_code = 200
            self.headers = {"Content-Length": str(len(PAYLOAD))}

        def raise_for_status(self):
            return None

        def iter_content(self, _n):
            yield PAYLOAD

    m = DumpDownloadManager(
        base_dir=tmp_path,
        http_get=lambda url, headers: _Resp(),
        fetch_segment=_fetch_segment(PAYLOAD, calls=calls),
    )
    entry = m._entry_for("en", "pages-articles")  # no expected_sha256 -> default ""
    assert entry.expected_sha256 == "" and entry.mirrors == []
    res = m._download(entry)
    assert res.status == "done"
    assert Path(res.dest).read_bytes() == PAYLOAD
    assert calls == [], "fetch_segment must never be called when expected_sha256 is empty"


def test_a_resumed_partial_file_never_engages_segmentation_even_with_a_checksum(tmp_path):
    """Segmented+resume is out of scope: a partial file on disk always falls
    to the sequential Range-resume path, regardless of expected_sha256."""
    calls: list = []
    m = DumpDownloadManager(
        base_dir=tmp_path,
        http_head=lambda url: _HeadResp(len(PAYLOAD)),
        fetch_segment=_fetch_segment(PAYLOAD, calls=calls),
    )
    entry = m._entry_for("en", "pages-articles", expected_sha256=PAYLOAD_SHA256)
    Path(entry.dest).write_bytes(PAYLOAD[:10])  # a partial file already exists

    class _PartialResp:
        def __init__(self):
            self.status_code = 206
            self.headers = {"Content-Length": str(len(PAYLOAD) - 10)}

        def raise_for_status(self):
            return None

        def iter_content(self, _n):
            yield PAYLOAD[10:]

    m._http_get = lambda url, headers: _PartialResp()
    res = m._download(entry)
    assert res.status == "done"
    assert Path(res.dest).read_bytes() == PAYLOAD
    assert calls == [], "a resumed download must never take the segmented path"


def test_a_mirror_is_selected_and_used_for_the_fetch(tmp_path):
    canonical_calls: list = []
    mirror_calls: list = []

    def probe(url):
        return {"ok": True, "latency_ms": 900.0 if "wikimedia" in url else 10.0}

    class _Resp:
        def __init__(self):
            self.status_code = 200
            self.headers = {"Content-Length": str(len(PAYLOAD))}

        def raise_for_status(self):
            return None

        def iter_content(self, _n):
            yield PAYLOAD

    def http_get(url, headers):
        (canonical_calls if "wikimedia" in url else mirror_calls).append(url)
        return _Resp()

    m = DumpDownloadManager(base_dir=tmp_path, http_get=http_get, mirror_probe=probe)
    entry = m._entry_for("en", "pages-articles", mirrors=["https://faster-mirror.example/x.bz2"])
    res = m._download(entry)
    assert res.status == "done"
    assert mirror_calls and not canonical_calls, "the faster mirror must be used, not the canonical URL"


def test_a_corrupt_segmented_download_is_recorded_as_a_genuine_error(tmp_path):
    """A tampered/corrupt segment must surface as entry.status == 'error' —
    never a silently-downgraded fallback 'success' that could mask a tampered
    fetch over an untrusted mirror/exit node."""
    tampered = bytearray(PAYLOAD)
    tampered[0:4] = b"XXXX"

    def fetch_segment(url, start, end):
        return bytes(tampered[start:end])

    m = DumpDownloadManager(
        base_dir=tmp_path,
        http_head=lambda url: _HeadResp(len(PAYLOAD)),
        fetch_segment=fetch_segment,
        segment_min_bytes=100,
    )
    entry = m._entry_for("en", "pages-articles", expected_sha256=PAYLOAD_SHA256)
    res = m._download(entry)
    assert res.status == "error"
    assert res.error and "checksum" in res.error.lower()
    # The dest file must NOT exist / must not be silently accepted as complete.
    assert not Path(res.dest).exists() or Path(res.dest).read_bytes() != bytes(tampered)


def test_start_seeds_mirrors_and_checksum_only_on_a_new_entry(tmp_path):
    m = DumpDownloadManager(base_dir=tmp_path)
    m.start("en", "pages-articles", mirrors=["https://m.example/a.bz2"], expected_sha256="abc123")
    e = m._entries["en:pages-articles"]
    assert e.mirrors == ["https://m.example/a.bz2"]
    assert e.expected_sha256 == "abc123"
    # A later call (e.g. a resume-style re-start) must NOT overwrite the
    # already-seeded values with the caller's (possibly default/empty) ones.
    m._entry_for("en", "pages-articles", mirrors=[], expected_sha256="")
    e2 = m._entries["en:pages-articles"]
    assert e2.mirrors == ["https://m.example/a.bz2"]
    assert e2.expected_sha256 == "abc123"
