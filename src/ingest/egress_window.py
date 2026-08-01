"""A purpose-scoped, temporary exemption from the airplane-mode refusal.

WHY THIS EXISTS (operator, 2026-08-01): "I'd like the ollama and vllm to be able
to being installed without having to start the scrapping engine while still going
online for obvious reason (divulging your IP to ollama and vllm is not the same as
divulging it to all scrapped sources), would it be possible to go online without
scrapping or downloading anything else?"

Revealing your address to PyPI / ollama.com / Hugging Face is a bounded, chosen
exposure to a handful of infrastructure hosts. Revealing it to every source in the
catalogue is a categorically wider one. Before this module the app could not tell
the two apart: ``POST /api/system/network`` clears the kill switch AND starts the
collector in the same breath (an explicit maintainer ruling -- "Online <=>
collecting", src/api/system.py), so "let me install vLLM" meant "and begin
contacting every source I have".

THE MECHANISM, and why it is the safe shape rather than the obvious one:

    The obvious fix is to clear the kill switch without starting the scheduler.
    That works, but it converts a GUARANTEE into a CONVENTION: once the switch is
    clear, ``EthicalFetcher``, ``GuardedSession``, the dump/OSM downloaders, stats,
    discovery, mailbox and DuckDuckGo all stop refusing themselves, and every
    "fetch a thing" button in the app becomes live. The realistic failure is
    mundane -- the operator opens the window for a vLLM install and, while it
    downloads, resumes a half-finished Wikipedia dump.

    So the kill switch STAYS ENGAGED. ``kill_switch_active()`` keeps returning
    True, all ~75 of its call sites keep refusing themselves unchanged, and
    ``POST /api/system/network`` is untouched. A window is a THIRD state, not a
    weakened online: only the handful of gates that explicitly ask
    ``egress_permitted(PURPOSE_AI_INSTALL)`` are exempted.

WHAT THIS GUARANTEES, precisely:

  * The collector cannot run. The scheduler is never started by this path, and
    ``EthicalFetcher`` reads ``_KILL`` directly (src/ingest/__init__.py) -- it
    does not go through ``kill_switch_active()``, so it can never be reached by a
    window even by accident.
  * Every other kill-switch-gated fetch stays refused: dumps, OSM regions, stats,
    governments, discovery, qualification, mailbox, DuckDuckGo, preflight.
  * The SOCKET-LEVEL airplane backstop stays in force for every thread except the
    one currently performing an install request, and even there only for the
    duration of that one request (see ``socket_exemption`` below). So a path that
    consults neither the kill switch nor ``GuardedSession`` -- a third-party
    library doing its own HTTP, say -- is still refused at the socket during a
    window, exactly as it is while plainly offline.
  * A window cannot survive a process restart -- the state below is in memory and
    is never persisted, and boot re-engages airplane before anything else runs.
  * Going offline (``activate_kill_switch``) closes any open window.
  * A window closes ITSELF once no install work has been running for the idle
    grace period, driven by a reaper thread this module owns -- not by anything
    polling it, so closing does not depend on a browser tab being open.

WHAT THIS DOES **NOT** GUARANTEE -- say this plainly wherever it is surfaced:

  * It does NOT restrict WHICH HOSTS are contacted. Almost all of the install
    traffic happens in CHILD PROCESSES (``pip``/``uv`` for vLLM, a ``python -c``
    snapshot download for the weights, ``sh install.sh`` under ``sudo`` for the
    Ollama binary, and Ollama's own daemon for model pulls). A monkeypatched
    ``socket`` in this interpreter is invisible to a child process, so this module
    can neither see nor bound their egress. Constraining them would need a
    filtering proxy the children are forced through, or OS-level scoping -- the
    operator declined that machinery, so the honest claim is the narrow one above.
  * Those downloads do NOT go through the app's configured proxy or Tor.
  * Within the exempted request itself the backstop is, necessarily, not
    refusing -- that request IS the consented egress. What it reaches is
    whatever the Ollama release API and its asset host redirect to.

A NOTE ON HOW THE SOCKET EXEMPTION IS SCOPED, because the obvious version of it
is wrong. The first cut lifted the backstop process-wide for the window's whole
life. That looked equivalent -- "every real fetch path refuses itself at its own
gate anyway" -- and it was not: ``src/monitoring/preflight.py`` calls
``EthicalFetcher._guard_target`` / ``_guarded_redirect_get`` DIRECTLY rather than
``fetch()``, so it never met the kill-switch check, and it uses the fetcher's
plain ``requests.Session`` rather than a ``GuardedSession``, so it never met that
one either. Both of the "chokepoints the whole app funnels through" were absent
from it, and the socket backstop had been its only protection all along. With the
process-wide exemption, an open AI-install window let a preflight sweep resolve
and fetch scraped-source hosts -- the precise exposure this module exists to
prevent. So the exemption is now THREAD-SCOPED and REQUEST-SCOPED: entered by
``GuardedSession.request`` only for a session that named a purpose a live window
covers, and only around that one request. Every other thread keeps the full
backstop.
"""

