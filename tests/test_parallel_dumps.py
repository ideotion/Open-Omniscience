"""Parallel, circuit-isolated dump downloads (maintainer 2026-06-13).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Up to ``max_concurrent`` dumps download in PARALLEL (dumps write files, not the
DB -- no single-writer contention); the excess still QUEUES and is reorderable
(the T9 control is preserved). Over Tor, each download rides its own circuit via
per-stream SOCKS isolation, so aggregate throughput multiplies instead of
sharing one slow circuit.
"""

from __future__ import annotations

import threading
import time

from src.safety.fetcher import _with_stream_isolation
from src.wiki.dumps import DumpDownloadManager


class _SlowResp:
    """A response whose body only advances when the gate is released, so several
    downloads can be observed 'downloading' at once."""

    status_code = 200
    headers = {"Content-Length": "30"}

    def __init__(self, gate: threading.Event):
        self._gate = gate

    def raise_for_status(self):
        pass

    def iter_content(self, _chunk):
        for _ in range(3):
            self._gate.wait(5)
            yield b"0123456789"


def _wait_until(predicate, tries=200, delay=0.02):
    for _ in range(tries):
        if predicate():
            return True
        time.sleep(delay)
    return False


def _downloading(mgr) -> int:
    return sum(1 for e in mgr.list() if e["status"] == "downloading")


# ----------------------------- parallelism ---------------------------------- #


def test_dumps_download_in_parallel_up_to_capacity(tmp_path):
    gate = threading.Event()
    mgr = DumpDownloadManager(
        base_dir=tmp_path, http_get=lambda u, h: _SlowResp(gate), max_concurrent=3
    )
    mgr.start("en")
    mgr.start("fr")
    mgr.start("de")
    try:
        assert _wait_until(lambda: _downloading(mgr) == 3), "all three should run at once"
        assert mgr.queue_order() == []  # nothing queued -- true parallelism
    finally:
        gate.set()


def test_excess_over_capacity_queues_and_stays_reorderable(tmp_path):
    gate = threading.Event()
    mgr = DumpDownloadManager(
        base_dir=tmp_path, http_get=lambda u, h: _SlowResp(gate), max_concurrent=2
    )
    for w in ("en", "fr", "de", "es"):
        mgr.start(w)
    try:
        assert _wait_until(lambda: _downloading(mgr) == 2), "capacity = 2 download at once"
        q = mgr.queue_order()
        assert len(q) == 2, "the excess two queue (prioritisation preserved)"
        # The queued downloads remain operator-reorderable.
        reversed_q = [q[1], q[0]]
        assert mgr.reorder(reversed_q) == reversed_q
        assert mgr.queue_order() == reversed_q
    finally:
        gate.set()


def test_stale_downloading_status_is_reset_on_reload(tmp_path):
    # A process restart leaves no worker thread; a persisted "downloading" must
    # not block a parallel slot forever -- it is demoted to "paused" (resumable).
    gate = threading.Event()
    mgr = DumpDownloadManager(
        base_dir=tmp_path, http_get=lambda u, h: _SlowResp(gate), max_concurrent=1
    )
    mgr.start("en")
    try:
        assert _wait_until(lambda: _downloading(mgr) == 1)
    finally:
        gate.set()
    # Join the worker so its own completion (status="done" + _save) fully lands
    # BEFORE we overwrite the persisted state below -- otherwise the worker races
    # our _save() and the reload can read "done" (a flake caught on the macOS lane).
    worker = mgr._threads.get("en:pages-articles")
    if worker is not None:
        worker.join(timeout=5)
    # Simulate a restart from the SAME persisted state, mid-download.
    mgr._entries["en:pages-articles"].status = "downloading"
    mgr._save()
    reloaded = DumpDownloadManager(base_dir=tmp_path, max_concurrent=1)
    assert reloaded._entries["en:pages-articles"].status == "paused"
    assert reloaded._downloading_now() == 0  # the slot is free again


# --------------------------- circuit isolation ------------------------------ #


def test_socks_proxy_gets_per_token_isolation():
    out = _with_stream_isolation("socks5://127.0.0.1:9050", "enwiki-dump")
    assert out == "socks5://enwiki-dump:enwiki-dump@127.0.0.1:9050"
    # different tokens -> different SOCKS auth -> different Tor circuits
    a = _with_stream_isolation("socks5h://127.0.0.1:9050", "a")
    b = _with_stream_isolation("socks5h://127.0.0.1:9050", "b")
    assert a != b


def test_isolation_is_a_noop_without_a_token_or_for_http_proxies():
    assert _with_stream_isolation("socks5://127.0.0.1:9050", None) == "socks5://127.0.0.1:9050"
    assert _with_stream_isolation("http://127.0.0.1:8118", "tok") == "http://127.0.0.1:8118"


def test_isolation_respects_caller_supplied_credentials():
    url = "socks5://user:pass@127.0.0.1:9050"
    assert _with_stream_isolation(url, "tok") == url


def test_dump_fetch_helpers_pass_the_url_as_isolation_token(monkeypatch):
    # Each dump's URL is its isolation token, so parallel downloads of different
    # dumps ride different Tor circuits.
    from src.safety import fetcher as fetcher_mod

    seen = {}

    class _FakeSession:
        def get(self, url, **kw):
            seen["get_url"] = url
            return _SlowResp(threading.Event())

        def head(self, url, **kw):
            return _SlowResp(threading.Event())

    def _fake_guarded(*, user_agent=None, isolation_token=None):
        seen["token"] = isolation_token
        return _FakeSession()

    monkeypatch.setattr(fetcher_mod, "guarded_session", _fake_guarded)
    from src.wiki.dumps import _default_get

    _default_get("https://dumps.wikimedia.org/enwiki/x.bz2", {})
    assert seen["token"] == "https://dumps.wikimedia.org/enwiki/x.bz2"
