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
once, and otherwise the settings are re-read at most every :data:`RECHECK_S`. Once a watch has a reason it keeps it.
"""

from __future__ import annotations

import threading
import time

#: How often a watch re-reads the stored settings when nothing has bumped (an unreadable store raises no bump).
RECHECK_S = 1.0

PROTECTED_STOP = (
    "Stopped because protected mode was switched on: this download had started over a direct connection, and it does not "
    "continue on it. Start it again to download through your proxy."
)
UNREADABLE_STOP = (
    "Stopped because the safety settings could not be read: the transport you chose is unknown until they can be read "
    "again, so nothing is sent. Start it again once they can be read."
)

_LOCK = threading.Lock()
_GENERATION = 0


class TransportStopped(RuntimeError):
    """A download stopped by a transport change. ``reason`` is ``"protected"`` or ``"unreadable"``; the text is the fixed note.

    A ``RuntimeError``, not a connection error: a retry loop that retries connection errors must not send the request again."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(stop_message(reason))


def stop_message(reason: str) -> str:
    return UNREADABLE_STOP if reason == "unreadable" else PROTECTED_STOP


def generation() -> int:
    with _LOCK:
        return _GENERATION


def bump() -> int:
    """Called by the save that switches protected mode on: every watch re-reads at its next boundary."""
    global _GENERATION
    with _LOCK:
        _GENERATION += 1
        return _GENERATION


def _mode_now() -> tuple[bool, bool]:
    """``(protected, unreadable)`` of the settings in force. Settings that cannot be read are unreadable, never transparent."""
    try:
        from src.safety.settings import load_settings

        s = load_settings()
    except Exception:  # noqa: BLE001 - a store that cannot be read is the case this exists for
        return False, True
    return bool(s.is_protected), bool(getattr(s, "read_failed", False))


class TransportWatch:
    """The transport a download started on, and whether it must stop now. Thread-safe."""

    def __init__(self, *, protected: bool | None = None, unreadable: bool = False) -> None:
        self._gen = generation()  # read BEFORE the mode, so a switch between the two is still seen
        if protected is None:
            protected, unreadable = _mode_now()
        self.started_protected = bool(protected)
        self.started_unreadable = bool(unreadable)
        self._checked = time.monotonic()
        self._reason: str | None = None
        self._lock = threading.Lock()

    @classmethod
    def for_settings(cls, settings) -> TransportWatch:
        """A watch for a session built from ``settings`` (the snapshot it took its transport from)."""
        return cls(protected=bool(settings.is_protected), unreadable=bool(getattr(settings, "read_failed", False)))

    def stop_reason(self) -> str | None:
        with self._lock:
            if self._reason is not None:
                return self._reason
            now = time.monotonic()
            if generation() == self._gen and now - self._checked < RECHECK_S:
                return None
            self._gen = generation()
            self._checked = now
        protected, unreadable = _mode_now()
        reason = None
        if unreadable:
            reason = "unreadable"
        elif protected and not self.started_protected:
            reason = "protected"
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