from __future__ import annotations

import os
import threading
import time

# The only purpose that exists today. A window is opened for a NAMED purpose and
# only gates asking for that same purpose are exempted, so adding a second
# purpose later cannot silently widen the first.
PURPOSE_AI_INSTALL = "ai-install"
_PURPOSES = frozenset({PURPOSE_AI_INSTALL})


def _env_seconds(name: str, default: float, *, floor: float, ceiling: float) -> float:
    """A bounded float from the environment. An operator override may narrow the
    window or widen it a little, but can never remove the deadline -- an unbounded
    window is a permanent hole, which is the failure mode this whole module exists
    to avoid."""
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return default
    return max(floor, min(ceiling, val))


def _max_ttl() -> float:
    # Six hours: a multi-GB weights download over a slow or congested link is
    # genuinely hours, and a deadline that fires mid-install would look like a
    # random failure. The idle reap below normally closes the window long before
    # this; the deadline is the backstop for a window nothing ever polls.
    return _env_seconds("OO_EGRESS_WINDOW_MAX_S", 6 * 3600.0, floor=60.0, ceiling=24 * 3600.0)


def _idle_grace() -> float:
    # How long the window may sit with no install work running before it closes
    # itself. Must comfortably cover (a) the gap between the operator consenting
    # and the job actually spawning, and (b) the gap between two steps of the
    # setup chain (install vLLM -> download weights).
    return _env_seconds("OO_EGRESS_WINDOW_IDLE_GRACE_S", 180.0, floor=10.0, ceiling=3600.0)


def _reap_tick() -> float:
    """How often the reaper thread wakes. Small enough to close promptly after the
    grace period, large enough to be free (a sleeping thread costs nothing)."""
    return _env_seconds("OO_EGRESS_WINDOW_REAP_TICK_S", 5.0, floor=0.02, ceiling=300.0)


class _Window:
    __slots__ = ("purpose", "opened_at", "deadline", "last_busy_at", "holds")

    def __init__(self, purpose: str, opened_at: float, deadline: float) -> None:
        self.purpose = purpose
        self.opened_at = opened_at
        self.deadline = deadline
        # Seeded to the open time so a freshly-opened window gets the full grace
        # period before the idle reap can consider it stale.
        self.last_busy_at = opened_at
        # Explicit "work is happening" holds, for install steps that are NOT
        # registered background jobs (the Ollama binary installer is a streaming
        # endpoint, not a BackgroundJob, so without this the idle reap would close
        # the window out from under the very install it was opened for).
        #
        # PER-WINDOW, not a module global: a hold that is never released -- a
        # wedged `sh install.sh` whose `proc.wait()` does not return -- must not
        # outlive its own window and pin EVERY later one open to the full deadline.
        # It dies with the window it was taken under.
        self.holds = 0


