"""The synthetic OSM extract, and the offline-map lane end to end without a socket.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1018 = a: "a synthetic wiki edition, a synthetic OSM extract and a synthetic
jurisdiction in ``tests/fixtures/``, so every lane's pipeline runs end-to-end in CI
without a socket". This is the OSM third (S04-08's S5). The lane today is: the
download manager writes a Geofabrik ``.osm.pbf`` to disk, and the in-browser reader
turns it into country areas for the map. Both halves run here, chained through the
file the manager actually wrote, with the airplane socket guard installed and every
name resolution counted.

The refusal half, a download started or running under airplane mode being paused and
NAMED as airplane mode, is ``tests/test_download_paused_by.py``.
"""

from __future__ import annotations

import hashlib
import socket
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE = _ROOT / "tests" / "fixtures" / "osm" / "synthetic.osm.pbf"
_GENERATOR = _ROOT / "scripts" / "make_osm_fixture.py"
_NOTE = _ROOT / "tests" / "fixtures" / "osm" / "PROVENANCE.md"


def _read_with_node(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", str(_ROOT / "tests" / "osm_extract_node_test.js"), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_fixture_is_exactly_what_its_generator_produces(tmp_path):
    out = tmp_path / "synthetic.osm.pbf"
    proc = subprocess.run(
        [sys.executable, str(_GENERATOR), "--out", str(out)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert out.read_bytes() == _FIXTURE.read_bytes(), (
        "the committed fixture is not what the generator produces; regenerate it"
    )


def test_the_PROVENANCE_note_records_the_digest_the_file_actually_has():
    note = _NOTE.read_text(encoding="utf-8")
    data = _FIXTURE.read_bytes()
    assert hashlib.sha256(data).hexdigest() in note, "PROVENANCE.md carries a stale digest"
    assert f"bytes   {len(data)}" in note, "PROVENANCE.md carries a stale size"


def test_the_reader_decodes_the_committed_fixture():
    proc = _read_with_node(_FIXTURE)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


class _Resp:
    status_code = 200

    def __init__(self, body: bytes):
        self._body = body
        self.headers = {"Content-Length": str(len(body))}

    def raise_for_status(self):
        pass

    def iter_content(self, _chunk):
        yield self._body


def test_download_then_read_resolves_ZERO_names_with_the_socket_guard_installed(
    tmp_path, monkeypatch
):
    """The lane end to end: the manager's own download loop writes the file, the reader
    reads THAT file, and no name is resolved on the way. A DNS lookup is egress, so the
    count is of resolutions, not of requests."""
    from src.geo.osm_downloads import OsmDownloadManager
    from src.ingest import clear_kill_switch
    from src.ingest.airplane import install_airplane_socket_guard

    clear_kill_switch()
    install_airplane_socket_guard()
    seen: list[tuple] = []
    real = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: (seen.append(a), real(*a, **k))[1])

    body = _FIXTURE.read_bytes()
    asked: list[str] = []
    mgr = OsmDownloadManager(
        base_dir=tmp_path, http_get=lambda url, _h: (asked.append(url), _Resp(body))[1]
    )
    mgr.start("europe")
    for _ in range(250):
        entry = mgr.list()[0]
        if entry["status"] in ("done", "error"):
            break
        time.sleep(0.02)
    assert entry["status"] == "done", entry
    assert asked, "the download loop never asked for the file"
    written = Path(entry["dest"])
    assert written.read_bytes() == body, "the manager wrote something other than it was served"
    assert seen == [], f"the download resolved {len(seen)} name(s): {seen}"

    proc = _read_with_node(written)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout
