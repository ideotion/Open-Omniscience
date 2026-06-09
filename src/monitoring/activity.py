"""Process-wide activity monitor: what the app is fetching, right now.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A tiny, thread-safe singleton that the single ethical fetcher feeds, so the UI can
show an honest, live "currently scraping <url>" readout and a *real* scraping
throughput number.

Why measure bytes here and not via psutil? psutil's network counters are
**system-wide**, not per-process -- it cannot attribute bytes to this app. So
instead we count the bytes our own fetcher actually downloads: a number that is
correctly attributed to Open Omniscience's scraping, measured at the source. It is
a cumulative counter; a rate is derived by the caller diffing two snapshots over
the elapsed time (no fabricated instantaneous value).

Local-only; nothing here leaves the machine. Best-effort and defensive: a fault in
monitoring must never break a fetch.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _Current:
    url: str
    started_at: float  # epoch seconds (time.time)


class ActivityMonitor:
    """Thread-safe record of the in-flight fetch + cumulative scraping counters."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: _Current | None = None
        self._bytes_total: int = 0
        self._fetches_total: int = 0
        self._last_url: str | None = None
        self._last_finished_at: float | None = None

    def fetch_started(self, url: str) -> None:
        """Mark a fetch as in flight (replaces any previous current)."""
        with self._lock:
            self._current = _Current(url=url, started_at=time.time())

    def fetch_bytes(self, n: int) -> None:
        """Add ``n`` downloaded bytes to the cumulative total (ignored if <= 0)."""
        if n is None or n <= 0:
            return
        with self._lock:
            self._bytes_total += int(n)

    def fetch_finished(self) -> None:
        """Clear the in-flight fetch and bump the completed-fetch counter."""
        with self._lock:
            if self._current is not None:
                self._last_url = self._current.url
                self._last_finished_at = time.time()
            self._current = None
            self._fetches_total += 1

    def snapshot(self) -> dict:
        """A point-in-time view (current fetch + cumulative counters + clock)."""
        with self._lock:
            cur = self._current
            current = None
            if cur is not None:
                current = {
                    "url": cur.url,
                    "started_at": cur.started_at,
                    "elapsed_s": round(max(0.0, time.time() - cur.started_at), 3),
                }
            return {
                "current_fetch": current,
                "last_url": self._last_url,
                "last_finished_at": self._last_finished_at,
                "bytes_total": self._bytes_total,
                "fetches_total": self._fetches_total,
                "at": time.time(),
            }


# Process-global singleton. Imported by the ethical fetcher and the /api/system
# vitals endpoint. (src.monitoring.__init__ imports nothing, so no import cycle.)
activity_monitor = ActivityMonitor()
