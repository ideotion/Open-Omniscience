"""
GUI shutdown — a visual equivalent of Ctrl-C (maintainer 2026-06-21).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

request_shutdown stops the server process; it must require confirmation and must
NOT touch data (this is not uninstall/panic). The actual SIGTERM is injected here
so the test never kills the runner.
"""

from src.safety.shutdown import request_shutdown


def test_request_shutdown_requires_confirm():
    armed = []
    r = request_shutdown(confirm=False, _arm=lambda d: armed.append(d))
    assert r["ok"] is False
    assert not armed  # nothing is armed without confirmation


def test_request_shutdown_arms_stop_on_confirm():
    armed = []
    r = request_shutdown(confirm=True, delay=0.0, _arm=lambda d: armed.append(d))
    assert r["ok"] is True
    assert armed == [0.0]  # the stop was scheduled exactly once, with our delay
    assert "shutting down" in r["detail"].lower()
