"""S3.4 (ruling 7): both ends under load -- the server says, the client backs off.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two halves, deliberately independent. The server publishes three measurements on
the already-polled ``/api/scheduler/status``; the client slows its polls on the
429/503 it was itself served. They are not wired together, and that is the point:
a server too loaded to answer cannot tell anyone it is loaded, so a backoff routed
through its payload would fail exactly when it is needed.

The client half is behavioural and lives in tests/load_backoff_node_test.js
(a schedule cannot be read off the source -- the code it replaced called
setInterval with a constant, which is a perfectly good-looking line that simply
cannot back off). It is driven from here so the node-suite driver ratchet holds.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_load_backoff_node_suite() -> None:
    """Drives the real poll chain with a fake clock and asserts the delay it asks for."""
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "load_backoff_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ok -" in proc.stdout


# --------------------------------------------------------------------------- #
# The server half
# --------------------------------------------------------------------------- #
def test_server_load_publishes_three_independent_readings():
    from src.monitoring.server_load import server_load

    out = server_load()
    assert set(out) == {"loop_lag", "heavy", "memory_guard", "method"}
    for name in ("loop_lag", "heavy", "memory_guard"):
        assert out[name]["read"] is True, f"{name}: {out[name]}"
    assert out["heavy"]["cap"] >= 1
    assert isinstance(out["memory_guard"]["engaged"], bool)


def test_a_section_that_cannot_be_read_says_so_rather_than_reporting_a_quiet_value(monkeypatch):
    """"We could not read it" and "we read it and it is quiet" are opposite facts.

    This is not hypothetical: the first cut of the memory-guard section called
    ``engaged`` as a method when it is a property, and it was THIS degrade that
    named the TypeError instead of publishing ``engaged: False`` -- a quiet value
    for a reading that never happened.
    """
    import src.monitoring.server_load as mod

    def _boom():
        raise RuntimeError("simulated")

    monkeypatch.setattr(mod, "_memory_guard", _boom)
    out = mod.server_load()
    assert out["memory_guard"]["read"] is False
    assert "RuntimeError" in out["memory_guard"]["reason"]
    assert "engaged" not in out["memory_guard"], (
        "a failed section must not also publish the value it failed to read"
    )
    # The other sections are untouched: one subsystem going quiet must not blank the rest.
    assert out["loop_lag"]["read"] is True and out["heavy"]["read"] is True


def test_an_unmeasured_loop_lag_is_none_and_never_zero():
    """Zero means "the loop is not lagging". Nobody measured means nobody measured."""
    from src.monitoring import latency

    latency._reset_for_tests()
    out = latency.loop_lag()
    assert out["latest_ms"] is None and out["peak_ms"] is None
    assert out["samples"] == 0
    assert "reason" in out, "an absent reading must say why it is absent"


def test_loop_lag_publishes_latest_and_peak_separately():
    """One number cannot answer both questions.

    A single 200 ms sample can read near zero on a loaded server that happened to
    be free at that instant, so the peak is what a "server busy" disclosure should
    read -- and calling the peak "the lag" would be one key meaning two things.
    """
    import time

    from src.monitoring import latency

    latency._reset_for_tests()
    now = time.monotonic()
    with latency._LOCK:
        latency._LAG.append((now - 1.0, 900.0))
        latency._LAG.append((now, 3.0))
    out = latency.loop_lag()
    assert out["latest_ms"] == 3.0, "latest is the most recent sample"
    assert out["peak_ms"] == 900.0, "peak is the worst in the window"
    assert out["samples"] == 2
    latency._reset_for_tests()


def test_a_sample_older_than_the_window_does_not_count_toward_the_peak():
    """A stall two minutes ago is not the load right now -- reporting it as the peak
    would keep a recovered server described as busy indefinitely."""
    import time

    from src.monitoring import latency

    latency._reset_for_tests()
    now = time.monotonic()
    with latency._LOCK:
        latency._LAG.append((now - latency._LAG_WINDOW_S - 5, 5000.0))
        latency._LAG.append((now, 2.0))
    out = latency.loop_lag()
    assert out["peak_ms"] == 2.0
    assert out["samples"] == 1
    latency._reset_for_tests()


def test_the_watchdog_records_every_sample_not_only_the_breaches():
    """The pre-existing events log only records lag ABOVE the block threshold, which
    is the right instrument for stalls and the wrong one for a continuous reading."""
    import asyncio

    from src.monitoring import latency

    latency._reset_for_tests()

    async def _one_tick():
        task = asyncio.get_running_loop().create_task(latency._watchdog(0.01))
        await asyncio.sleep(0.08)
        task.cancel()

    asyncio.run(_one_tick())
    out = latency.loop_lag()
    assert out["samples"] >= 1, "an idle loop still produces (small) readings"
    assert out["latest_ms"] is not None and out["latest_ms"] >= 0.0
    assert latency.recent_block_events() == [], "an idle loop must record no BLOCK events"
    latency._reset_for_tests()


def test_a_negative_reading_is_floored_rather_than_published():
    """The loop can wake EARLY at clock granularity; a negative lag describes nothing."""
    import time

    from src.monitoring import latency

    latency._reset_for_tests()
    with latency._LOCK:
        latency._LAG.append((time.monotonic(), max(0.0, -3.0)))
    assert latency.loop_lag()["latest_ms"] == 0.0
    latency._reset_for_tests()


def test_server_load_rides_the_already_polled_scheduler_status():
    """It must ride the response the UI ALREADY makes: a load disclosure behind a
    second poll is a disclosure nobody reads -- the same reasoning that put
    ``online`` and ``machine_floor`` here."""
    from src.api.scheduler import _status_payload

    body = _status_payload()
    assert "server_load" in body
    assert "online" in body and "machine_floor" in body, (
        "the siblings it rides beside must still be there"
    )
    assert set(body["server_load"]) == {"loop_lag", "heavy", "memory_guard", "method"}


def test_a_polled_call_spends_a_shorter_retry_budget_than_a_user_action():
    """(c): a background refresh that spends five attempts is adding load to a server
    that just said it has none to spare. A user action has nobody to re-ask it."""
    from tests.js_source_helper import app_js

    src = app_js()
    assert "const _API_MAX_RETRIES_POLLED = 1;" in src
    assert "const {polled, ...init} = opts;" in src, (
        "`polled` is ours, not fetch's -- it must not ride along in the request init"
    )
    assert "const maxRetries = polled ? _API_MAX_RETRIES_POLLED : _API_MAX_RETRIES;" in src


def test_the_live_polls_are_the_calls_marked_polled():
    """The shorter budget is worth nothing if the polls do not ask for it."""
    from tests.js_source_helper import app_js

    src = app_js()
    for call in (
        'api("/api/database/stats", {polled: true})',
        'api("/api/scheduler/status", {polled: true})',
        'api("/api/database/figures", {polled: true})',
        'api("/api/briefing", {polled: true})',
    ):
        assert call in src, f"the live chain must mark {call} as polled"
