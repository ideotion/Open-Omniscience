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


class EgressWindowBody(BaseModel):
    """Open or close the AI-install egress window."""

    open: bool = False
    ttl_s: float | None = None


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
    from src.ingest import (
        activate_kill_switch,
        clear_kill_switch,
        kill_switch_active,
        note_operator_crossed_online,
    )

    online = bool(payload.get("online"))
    if online:
        clear_kill_switch()
        # THE decision, recorded here rather than inside clear_kill_switch: a slow
        # background boot upkeep must not re-engage airplane over it (field report
        # 2026-08-02, "sometimes the app remains in airplane mode with no explanation").
        note_operator_crossed_online()
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


# --------------------------------------------------------------------------- #
# The AI-install egress window: go online for the local-AI install WITHOUT
# starting the collector.
#
# Operator, 2026-08-01: "divulging your IP to ollama and vllm is not the same as
# divulging it to all scrapped sources". POST /api/system/network cannot express
# that -- it clears the kill switch AND starts the collector in one ruled step
# ("Online <=> collecting"). These two routes are a THIRD state instead: the kill
# switch stays ENGAGED, so every other gated fetch keeps refusing itself, and only
# the handful of AI-install gates are exempted.
#
# Deliberately NOT reusing /network: that endpoint stays byte-identical, so the
# maintainer ruling it encodes is untouched and its consent popup, its invariant
# and its tests cannot be regressed by this feature.
# --------------------------------------------------------------------------- #
@router.get("/egress-window")
def egress_window_status() -> dict:
    """Live state of the AI-install egress window.

    Reaps first: this is the poll the UI runs while a window is open, so it is
    also where a window whose install has finished (or failed, or been cancelled)
    gets closed -- one rule covering all three outcomes, keyed on "nothing is
    running any more" rather than on a hook per outcome.
    """
    from src.ingest import egress_window as ew

    ew.reap_idle()
    return ew.status(with_collector=True)


@router.post("/egress-window")
def set_egress_window(body: EgressWindowBody) -> dict:
    """Open (the consented act) or close the AI-install egress window.

    NEVER touches the scheduler -- that is the whole point, and the reason this
    is not a variant of ``set_network_mode``. Opening starts, queues and schedules
    nothing; it only stops the AI-install gates from refusing.
    """
    from src.ingest import egress_window as ew

    if body.open:
        try:
            return ew.open_window(ew.PURPOSE_AI_INSTALL, ttl_s=body.ttl_s) | {
                "collector_running": ew.collector_running()
            }
        except ew.EgressWindowError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    ew.close_window()
    return ew.status(with_collector=True)


# --------------------------------------------------------------------------- #
# THE UNATTENDED RUN — one button, armed before a multi-day absence.           #
#                                                                             #
# 2026-08-12 field ask: a dedicated slow machine is left running for ~10 days  #
# on a million-article corpus, and the operator wants ONE control to press     #
# before leaving. This composes surfaces that already exist rather than adding #
# a second way to collect: going online IS starting the collector (the ruled   #
# online-implies-collecting semantics above), and the qualification backlog    #
# already has a cancellable, memory-guard-aware background job. What is new    #
# here is (a) doing both from one press, (b) taking one measured safety        #
# decision first, and (c) arming the expedition log so the absence has a       #
# record the operator can copy back.                                          #
# --------------------------------------------------------------------------- #

@router.post("/unattended/start")
def unattended_start(payload: dict | None = None) -> dict:
    """Arm an unattended run: go online (which starts continuous collection, per the
    ruled online-implies-collecting semantics), optionally start the bulk qualification
    drain, and arm the expedition log.

    This is the ONE control to press before a multi-day absence. It is idempotent --
    pressing it twice keeps the original start time, because the window a returning
    operator cares about is the whole absence.

    ``qualify`` (default: decide from the measurement) forces the backlog drain on or
    off explicitly. The decision and its basis are always recorded in the log, so a run
    that declined to qualify says so rather than looking like one that simply found
    nothing to do."""
    payload = payload or {}
    force = payload.get("qualify")
    note = str(payload.get("note") or "")[:200]

    from src.database.session import session_scope
    from src.ingest import clear_kill_switch, kill_switch_active, note_operator_crossed_online
    from src.monitoring import expedition

    # 1. Online. Same two calls the top-bar toggle makes, in the same order, so the
    #    consent semantics and the crossed-online record are identical -- this button
    #    is a composition of the ruled path, never a second way in.
    clear_kill_switch()
    note_operator_crossed_online()

    # 2. Collection. Idempotent; gated exactly like the network toggle.
    collecting = None
    if os.getenv("OO_NO_SCHEDULER", "0") != "1":
        try:
            from src.scheduler.runner import get_scheduler

            get_scheduler().start()
            collecting = get_scheduler().is_running()
        except Exception:  # noqa: BLE001 - a scheduler hiccup must not lose the arming
            _LOG.warning("unattended start: scheduler start failed", exc_info=True)
            collecting = False

    # 3. The measured safety decision, then the backlog drain.
    with session_scope() as db:
        safety = expedition.qualification_safety(db)
    if force is not None:
        safety = {**safety, "safe": bool(force), "basis": "operator override",
                  "reason": f"operator set qualify={bool(force)} explicitly"}

    qualification = {"started": False, "reason": safety["reason"]}
    if safety["safe"]:
        try:
            from src.api.source_management import _BULK_QUALIFICATION_JOB
            from src.config.power_profiles import qualification_batch_size

            job = _BULK_QUALIFICATION_JOB.start(batch_size=qualification_batch_size())
            qualification = {"started": True, "job": job}
        except RuntimeError:
            qualification = {"started": False, "reason": "already running"}
        except Exception as exc:  # noqa: BLE001 - never lose the arming over the drain
            _LOG.warning("unattended start: bulk qualification failed to start", exc_info=True)
            qualification = {"started": False, "reason": f"could not start: {type(exc).__name__}"}

    state = expedition.arm(
        safety={**safety, "bulk_qualification_started": qualification["started"]},
        note=note,
    )
    expedition.record_event(
        "job-started",
        "collection online"
        + ("; bulk qualification started" if qualification["started"]
           else f"; bulk qualification not started ({qualification.get('reason')})"),
    )
    return {
        "armed": True,
        "online": not kill_switch_active(),
        "collecting": collecting,
        "qualification": qualification,
        "safety": safety,
        "started_at": state.get("started_at"),
    }


@router.post("/unattended/stop")
def unattended_stop(payload: dict | None = None) -> dict:
    """Disarm the run. Deliberately does NOT stop collection or cancel the drain: the
    operator may want the record closed while the machine keeps working, and stopping
    collection already has its own control (the airplane toggle). Nothing is destroyed
    -- the log stays readable."""
    from src.monitoring import expedition

    reason = str((payload or {}).get("reason") or "")[:200]
    expedition.disarm(reason)
    return {"armed": False}


@router.get("/unattended/log")
def unattended_log(fmt: str = "text") -> dict:
    """The expedition log. A PLAIN FILE READ plus in-memory state -- it never scans the
    corpus, so this is safe to press on a slow machine mid-run, with jobs still running.

    ``fmt=text`` (default) returns the copy-pasteable rendering; ``fmt=json`` returns
    the structured digest."""
    from src.monitoring import expedition

    d = expedition.digest()
    if fmt == "json":
        return d
    return {"text": expedition.render_text(d)}