_LOCK = threading.Lock()
_WINDOW: _Window | None = None
_REAPER: threading.Thread | None = None

# The background-job kinds that count as install work in progress.
_BUSY_JOB_KINDS = frozenset({"vllm-install", "vllm-model-download"})

# Per-THREAD socket-backstop exemption. See the module docstring: the exemption
# has to be this narrow, because the backstop is the only thing standing between
# an open window and every fetch path that does not check the kill switch itself.
_THREAD_STATE = threading.local()


class EgressWindowError(ValueError):
    """An unknown purpose, or a ttl that is not a number."""


def _now() -> float:
    # Monotonic: a wall-clock jump (NTP, suspend/resume) must never extend a
    # window past its deadline.
    return time.monotonic()


def _expired(win: _Window, now: float) -> bool:
    return now >= win.deadline


def any_window_open() -> bool:
    """True if a window is open right now, for any purpose.

    Deliberately CHEAP: a deadline comparison under the lock, no job-registry
    probe. This is called from the socket guard on every ``getaddrinfo`` and
    ``connect``, so it must not do real work or re-enter anything.
    """
    global _WINDOW
    with _LOCK:
        win = _WINDOW
        if win is None:
            return False
        if _expired(win, _now()):
            _WINDOW = None
            return False
        return True


def window_open(purpose: str) -> bool:
    """True if a window covering ``purpose`` is open right now."""
    global _WINDOW
    with _LOCK:
        win = _WINDOW
        if win is None:
            return False
        if _expired(win, _now()):
            _WINDOW = None
            return False
        return win.purpose == purpose


def socket_exempt_here() -> bool:
    """True if THIS thread is inside an exempted install request right now.

    Read by the airplane socket guard on every ``getaddrinfo``/``connect``, so it
    is a bare thread-local attribute read -- no lock, no import, nothing to
    re-enter. It is checked BEFORE the window lookup precisely because it is the
    cheaper of the two and is false on every thread but one.
    """
    return getattr(_THREAD_STATE, "socket_exempt", 0) > 0


class _SocketExemption:
    """Lift the socket backstop for THIS thread, for the duration of one request.

    Entered by ``GuardedSession.request`` (and only there) once it has established
    that the kill switch is engaged AND a live window covers this session's named
    purpose -- so the exemption cannot be entered without the consent that
    authorised it. Re-entrant, and unwound on any exception.

    The flag itself carries no purpose: the purpose check happens at the entry
    point, where the session's own ``egress_purpose`` is matched against the live
    window. That is exact while one purpose exists. A second purpose whose gates
    should NOT reach the socket would need the purpose threaded through here too,
    rather than inheriting this exemption by being a window at all.
    """

    def __enter__(self) -> "_SocketExemption":
        _THREAD_STATE.socket_exempt = getattr(_THREAD_STATE, "socket_exempt", 0) + 1
        return self

    def __exit__(self, *exc: object) -> None:
        _THREAD_STATE.socket_exempt = max(0, getattr(_THREAD_STATE, "socket_exempt", 0) - 1)


def socket_exemption() -> _SocketExemption:
    """Context manager for :func:`socket_exempt_here`."""
    return _SocketExemption()


def egress_permitted(purpose: str | None) -> bool:
    """The one question an AI-install gate should ask instead of ``kill_switch_active()``.

    True when the app is simply online, or when a window covering ``purpose`` is
    open. ``purpose=None`` means "no window can cover this" -- so a caller that
    forgets to name a purpose gets the OLD, refusing behaviour rather than a hole.
    """
    from src.ingest import kill_switch_active

    if not kill_switch_active():
        return True
    if purpose is None:
        return False
    return window_open(purpose)


