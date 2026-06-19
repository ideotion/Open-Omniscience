"""Downloads honour airplane mode (field test 2026-06-19, #36/#41, THEME-6).

Two bugs: (1) a wiki/OSM download started before airplane kept reading from its
open socket after the kill switch engaged — the chunk loop checked only the per-
download Pause event, not the kill switch; (2) resuming a download in airplane mode
hit the guarded fetcher and surfaced a cryptic "error". Both are fixed: the chunk
loop pauses (resumable) when airplane engages mid-download, and start()/resume in
airplane presents PAUSED (resumable), never an error. The UI's resume re-prompts the
go-online consent before calling start() again.
"""

from __future__ import annotations

import threading
import time

import pytest

from src.ingest import activate_kill_switch, clear_kill_switch


class _GatedResp:
    status_code = 200
    headers = {"Content-Length": "30"}

    def __init__(self, gate: threading.Event):
        self._gate = gate

    def raise_for_status(self):
        pass

    def iter_content(self, _chunk):
        for _ in range(3):
            self._gate.wait(5)  # block until the test lets the next chunk through
            yield b"0123456789"


def _wait_until(predicate, tries=200, delay=0.02):
    for _ in range(tries):
        if predicate():
            return True
        time.sleep(delay)
    return False


@pytest.fixture(autouse=True)
def _clean_kill_switch():
    clear_kill_switch()
    yield
    clear_kill_switch()


def test_dump_start_in_airplane_is_paused_not_error_and_opens_no_socket(tmp_path):
    from src.wiki.dumps import DumpDownloadManager

    calls = []
    mgr = DumpDownloadManager(
        base_dir=tmp_path,
        http_get=lambda u, h: calls.append(u) or _GatedResp(threading.Event()),
        max_concurrent=1,
    )
    activate_kill_switch()
    out = mgr.start("en")
    assert out["status"] == "paused"  # never "error"
    assert not out.get("error")
    assert calls == [], "airplane mode must not open a socket for a download"
    # No worker thread spawned.
    assert not any(t.is_alive() for t in mgr._threads.values())


def test_dump_pauses_when_airplane_engages_mid_download(tmp_path):
    from src.wiki.dumps import DumpDownloadManager

    gate = threading.Event()
    mgr = DumpDownloadManager(
        base_dir=tmp_path, http_get=lambda u, h: _GatedResp(gate), max_concurrent=1
    )
    try:
        mgr.start("en")
        assert _wait_until(lambda: mgr.list() and mgr.list()[0]["status"] == "downloading")
        # Airplane mode engages mid-stream: the next chunk must trip a clean pause.
        activate_kill_switch()
        gate.set()
        assert _wait_until(lambda: mgr.list()[0]["status"] == "paused"), mgr.list()
        assert not mgr.list()[0].get("error")  # a clean pause, resumable
    finally:
        gate.set()


def test_osm_start_in_airplane_is_paused_not_error(tmp_path):
    from src.geo.osm_downloads import OsmDownloadManager

    calls = []
    mgr = OsmDownloadManager(
        base_dir=tmp_path,
        http_get=lambda url, headers: calls.append(url) or _GatedResp(threading.Event()),
        max_concurrent=1,
    )
    activate_kill_switch()
    out = mgr.start("monaco")
    assert out["status"] == "paused"
    assert not out.get("error")
    assert calls == []


def test_wiki_dump_job_label_is_human_readable():
    """#36: the task manager showed "en · pages-articles-multistream" — show a human
    label instead ("English Wikipedia — articles dump")."""
    from src.api.jobs import _dump_label

    assert _dump_label("en", "pages-articles-multistream") == "English Wikipedia — articles dump"
    assert _dump_label("fr", "pages-articles") == "French Wikipedia — articles dump"
    assert (
        _dump_label("en", "pages-articles-multistream-index")
        == "English Wikipedia — articles dump index"
    )
    # Unknown edition degrades to the upper-cased code, never a crash.
    assert _dump_label("zz", "pages-articles").startswith("ZZ Wikipedia")


def test_osm_pauses_when_airplane_engages_mid_download(tmp_path):
    from src.geo.osm_downloads import OsmDownloadManager

    gate = threading.Event()
    mgr = OsmDownloadManager(
        base_dir=tmp_path, http_get=lambda url, headers: _GatedResp(gate), max_concurrent=1
    )
    try:
        mgr.start("monaco")
        assert _wait_until(lambda: mgr.list() and mgr.list()[0]["status"] == "downloading")
        activate_kill_switch()
        gate.set()
        assert _wait_until(lambda: mgr.list()[0]["status"] == "paused"), mgr.list()
    finally:
        gate.set()
