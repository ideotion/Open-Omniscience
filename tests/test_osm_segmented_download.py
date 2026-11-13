"""
C11 (2026-07-24 throughput brief, S-C): the segmented-download + mirror-ranking
wiring INSIDE ``OsmDownloadManager`` — the OSM-side consumer-level tests
(mirrors ``tests/test_dump_segmented_download.py``; the pure mechanism itself
is covered by ``tests/test_segmented_download.py``).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.geo.osm_downloads import OsmDownloadManager

PAYLOAD = b"segmented-osm-extract-fixture-" * 100
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


def test_fresh_download_with_a_checksum_uses_the_segmented_path(tmp_path):
    calls: list = []
    m = OsmDownloadManager(
        base_dir=tmp_path,
        http_head=lambda url: _HeadResp(len(PAYLOAD)),
        fetch_segment=_fetch_segment(PAYLOAD, calls=calls),
        segment_min_bytes=100,
    )
    entry = m._entry_for("liechtenstein", expected_sha256=PAYLOAD_SHA256)
    res = m._download(entry)
    assert res.status == "done"
    assert Path(res.dest).read_bytes() == PAYLOAD
    assert calls
    assert len({(s, e) for _u, s, e in calls}) >= 2


def test_expected_sha256_absent_never_engages_segmentation(tmp_path):
    calls: list = []

    class _Resp:
        def __init__(self):
            self.status_code = 200
            self.headers = {"Content-Length": str(len(PAYLOAD))}

        def raise_for_status(self):
            return None

        def iter_content(self, _n):
            yield PAYLOAD

    m = OsmDownloadManager(
        base_dir=tmp_path,
        http_get=lambda url, headers: _Resp(),
        fetch_segment=_fetch_segment(PAYLOAD, calls=calls),
    )
    entry = m._entry_for("liechtenstein")
    assert entry.expected_sha256 == "" and entry.mirrors == []
    res = m._download(entry)
    assert res.status == "done"
    assert Path(res.dest).read_bytes() == PAYLOAD
    assert calls == []


def test_a_mirror_is_selected_and_used_for_the_fetch(tmp_path):
    geofabrik_calls: list = []
    mirror_calls: list = []

    def probe(url):
        return {"ok": True, "latency_ms": 900.0 if "geofabrik" in url else 10.0}

    class _Resp:
        def __init__(self):
            self.status_code = 200
            self.headers = {"Content-Length": str(len(PAYLOAD))}

        def raise_for_status(self):
            return None

        def iter_content(self, _n):
            yield PAYLOAD

    def http_get(url, headers):
        (geofabrik_calls if "geofabrik" in url else mirror_calls).append(url)
        return _Resp()

    m = OsmDownloadManager(base_dir=tmp_path, http_get=http_get, mirror_probe=probe)
    entry = m._entry_for("liechtenstein", mirrors=["https://faster-osm-mirror.example/x.pbf"])
    res = m._download(entry)
    assert res.status == "done"
    assert mirror_calls and not geofabrik_calls


def test_a_corrupt_segmented_download_is_recorded_as_a_genuine_error(tmp_path):
    tampered = bytearray(PAYLOAD)
    tampered[0:4] = b"XXXX"

    def fetch_segment(url, start, end):
        return bytes(tampered[start:end])

    m = OsmDownloadManager(
        base_dir=tmp_path,
        http_head=lambda url: _HeadResp(len(PAYLOAD)),
        fetch_segment=fetch_segment,
        segment_min_bytes=100,
    )
    entry = m._entry_for("liechtenstein", expected_sha256=PAYLOAD_SHA256)
    res = m._download(entry)
    assert res.status == "error"
    assert res.error and "checksum" in res.error.lower()


def test_the_segmented_write_lands_beside_the_final_name_and_is_renamed_over_it(tmp_path, monkeypatch):
    """Audit P15: a crash mid-write must leave nothing at the final name, which a later start would resume from as a valid prefix."""
    import os as _os

    import src.geo.osm_downloads as od

    m = OsmDownloadManager(
        base_dir=tmp_path,
        http_head=lambda url: _HeadResp(len(PAYLOAD)),
        fetch_segment=_fetch_segment(PAYLOAD),
        segment_min_bytes=100,
    )
    entry = m._entry_for("liechtenstein", expected_sha256=PAYLOAD_SHA256)
    seen: list = []
    real_replace = _os.replace   # the module's ``os`` IS the process's: keep the real one before patching it

    def _replace(src, dst):
        seen.append((Path(src).name, Path(dst).name, Path(dst).exists()))
        real_replace(src, dst)

    monkeypatch.setattr(od.os, "replace", _replace)
    assert m._download(entry).status == "done"
    final = Path(entry.dest)
    mine = [r for r in seen if r[1] == final.name]   # the state file has its own atomic rename; only the extract's is asked about
    assert mine == [(final.name + ".segmented-part", final.name, False)], "the extract was written straight to its final name"
    assert final.read_bytes() == PAYLOAD and not (final.parent / (final.name + ".segmented-part")).exists()
