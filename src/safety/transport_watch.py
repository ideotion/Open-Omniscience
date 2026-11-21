"""The ONE check every long download makes at its request and chunk boundaries (R768, R769).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A download takes its transport when it starts: a session built while protected mode was off sends direct, and kept sending
direct after the operator switched protected mode on, for as long as the download ran (a Wikipedia dump, an OSM region, a
Medical papers run). R765 stopped the AI installs; R768 extends that to every long download, and R769 adds the other way the
transport choice can change under a running download: the stored settings becoming unreadable.

A :class:`TransportWatch` is taken when a download (or a session) starts. :meth:`TransportWatch.stop_reason` answers, at any
boundary, whether it must stop:

- ``"protected"``: it started direct and protected mode is now on. It never continues on its original transport, and is never
  re-routed for it: the operator starts it again, under protected mode's own rules and consent.
- ``"unreadable"``: the stored settings cannot be read now, so the choice in force is unknown, and the download stops whatever
  transport it started on (fail closed, as R117 refuses a new request).

A download that started through the proxy and stays protected goes on: that is not a downgrade.

The answer is cheap to ask per chunk: the save that switches protected mode on raises :func:`bump`, which every watch reads at
once, and otherwise the settings are re-read at most every :data:`RECHECK_S`. Once a watch has a reason it keeps it: a long-lived
holder (``following_session``) asks :attr:`TransportWatch.latched` and builds a fresh session under the rules then in force, never
re-opening the stopped one.

Only bodies read through ``iter_content`` (and so ``iter_lines`` and ``content``) are watched; nothing here reads ``resp.raw``
directly, and a reader that did would bypass the watch.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Iterator

#: How often a watch re-reads the stored settings when nothing has bumped (an unreadable store raises no bump).
RECHECK_S = 1.0

PROTECTED_STOP = (
    "Stopped because protected mode was switched on: this download had started over a direct connection, and it does not "
    "continue on it. Start it again to download through your proxy."
)
UNPROTECTED_STOP = (
    "Stopped because protected mode was switched off: this download had started through your proxy, and it does not continue "
    "over the direct connection. Start it again to download over the direct connection."
)
PROXY_STOP = (
    "Stopped because the proxy was changed: this download had started through another proxy, and it does not continue on the "
    "new one. Start it again to download through the proxy now set."
)
UNREADABLE_STOP = (
    "Stopped because the safety settings could not be read: the transport you chose is unknown until they can be read "
    "again, so nothing is sent. Start it again once they can be read."
)

_LOCK = threading.Lock()
_GENERATION = 0

#: The transport identities (R772's "exact transport the user approved"): the direct connection, settings that cannot be read,
#: and protected mode through one proxy configuration, named by a digest of it (``"protected:<16 hex>"``) so no address is kept.
DIRECT = "direct"
UNKNOWN = "unknown"
ANY_PROXY = "protected:*"  # a watch told only "protected" (no proxy known): any proxy matches it

_DISPLAY_KEY = secrets.token_bytes(16)  # per process: the page gets a token of the identity, never the digest itself
# Per process, and never written anywhere: the identity is KEYED, so no digest of a proxy address can be checked against a guess
# (``socks5h://127.0.0.1:9050``) by anyone holding a file or a response. A state file keeps only :func:`coarse` of it.
_ID_KEY = secrets.token_bytes(32)


class TransportStopped(RuntimeError):
    """A download stopped by a transport change. ``reason`` is ``"protected"``, ``"unprotected"``, ``"proxy"`` or
    ``"unreadable"``; the text is the fixed note.

    A ``RuntimeError``, not a connection error: a retry loop that retries connection errors must not send the request again."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(stop_message(reason))


def stop_message(reason: str) -> str:
    return {"unreadable": UNREADABLE_STOP, "unprotected": UNPROTECTED_STOP, "proxy": PROXY_STOP}.get(reason, PROTECTED_STOP)


def generation() -> int:
    with _LOCK:
        return _GENERATION


def bump() -> int:
    """Called by every save that changes the transport (protected mode on or off, another proxy): every watch re-reads at once."""
    global _GENERATION
    with _LOCK:
        _GENERATION += 1
        return _GENERATION


