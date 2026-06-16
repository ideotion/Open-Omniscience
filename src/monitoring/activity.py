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

Concurrency note (the bandwidth-governed collector, 2026-06-16): under parallel
collection several fetches are in flight at once, so the monitor tracks a *set* of
in-flight fetches keyed by an opaque token returned by ``fetch_started`` (not a
single "current"). That keeps per-host rate attribution correct (each fetch's
bytes are timed against ITS OWN start, not whichever fetch happened to start last)
and lets the governor read a real in-flight count. The cumulative byte counter was
always concurrency-safe (a locked sum); ``download_rate_kbps`` diffs it over a
window for callers (the UI) that do not keep their own snapshot.

Local-only; nothing here leaves the machine. Best-effort and defensive: a fault in
monitoring must never break a fetch.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class _Current:
    url: str
    host: str
    started_at: float  # epoch seconds (time.time)


# Rolling per-host transfer samples (the maintainer asked for per-source rates).
# These are the app's OWN responses — bytes ÷ time spent downloading them — so
# attribution is exact; this is NOT an OS/per-process network counter.
_MAX_SAMPLES = 400


class ActivityMonitor:
    """Thread-safe record of the in-flight fetches + cumulative scraping counters."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # token -> _Current for every fetch currently on the wire (parallel-safe).
        self._inflight: dict[int, _Current] = {}
        self._token_seq = 0
        self._bytes_total: int = 0
        self._fetches_total: int = 0
        self._last_url: str | None = None
        self._last_finished_at: float | None = None
        # (ts, host, bytes, transfer_seconds) — bounded, oldest evicted.
        self._samples: deque[tuple[float, str, int, float]] = deque(maxlen=_MAX_SAMPLES)
        # (ts, bytes_total) ring so download_rate_kbps() can diff over a window
        # without the caller holding state.
        self._rate_ring: deque[tuple[float, int]] = deque(maxlen=_MAX_SAMPLES)

    def fetch_started(self, url: str) -> int:
        """Mark a fetch as in flight and return an opaque token.

        The token identifies THIS fetch so its bytes (``fetch_bytes``) and its end
        (``fetch_finished``) attribute to the right host/start time even when many
        fetches overlap. Callers that ignore the token still work (legacy /
        best-effort attribution to the most recent in-flight fetch)."""
        with self._lock:
            self._token_seq += 1
            tok = self._token_seq
            host = urlparse(url).netloc or "?"
            self._inflight[tok] = _Current(url=url, host=host, started_at=time.time())
            return tok

    def fetch_bytes(self, n: int, token: int | None = None) -> None:
        """Add ``n`` downloaded bytes to the cumulative total (ignored if <= 0).

        Called once per successful fetch with the body size; the in-flight record
        for ``token`` gives us the host and the time spent, so a per-host sample is
        recorded too. Without a token we attribute to the most recent in-flight
        fetch (legacy single-fetch behaviour)."""
        if n is None or n <= 0:
            return
        with self._lock:
            self._bytes_total += int(n)
            now = time.time()
            self._rate_ring.append((now, self._bytes_total))
            cur = self._inflight.get(token) if token is not None else None
            if cur is None and self._inflight:
                cur = list(self._inflight.values())[-1]  # most recent (insertion order)
            if cur is not None:
                dur = max(1e-3, now - cur.started_at)
                self._samples.append((now, cur.host, int(n), dur))

    def fetch_finished(self, token: int | None = None) -> None:
        """Clear the in-flight fetch for ``token`` and bump the completed counter."""
        with self._lock:
            cur = None
            if token is not None:
                cur = self._inflight.pop(token, None)
            elif self._inflight:
                # Legacy: drop the most recent in-flight record.
                last_key = list(self._inflight.keys())[-1]
                cur = self._inflight.pop(last_key, None)
            if cur is not None:
                self._last_url = cur.url
                self._last_finished_at = time.time()
            self._fetches_total += 1

    def inflight_count(self) -> int:
        """How many fetches are on the wire right now (for the governor + logs)."""
        with self._lock:
            return len(self._inflight)

    def inflight_hosts(self) -> int:
        """How many DISTINCT hosts are being fetched right now."""
        with self._lock:
            return len({c.host for c in self._inflight.values()})

    def download_rate_kbps(self, *, window_s: float = 8.0) -> float:
        """Wall-clock download rate in kbps (kiloBITS/s, decimal) over the last
        ``window_s`` seconds — the consumer-standard "download speed" unit the
        collect UI shows, so the target and the actual read in the same unit.

        Diffs the cumulative byte counter across the window — the honest
        bytes-per-wall-second figure (×8/1000 to kilobits), NOT a per-request
        transfer speed. Returns 0.0 when fewer than two samples fall in the window
        (idle / just started), never a fabricated value."""
        now = time.time()
        with self._lock:
            window = [(ts, b) for ts, b in self._rate_ring if now - ts <= window_s]
        if len(window) < 2:
            return 0.0
        t0, b0 = window[0]
        t1, b1 = window[-1]
        dt = max(1e-3, t1 - t0)
        return round((b1 - b0) * 8 / 1000.0 / dt, 1)

    def per_host_rates(self, *, window_s: float = 120.0, top: int = 6) -> list[dict]:
        """Recent per-host transfer rates from the app's own fetches.

        Rate = bytes ÷ seconds spent on those requests (transfer speed while
        actively downloading from that host) over the last ``window_s`` seconds.
        Empty when nothing was fetched recently — never a fabricated number.
        """
        now = time.time()
        agg: dict[str, list[float]] = {}  # host -> [bytes, seconds, fetches, last_ts]
        with self._lock:
            for ts, host, n, dur in self._samples:
                if now - ts > window_s:
                    continue
                a = agg.setdefault(host, [0.0, 0.0, 0.0, 0.0])
                a[0] += n
                a[1] += dur
                a[2] += 1
                a[3] = max(a[3], ts)
        out = [
            {
                "host": host,
                "kbps": round(b / max(s, 1e-3) / 1024.0, 1),
                "bytes": int(b),
                "fetches": int(f),
                "last_s_ago": round(max(0.0, now - last), 1),
            }
            for host, (b, s, f, last) in agg.items()
        ]
        out.sort(key=lambda r: float(r["last_s_ago"]))  # type: ignore[arg-type]
        return out[:top]

    def snapshot(self) -> dict:
        """A point-in-time view (current fetch + cumulative counters + clock)."""
        with self._lock:
            # "current_fetch" stays for back-compat (the single-fetch readout);
            # under parallelism it is the most recently started in-flight fetch,
            # with inflight giving the true concurrent count.
            cur = list(self._inflight.values())[-1] if self._inflight else None
            current = None
            if cur is not None:
                current = {
                    "url": cur.url,
                    "started_at": cur.started_at,
                    "elapsed_s": round(max(0.0, time.time() - cur.started_at), 3),
                }
            return {
                "current_fetch": current,
                "inflight": len(self._inflight),
                "last_url": self._last_url,
                "last_finished_at": self._last_finished_at,
                "bytes_total": self._bytes_total,
                "fetches_total": self._fetches_total,
                "at": time.time(),
            }


# Process-global singleton. Imported by the ethical fetcher and the /api/system
# vitals endpoint. (src.monitoring.__init__ imports nothing, so no import cycle.)
activity_monitor = ActivityMonitor()
