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

import logging
import os
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.monitoring.activity import activity_monitor

router = APIRouter(prefix="/api/system", tags=["system"])
_LOG = logging.getLogger(__name__)


class ShutdownBody(BaseModel):
    confirm: bool = False


@router.post("/shutdown")
def system_shutdown(body: ShutdownBody) -> dict:
    """Stop the app from the GUI (a power button + confirm) — the equivalent of Ctrl-C.

    NOT uninstall, NOT panic: the data directory, corpus and keys are untouched; the
    server process simply exits. ``confirm`` must be true.
    """
    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirmation required to shut down")
    from src.safety.shutdown import request_shutdown

    return request_shutdown(confirm=True)

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
            # psutil reports PER-CORE process percentages (160% = 1.6 cores),
            # which read as "more than the whole OS" (live-test bug 2026-06-11).
            # Normalize to a share of TOTAL machine capacity, like OS monitors.
            ncpu = psutil.cpu_count() or 1
            out["cpu_percent"] = round(_PROC.cpu_percent(interval=None) / ncpu, 1)
            out["cpu_cores"] = ncpu
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


@router.get("/network")
def network_mode() -> dict:
    """The app-wide network mode (the kill switch, surfaced as online/offline)."""
    from src.ingest import kill_switch_active

    return {"online": not kill_switch_active()}


@router.get("/interfaces")
def local_interfaces() -> dict:
    """The machine's LOCAL network addresses, for the online-consent popup.

    Read from the kernel's interface tables via psutil — NEVER a network call
    (fetching a public-IP echo before consent would itself be network traffic
    while "offline"). Loopback and link-local addresses are skipped: the list
    answers "what addresses does this machine present to its networks". The
    public address beyond them is whatever the ISP/VPN presents; this app does
    not check it, and the UI says so.
    """
    interfaces: list[dict] = []
    if _HAVE_PSUTIL:
        try:
            import socket as _socket

            for name, addrs in psutil.net_if_addrs().items():
                ips = []
                for a in addrs:
                    if a.family not in (_socket.AF_INET, getattr(_socket, "AF_INET6", None)):
                        continue
                    ip = (a.address or "").split("%")[0]
                    if not ip or ip.startswith(("127.", "169.254.", "fe80")) or ip == "::1":
                        continue
                    ips.append(ip)
                if ips:
                    interfaces.append({"interface": name, "addresses": ips})
        except Exception:  # noqa: BLE001 - degrade honestly below, never fabricate
            pass
    return {
        "available": _HAVE_PSUTIL,
        "interfaces": interfaces,
        "method": (
            "psutil.net_if_addrs() — the kernel's own interface tables, read "
            "locally; no packet leaves the machine. Loopback and link-local "
            "addresses omitted."
        ),
    }


@router.post("/network")
def set_network_mode(payload: dict) -> dict:
    """Flip the app-wide network mode (maintainer-ruled 2026-06-11: a first-
    class top-bar play/pause, not a control buried in a sub-tab).

    Offline = the global kill switch: every NEW fetch on every path is refused
    immediately; one already-in-flight HTTP request may still complete (an
    open socket cannot be honestly un-sent) — the UI says so.
    """
    from src.ingest import activate_kill_switch, clear_kill_switch, kill_switch_active

    online = bool(payload.get("online"))
    if online:
        clear_kill_switch()
    else:
        activate_kill_switch()
    # Online ⟺ collecting (maintainer 2026-06-18): crossing online immediately
    # starts the continuous background collector (articles + markets/indices +
    # calendars + watched Wikipedia + …); crossing offline (airplane) stops it —
    # "the only reason to stop it is airplane mode". So EVERY path to online (the
    # top-bar airplane button, the first-launch wizard's "Go online", any consented
    # action) begins collection at once, with no separate Collect/Start step. The
    # kill switch is set FIRST so a stop winds the in-flight pass down fast. Gated
    # by OO_NO_SCHEDULER (tests/headless drive the scheduler themselves).
    if os.getenv("OO_NO_SCHEDULER", "0") != "1":
        try:
            from src.scheduler.runner import get_scheduler

            scheduler = get_scheduler()
            if online:
                scheduler.start()  # idempotent: no-op if already running
            else:
                scheduler.stop()  # idempotent: no-op if not running
        except Exception:  # noqa: BLE001 - a scheduler hiccup must never fail the toggle
            _LOG.warning(
                "network toggle: scheduler %s failed", "start" if online else "stop", exc_info=True
            )
    return {"online": not kill_switch_active()}
