"""System vitals: honest, live readout of what the app is doing to the machine.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Loopback-only, single-user: this is the app observing *itself*, never telemetry --
nothing is sent anywhere. Every figure is real and honestly attributed:

  * cpu_percent / rss_bytes / disk I/O  -> this process, via psutil.
  * scraping throughput (fetch_bytes_total) -> measured at our own ethical fetcher,
    so it is correctly attributed to THIS app. psutil's network counters are
    system-wide (it cannot attribute bytes to a process), so any net figure we
    expose from psutil is explicitly labelled ``system_wide`` -- never passed off
    as the app's own traffic.

Rates are not computed here: the endpoint returns cumulative counters + a clock,
and the caller derives bytes/s by diffing two snapshots. That keeps every number a
real measurement rather than a fabricated instantaneous value. Fields that the
platform cannot supply are returned as ``null`` (honest "unknown", never a guess).
"""

from __future__ import annotations

import os
import time

from fastapi import APIRouter

from src.monitoring.activity import activity_monitor

router = APIRouter(prefix="/api/system", tags=["system"])

# Process handle + start time, resolved once. psutil is a core dependency, but we
# stay defensive: if it is somehow unavailable the endpoint still returns the
# fetcher-measured activity (which needs no psutil).
try:
    import psutil

    _PROC = psutil.Process(os.getpid())
    # Prime cpu_percent so the first real call reports a meaningful delta, not 0.0.
    _PROC.cpu_percent(interval=None)
    _HAVE_PSUTIL = True
except Exception:  # noqa: BLE001 - any failure -> degrade honestly, never fabricate
    psutil = None  # type: ignore[assignment]
    _PROC = None
    _HAVE_PSUTIL = False

_BOOT_TS = time.time()


def _process_vitals() -> dict:
    """Per-process CPU / memory / disk I/O via psutil, or nulls if unavailable."""
    out: dict = {
        "available": _HAVE_PSUTIL,
        "cpu_percent": None,
        "rss_bytes": None,
        "vms_bytes": None,
        "num_threads": None,
        "io_read_bytes": None,
        "io_write_bytes": None,
    }
    if not _HAVE_PSUTIL or _PROC is None:
        return out
    try:
        with _PROC.oneshot():
            out["cpu_percent"] = round(_PROC.cpu_percent(interval=None), 1)
            mem = _PROC.memory_info()
            out["rss_bytes"] = int(getattr(mem, "rss", 0))
            out["vms_bytes"] = int(getattr(mem, "vms", 0))
            out["num_threads"] = int(_PROC.num_threads())
    except Exception:  # noqa: BLE001 - never let observation break the app
        pass
    # io_counters is unavailable on some platforms (e.g. macOS) -> honest null.
    try:
        io = _PROC.io_counters()
        out["io_read_bytes"] = int(io.read_bytes)
        out["io_write_bytes"] = int(io.write_bytes)
    except Exception:  # noqa: BLE001
        pass
    return out


def _system_net() -> dict | None:
    """System-wide network counters (NOT this process). Clearly labelled as such."""
    if not _HAVE_PSUTIL:
        return None
    try:
        n = psutil.net_io_counters()
        return {"bytes_sent": int(n.bytes_sent), "bytes_recv": int(n.bytes_recv)}
    except Exception:  # noqa: BLE001
        return None


@router.get("/vitals")
def system_vitals() -> dict:
    """A point-in-time snapshot of the app's own resource use + live scraping.

    Cumulative counters (bytes, io) + ``at`` (epoch seconds) let the UI compute
    rates by diffing successive snapshots. ``scraping.current_fetch`` is the URL
    being fetched *right now* (or null when idle).
    """
    return {
        "at": time.time(),
        "uptime_s": round(time.time() - _BOOT_TS, 1),
        "process": _process_vitals(),
        "scraping": activity_monitor.snapshot(),
        # System-wide (not this process) -- labelled so the UI never misattributes it.
        "network_system_wide": _system_net(),
    }