def open_window(purpose: str, *, ttl_s: float | None = None) -> dict:
    """Open (or refresh) the window for ``purpose``. Returns its status.

    This is the CONSENTED act -- it is reachable only from the endpoint that shows
    the operator what it does and does not protect. Opening does not start, queue
    or schedule anything: it only stops the AI-install gates from refusing.
    """
    global _WINDOW
    if purpose not in _PURPOSES:
        raise EgressWindowError(f"unknown egress-window purpose: {purpose!r}")
    cap = _max_ttl()
    try:
        ttl = cap if ttl_s is None else float(ttl_s)
    except (TypeError, ValueError) as exc:
        raise EgressWindowError(f"ttl_s must be a number, got {ttl_s!r}") from exc
    ttl = max(1.0, min(cap, ttl))
    now = _now()
    with _LOCK:
        # One window at a time. Re-opening the same purpose refreshes its deadline
        # (the operator re-consented); a DIFFERENT purpose replaces it rather than
        # accumulating, so there is never a set of purposes to reason about.
        _WINDOW = _Window(purpose=purpose, opened_at=now, deadline=now + ttl)
        _ensure_reaper_locked()
        return _status_locked(_WINDOW, now)


def close_window(*, purpose: str | None = None) -> bool:
    """Close the window. Returns True if one was actually open.

    ``purpose=None`` closes whatever is open (the operator's "close now", going
    offline, shutdown). Naming a purpose closes only that one.
    """
    global _WINDOW
    with _LOCK:
        win = _WINDOW
        if win is None:
            return False
        if purpose is not None and win.purpose != purpose:
            return False
        _WINDOW = None
        return True


def collector_running() -> bool | None:
    """Whether the background collector is actually running, READ FROM THE SCHEDULER.

    The window's whole promise is "the collector stays stopped", so the UI must be
    able to show that holding rather than take our word for it. Returns ``None``
    when the scheduler cannot be reached -- an honest "unknown", never a
    reassuring ``False`` we did not measure.
    """
    try:
        from src.scheduler.runner import get_scheduler

        return bool(get_scheduler().is_running())
    except Exception:  # noqa: BLE001
        return None


def _status_locked(win: _Window | None, now: float) -> dict:
    if win is None:
        return {"open": False, "purpose": None, "seconds_remaining": 0}
    return {
        "open": True,
        "purpose": win.purpose,
        "seconds_remaining": max(0, int(win.deadline - now)),
        "seconds_open": max(0, int(now - win.opened_at)),
    }


def status(*, with_collector: bool = False) -> dict:
    """A snapshot for the UI. Reaps an expired window first.

    ``with_collector`` adds the MEASURED collector state (off by default so the
    hot in-process callers never pay for a scheduler import).
    """
    global _WINDOW
    now = _now()
    with _LOCK:
        win = _WINDOW
        if win is not None and _expired(win, now):
            _WINDOW = None
            win = None
        out = _status_locked(win, now)
    if with_collector:
        out["collector_running"] = collector_running()
    return out


# --------------------------------------------------------------------------- #
# Holds: "install work is happening right now" for work that is not a job.
# --------------------------------------------------------------------------- #
class _Hold:
    """Context manager marking install work in flight, so the idle reap waits.

    A hold belongs to the window that was open when it was taken, and is released
    against THAT window -- so it can neither pin a later, unrelated window open
    (see ``_Window.holds``) nor decrement one it never incremented. Taken with no
    window open it is simply a no-op: there is nothing to hold open.
    """

    __slots__ = ("_win",)

    def __init__(self) -> None:
        self._win: _Window | None = None

    def __enter__(self) -> "_Hold":
        with _LOCK:
            self._win = _WINDOW
            if self._win is not None:
                self._win.holds += 1
                self._win.last_busy_at = _now()
        return self

    def __exit__(self, *exc: object) -> None:
        with _LOCK:
            win, self._win = self._win, None
            if win is None:
                return
            win.holds = max(0, win.holds - 1)
            if win is _WINDOW:
                win.last_busy_at = _now()