def transport_id(settings) -> str:
    """The identity of the transport ``settings`` send over: :data:`DIRECT`, :data:`UNKNOWN`, or ``"protected:<digest>"`` of the
    proxy and the proxy pool (a digest, so the address itself is never kept beside a download or shown)."""
    if bool(getattr(settings, "read_failed", False)) or bool(getattr(settings, "store_unreadable", False)):
        return UNKNOWN
    if not bool(settings.is_protected):
        return DIRECT
    # What the fetcher actually sends through: the pool when it has members (in its configured order, which decides the member
    # each host is sharded to), else the one proxy. A proxy left set beside a pool is not used, so it is not part of the identity.
    pool = [str(p).strip() for p in (getattr(settings, "http_proxies", None) or []) if str(p).strip()]
    material = json.dumps(["pool", pool] if pool else ["proxy", str(getattr(settings, "http_proxy", "") or "").strip()])
    return "protected:" + hmac.new(_ID_KEY, material.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def coarse(tid: str | None) -> str | None:
    """What a STATE FILE keeps of an identity: ``"direct"``, ``"unknown"`` or ``"protected"``, never the keyed digest (it is
    per process, so a later process could not read it anyway, and a file is the wrong place for anything about the proxy)."""
    if tid is None:
        return None
    return "protected" if tid.startswith("protected") else tid


def _id_now() -> str:
    """The identity of the transport in force. Settings that cannot be read are :data:`UNKNOWN`, never the direct connection."""
    try:
        from src.safety.settings import load_settings

        return transport_id(load_settings())
    except Exception:  # noqa: BLE001 - a store that cannot be read is the case this exists for
        return UNKNOWN


def change_reason(started: str | None, now: str) -> str | None:
    """Why something approved under ``started`` must stop or be held under ``now``, or ``None`` when it may go on.

    ``"unreadable"`` while the settings cannot be read, or when it was approved while they could not be (under no known
    transport); ``"protected"`` (R768) when it was approved for the direct connection and protected mode is on; ``"unprotected"``
    (R772) when it was approved through the proxy and protected mode is off; ``"proxy"`` (R772) when protected mode stays on and
    the proxy is another one. ``None`` (or a legacy value) for ``started`` reads as the direct connection; a legacy
    ``"protected"`` as :data:`ANY_PROXY`."""
    if now == UNKNOWN:
        return "unreadable"
    if started == UNKNOWN:
        return "unreadable"
    if not started or not started.startswith("protected"):
        return None if now == DIRECT else "protected"
    if now == DIRECT:
        return "unprotected"
    if started in (ANY_PROXY, "protected") or started == now:
        return None
    return "proxy"


def queue_mode() -> str:
    """The transport identity a download queued NOW is approved under (R768's queue ruling, R772). Recorded on a queued download."""
    return _id_now()


def mode_now() -> str:
    """The transport identity in force (one reading for a whole queue)."""
    return _id_now()


def hold_reason(queued_mode: str | None, mode: str | None = None) -> str | None:
    """Why a queued download must be HELD instead of started (R768's queue ruling, R769, R772), or ``None`` when it may start:
    :func:`change_reason` between the transport it was queued under and the one in force, with ``"settings"`` for unreadable.
    ``mode`` is a reading taken once for a whole queue."""
    now = mode if mode is not None else _id_now()
    if now != UNKNOWN and now != DIRECT and queued_mode in (None, "protected", ANY_PROXY):
        # Queued through a proxy this process cannot name (before a restart: the file keeps only "protected"), or by a build that
        # recorded no transport at all: nothing proves the proxy now set is the one approved, so it waits for the click.
        return "unverified"
    if queued_mode is None and now == DIRECT:
        return "unverified"  # queued by a build that recorded no transport: it may have been approved through a proxy
    reason = change_reason(queued_mode, now)
    return "settings" if reason == "unreadable" else reason


def held_by_for(reason: str) -> str:
    """The ``held_by`` of a download a :class:`TransportStopped` of ``reason`` stopped."""
    return {"protected": "protected", "unprotected": "unprotected", "proxy": "proxy"}.get(reason, "settings")


def resume_transport(tid: str | None = None) -> str:
    """What "Resume the queue" would send held downloads over, for the panel to say BEFORE the click (R772): ``"proxy"``,
    ``"direct"`` or ``"settings"`` (the settings cannot be read, so nothing would be sent)."""
    tid = _id_now() if tid is None else tid
    return "settings" if tid == UNKNOWN else ("direct" if tid == DIRECT else "proxy")


def display_token(tid: str | None = None) -> str:
    """A per-process token of a transport identity, for the page to send back with the click: the server refuses a resume when
    the transport changed after the page said which one it would use. Never the identity itself."""
    tid = _id_now() if tid is None else tid
    return hmac.new(_DISPLAY_KEY, tid.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


_RUN: contextvars.ContextVar[TransportWatch | None] = contextvars.ContextVar("oo_transport_run", default=None)


def current_run() -> TransportWatch | None:
    """The watch of the download run this code is part of, if any: every session built inside it shares that ONE watch."""
    return _RUN.get()


@contextlib.contextmanager
def run(watch: TransportWatch) -> Iterator[TransportWatch]:
    """Every guarded session built inside this block (a mirror probe, a size read, each segment of a segmented file) checks
    ``watch``: one download is one run, so a switch between two of its requests stops it rather than moving the rest to another
    transport. A worker thread inherits it only through ``contextvars.copy_context()``."""
    token = _RUN.set(watch)
    try:
        yield watch
    finally:
        _RUN.reset(token)


def for_launch(mode: str) -> TransportWatch:
    """The run watch of a download the queue launched under the transport identity ``mode`` (the one the launch decision read).
    The decision, not a later reading, is what it started on: a change saved between the decision and the session's own settings
    read is caught at the first check, which re-reads."""
    w = TransportWatch(transport=mode)
    w._checked = float("-inf")
    return w


class TransportWatch:
    """The transport a download started on, and whether it must stop now. Thread-safe."""

    def __init__(self, *, transport: str | None = None, protected: bool | None = None, unreadable: bool = False) -> None:
        self._gen = generation()  # read BEFORE the mode, so a switch between the two is still seen
        if transport is None:
            if protected is None:
                transport = _id_now()
            else:
                transport = UNKNOWN if unreadable else (ANY_PROXY if protected else DIRECT)
        self.started_id = transport
        self._checked = time.monotonic()
        self._reason: str | None = None
        self._lock = threading.Lock()

    @property
    def started_protected(self) -> bool:
        return self.started_id.startswith("protected")

    @property
    def started_unreadable(self) -> bool:
        return self.started_id == UNKNOWN

    @classmethod
    def for_settings(cls, settings) -> TransportWatch:
        """A watch for a session built from ``settings`` (the snapshot it took its transport from).

        The snapshot was read BEFORE this watch took the generation, so a switch saved between the two would be missed: the first
        check re-reads the settings whatever the interval."""
        w = cls(transport=transport_id(settings))
        w._checked = float("-inf")
        return w

    def bind_transport(self, tid: str) -> str | None:
        """A session built inside this watch's run took the transport ``tid`` from its own snapshot: when that is not the transport
        the run started on, the stop is latched NOW, before the session sends anything -- the watch alone might not re-read for up
        to :data:`RECHECK_S` (the gap between a save and its bump, or a restore that raises none)."""
        reason = change_reason(self.started_id, tid)
        with self._lock:
            if reason is not None and self._reason is None:
                self._reason = reason
            return self._reason

    def bind(self, settings) -> str | None:
        """:meth:`bind_transport` for the snapshot ``settings``."""
        return self.bind_transport(transport_id(settings))

    @property
    def latched(self) -> bool:
        """Whether this watch already has a stop reason (no settings read)."""
        with self._lock:
            return self._reason is not None

    def stop_reason(self) -> str | None:
        with self._lock:
            if self._reason is not None:
                return self._reason
            now = time.monotonic()
            if generation() == self._gen and now - self._checked < RECHECK_S:
                return None
            self._gen = generation()
            self._checked = now
        reason = change_reason(self.started_id, _id_now())
        if reason is not None:
            with self._lock:
                self._reason = self._reason or reason
                return self._reason
        return None

    def check(self) -> None:
        """Raise :class:`TransportStopped` when the download must stop."""
        reason = self.stop_reason()
        if reason is not None:
            raise TransportStopped(reason)
