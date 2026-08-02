"""A boot step must not revoke an operator's explicit decision to go online.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-08-02: "sometimes, when I install the app on a new instance ... the
app remains in airplane mode with no explanation", intermittently.

Airplane-at-boot is engaged TWICE on the unlock path: synchronously in unlock.py (so
there is never a window where the corpus is open and the socket guard is not), and
again at the tail of _run_startup_upkeep -- which on that path runs in a BACKGROUND
THREAD. A new instance's upkeep is slow (catalog seed, ANALYZE, counts, cache warm),
so the first-launch wizard is on screen for its whole duration. Cross online in that
window and the thread's activate_kill_switch() lands AFTER the operator's
clear_kill_switch(), silently putting the app back in airplane mode: the POST had
already returned online:true, so nothing reported it, and the 5 s poll just repainted
the button. Intermittent by construction -- it depends purely on whether the click
beat the thread.

The zero-network-boot NON-NEGOTIABLE is untouched and is pinned here too: a boot with
no operator decision still engages airplane unconditionally.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from src import ingest as I

# Imported ONCE, at module scope: src.api.main registers Prometheus collectors at import
# time, so a second import inside a test body raises DuplicateTimeseries. It is also
# unimportable in a bare sandbox (the guarded fetch factory pulls in cryptography, whose
# pyo3 extension panics there), so the boot-path tests skip rather than error and CI --
# which has the full install -- is what actually runs them. The FLAG's own behaviour is
# pure and always runs, here and everywhere.
try:
    from src.api import main as M
except BaseException:  # noqa: BLE001 - cryptography's pyo3 extension PANICS in a bare
    # sandbox, and a pyo3 PanicException inherits BaseException, so `except Exception`
    # does not catch it and collection aborts for the whole file.
    M = None

_needs_main = pytest.mark.skipif(M is None, reason="src.api.main is unimportable here (CI runs it)")


@pytest.fixture(autouse=True)
def _reset():
    I._reset_crossed_online_for_tests()
    I.activate_kill_switch()
    yield
    I._reset_crossed_online_for_tests()
    I.activate_kill_switch()


def test_a_fresh_process_has_taken_no_online_decision():
    assert I.crossed_online_since_boot() is False


def test_crossing_online_is_remembered_as_a_DECISION_not_a_state():
    """It must survive going offline again: the flag records that the operator has
    taken control of the network mode in this process, which is precisely what a late
    boot step must not overwrite. If it merely mirrored the current state, an operator
    who went online and then deliberately offline would re-arm the clobber."""
    I.clear_kill_switch()
    assert I.crossed_online_since_boot() is True
    I.activate_kill_switch()
    assert I.kill_switch_active() is True
    assert I.crossed_online_since_boot() is True, (
        "the decision is remembered even after a later, deliberate go-offline"
    )


@_needs_main
def test_the_boot_engage_is_skipped_once_the_operator_has_crossed_online():
    """The exact interleaving from the field: unlock engages airplane, the upkeep
    thread starts, the operator crosses online, and only THEN does the thread reach
    its own airplane block."""
    os.environ.pop("OO_NO_SCHEDULER", None)
    I.clear_kill_switch()  # the operator's click, mid-upkeep
    assert I.kill_switch_active() is False

    with patch("src.ingest.airplane.install_airplane_socket_guard"):
        M._run_startup_upkeep()

    assert I.kill_switch_active() is False, (
        "the background upkeep silently put the app back in airplane mode, revoking a "
        "decision the operator had already made and been told succeeded"
    )


@_needs_main
def test_a_boot_with_no_operator_decision_STILL_engages_airplane():
    """The negative-space twin, and the load-bearing one: zero-network boot is a
    non-negotiable. Skipping the engage whenever the switch happens to be clear would
    turn a first boot into an ONLINE boot."""
    os.environ.pop("OO_NO_SCHEDULER", None)
    I._KILL.clear()  # clear the STATE without recording a decision
    assert I.crossed_online_since_boot() is False

    with patch("src.ingest.airplane.install_airplane_socket_guard"):
        M._run_startup_upkeep()

    assert I.kill_switch_active() is True, "a boot with no operator decision boots OFFLINE"


@_needs_main
def test_the_socket_guard_is_installed_either_way():
    """The guard is a no-op while online and is exactly what must already be in place
    if the operator goes offline later, so only the ENGAGE is conditional."""
    import inspect

    src = inspect.getsource(M)
    body = src.split("def _run_startup_upkeep(", 1)[1]
    guard = body.index("install_airplane_socket_guard()")
    cond = body.index("if crossed_online_since_boot():")
    assert guard < cond, "the guard must be installed before the conditional engage"
