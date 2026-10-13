"""A test helper: make the previous session's marks the ledger's previous session's, for a test of ``forensics._previous_peaks``.

``forensics._previous_peaks`` reads the marks as the previous session's only when they carry the ledger's id for it (the way the end
record decides), so a test that builds marks without a ledger names that id on both sides."""

from __future__ import annotations

from src.monitoring import session_history, session_hwm


def claim(monkeypatch, sid: str = "s-prev") -> None:
    """The marks ``session_hwm.previous()`` returns carry ``sid``, and the ledger says that is the previous session's id."""
    marks = session_hwm.previous()
    if marks is not None:
        marks["session_id"] = sid
    monkeypatch.setattr(session_history, "previous_session_id", lambda: sid)