def hold() -> _Hold:
    """Mark install work in flight for the duration of a ``with`` block."""
    return _Hold()


def _default_is_busy() -> bool:
    """True while any AI-install work is actually running.

    Reads the LIVE owners (the background-job registry and the model-pull queue)
    rather than any state of our own -- a shadow copy could disagree with reality,
    and the whole point of the reap is to notice when reality has moved on.
    """
    with _LOCK:
        win = _WINDOW
        if win is not None and win.holds > 0:
            return True
    try:
        from src.jobs.background import all_job_statuses

        for st in all_job_statuses():
            # ``ended_at`` guards the exotic case of a worker killed by a
            # BaseException, which leaves ``state`` at "running" forever: without
            # it such a job would wedge the window open to its full deadline.
            if (
                st.get("kind") in _BUSY_JOB_KINDS
                and st.get("state") == "running"
                and st.get("ended_at") is None
            ):
                return True
    except Exception:  # noqa: BLE001 - a registry hiccup must never wedge the window open
        pass
    try:
        from src.llm.pull_queue import get_pull_manager

        pq = get_pull_manager().status()
        if pq.get("active") or pq.get("queue"):
            return True
    except Exception:  # noqa: BLE001 - same: unknown -> not busy -> the window closes sooner
        pass
    return False


def reap_idle(is_busy=None) -> bool:
    """Close the window once no install work has been running for the grace period.

    This is the mechanism that satisfies "close on success, on failure, and on
    cancel" with ONE rule instead of three hooks: every one of those outcomes is
    simply "nothing is running any more". It also covers the case no per-outcome
    hook can -- a worker thread that dies without unwinding.

    Returns True if it closed a window. Safe to call often. Its callers are the
    reaper thread above (which is what makes closing a property of this module
    rather than of a browser tab) and the status endpoint; never the socket
    guard, which must stay free of anything that does real work.
    """
    global _WINDOW
    now = _now()
    with _LOCK:
        win = _WINDOW
        if win is None:
            return False
        if _expired(win, now):
            _WINDOW = None
            return True
    busy = (is_busy or _default_is_busy)()
    with _LOCK:
        win = _WINDOW
        if win is None:
            return False
        if busy:
            win.last_busy_at = now
            return False
        if now - win.last_busy_at >= _idle_grace():
            _WINDOW = None
            return True
        return False


# --------------------------------------------------------------------------- #
# The reaper: what makes "it closes on its own" a property of this module.
# --------------------------------------------------------------------------- #
def _reaper_loop() -> None:
    """Drive ``reap_idle`` until the window is gone, then exit.

    Without this the ONLY caller of ``reap_idle`` was the status endpoint, which
    means the window closed when a browser happened to poll it -- so an operator
    who started an install and closed the tab kept the window open to its full
    deadline. "It closes once the install finishes" is a claim the consent dialog
    makes, so it has to hold with no UI attached.
    """
    global _REAPER
    while True:
        time.sleep(_reap_tick())
        try:
            reap_idle()
        except Exception:  # noqa: BLE001 - a reap hiccup must never kill the reaper
            pass
        with _LOCK:
            if _WINDOW is None:
                # Cleared under the same lock ``_ensure_reaper_locked`` takes, so
                # a window opening concurrently either sees a live reaper or
                # starts a fresh one -- never neither, never two.
                _REAPER = None
                return


def _ensure_reaper_locked() -> None:
    """Start the reaper if it is not already running. Caller holds ``_LOCK``."""
    global _REAPER
    if _REAPER is not None and _REAPER.is_alive():
        return
    _REAPER = threading.Thread(
        target=_reaper_loop, name="oo-egress-window-reaper", daemon=True
    )
    _REAPER.start()


def _reset_for_tests() -> None:
    global _WINDOW
    with _LOCK:
        _WINDOW = None
    _THREAD_STATE.socket_exempt = 0
