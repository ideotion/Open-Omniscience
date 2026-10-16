"""Encrypting in place owns the machine, so the storage guard's drain cannot open the live path while the file is swapped.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE GAP. ``encrypt_all`` swaps the corpus file under the write gate. Until now the gate was also what kept the storage guard's drain out:
the drain asked for it, waited up to 30 s and gave up. A drain whose passive step needs no gate (the next change) would have opened a
connection to the plaintext path in the middle of the swap, and a log of the old file beside the new one is a corrupt store. The route
never claimed ``owns_the_machine()``, which is what ``drain_if_due`` declines on.

THE GUARD. ``/api/system/encrypt-db`` runs inside an exclusive window (opened BEFORE the pool is disposed, closed after the keyed pool is
back) and then waits, bounded, for the leases of work already in flight (a drain, a re-index batch), refusing by name when they do not end.
The drain asks AGAIN once it holds its own lease, so a window that opens between its first ask and its lease is still seen: lease first,
then ask. Four kinds of test, each red without the part it names: the machine is owned for every step of the route, the drain declines
inside it, the window closes however the route ends, and the wait for work in flight is real and bounded.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi import HTTPException

from src.api import unlock as unlock_mod
from src.database import connect as connect_mod
from src.database import corpus_lease, encrypt_tool
from src.scheduler import runner
from src.scheduler.storage_guard import GIB, StorageGuard

_KEY = "a-long-enough-passphrase-for-the-test-9Q"


@pytest.fixture(autouse=True)
def _guard_enabled(monkeypatch):
    monkeypatch.setenv("OO_STORAGE_GUARD", "1")
    monkeypatch.setattr(runner, "_ensure_storage_supervisor", lambda: None)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _pinned_guard(drain_calls: list) -> StorageGuard:
    """A guard whose log latch is engaged and whose drain is a recorder, so a drain that runs is a call in ``drain_calls``."""
    g = StorageGuard(clock=Clock(), trip_after=2, resume_after=2, drain_fn=lambda: drain_calls.append(1) or {"busy": 0})
    for _ in range(2):
        g.observe(wal_bytes=2 * GIB, corpus_bytes=10 * GIB, disk_free_bytes=300 * GIB, disk_total_bytes=500 * GIB)
    assert g.engaged
    return g


@pytest.fixture
def route(monkeypatch):
    """The encrypt route with its heavy parts replaced by recorders; ``events`` holds what each step saw of ownership."""
    events: list[tuple[str, bool]] = []

    def seen(step):
        events.append((step, runner.owns_the_machine()))

    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-plaintext")
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: seen("dispose"))
    monkeypatch.setattr(connect_mod, "set_passphrase", lambda p: seen("set_passphrase"))
    return events


def _body():
    return unlock_mod.EncryptBody(passphrase=_KEY, confirm=_KEY, consent=True)


def test_the_machine_is_owned_for_every_step_of_the_route_and_not_before_or_after(monkeypatch, route):
    """Before the pool is disposed, while the file is swapped, while the keyed pool is installed and disposed again: owned. Before and
    after the route: not. RED WITHOUT the window: every step reads False."""
    monkeypatch.setattr(encrypt_tool, "encrypt_all", lambda key: route.append(("encrypt_all", runner.owns_the_machine())) or {})
    assert runner.owns_the_machine() is False
    unlock_mod.encrypt_db(_body())
    assert route == [("dispose", True), ("encrypt_all", True), ("set_passphrase", True), ("dispose", True)]
    assert runner.owns_the_machine() is False, "the window closes with the route"


def test_a_drain_that_is_due_while_the_file_is_swapped_does_not_run(monkeypatch, route):
    """The storage guard ticks inside ``encrypt_all`` (the file is mid-swap): no drain, and nothing stamped, so the drain runs at once
    when the route ends. RED WITHOUT the window: the drain runs and the file is opened under the swap."""
    drains: list = []
    g = _pinned_guard(drains)
    ticks: list = []

    def encrypt(key):
        ticks.append(g.drain_if_due())
        return {}

    monkeypatch.setattr(encrypt_tool, "encrypt_all", encrypt)
    unlock_mod.encrypt_db(_body())
    assert ticks == [None] and drains == [], "a drain ran while the file was being replaced"
    assert g.drain_if_due() is not None and drains == [1], "nothing was stamped, so the drain runs as soon as the machine is free"


def test_the_window_closes_however_the_route_ends(monkeypatch, route):
    """A refused key, an engine failure and an exit that is not an Exception all leave the machine free. RED WITHOUT the ``finally`` of the
    window: the first later restore or drain finds the machine owned for ever."""

    def refused(key):
        raise encrypt_tool.EncryptToolError("not encrypted")

    monkeypatch.setattr(encrypt_tool, "encrypt_all", refused)
    with pytest.raises(HTTPException) as err:
        unlock_mod.encrypt_db(_body())
    assert err.value.status_code == 400
    assert runner.owns_the_machine() is False

    def broken(key):
        raise RuntimeError("the engine failed")

    monkeypatch.setattr(encrypt_tool, "encrypt_all", broken)
    with pytest.raises(Exception):  # noqa: B017 - the route converts it; the class is not the point here
        unlock_mod.encrypt_db(_body())
    assert runner.owns_the_machine() is False

    def interrupted(key):
        raise KeyboardInterrupt

    monkeypatch.setattr(encrypt_tool, "encrypt_all", interrupted)
    with pytest.raises(KeyboardInterrupt):
        unlock_mod.encrypt_db(_body())
    assert runner.owns_the_machine() is False


def test_work_already_in_flight_finishes_before_the_file_is_touched(monkeypatch, route):
    """A drain (or a re-index batch) that holds its lease when the route starts is waited for: ``encrypt_all`` finds no lease. RED WITHOUT
    the wait: it starts under the lease."""
    monkeypatch.setattr(unlock_mod, "ENCRYPT_QUIESCE_S", 10.0)
    leases_seen: list = []
    monkeypatch.setattr(encrypt_tool, "encrypt_all", lambda key: leases_seen.append(corpus_lease.active_leases()) or {})
    inside = threading.Event()
    release = threading.Event()

    def drain():
        with corpus_lease.corpus_lease("storage-guard-drain"):
            inside.set()
            release.wait(10)

    t = threading.Thread(target=drain, name="oo-drain")
    t.start()
    assert inside.wait(5)
    threading.Timer(0.6, release.set).start()
    t0 = time.monotonic()
    unlock_mod.encrypt_db(_body())
    t.join(10)
    assert leases_seen == [[]], f"the file was touched under a lease: {leases_seen}"
    assert time.monotonic() - t0 >= 0.5, "the route did not wait for the lease"


def test_work_that_does_not_end_is_a_named_refusal_and_nothing_is_touched(monkeypatch, route):
    """After the bounded wait the route answers 409 and names the lease; nothing was disposed, swapped or keyed, and the machine is free.
    RED WITHOUT the refusal: the file is swapped under the lease or the route waits for ever."""
    monkeypatch.setattr(unlock_mod, "ENCRYPT_QUIESCE_S", 0.3)
    called: list = []
    monkeypatch.setattr(encrypt_tool, "encrypt_all", lambda key: called.append(1) or {})
    t0 = time.monotonic()
    with corpus_lease.corpus_lease("storage-guard-drain"), pytest.raises(HTTPException) as err:
        unlock_mod.encrypt_db(_body())
    assert time.monotonic() - t0 < 3.0, "the wait is bounded by ENCRYPT_QUIESCE_S, not by anything else"
    assert err.value.status_code == 409
    assert "storage-guard-drain" in err.value.detail and "nothing was encrypted" in err.value.detail
    assert _KEY not in err.value.detail
    assert called == [] and route == [], "a refused route touched the pool or the file"
    assert runner.owns_the_machine() is False


def test_a_drain_that_asked_before_the_window_opened_asks_again_under_its_lease(monkeypatch):
    """``drain_if_due`` read the machine as free; an encryption opened its window before the drain took its lease. The drain's second
    ask, under the lease, sees the window and runs nothing and stamps nothing. RED WITHOUT the second ask: the drain runs."""
    answers = iter([False, True])
    monkeypatch.setattr(runner, "owns_the_machine", lambda: next(answers, True))
    drains: list = []
    g = _pinned_guard(drains)
    assert g.drain_if_due() is None
    assert drains == []
    assert g.state()["last_drain"] is None or g.state()["last_drain"].get("ran") is not True
    monkeypatch.setattr(runner, "owns_the_machine", lambda: False)
    assert g.drain_if_due() is not None and drains == [1], "the declined drain stamped the cadence"


def test_the_drain_holds_its_lease_while_it_asks_so_the_wait_of_an_exclusive_operation_sees_it(monkeypatch):
    """The other half of lease-first-then-ask: the second ask happens INSIDE the lease. A lease taken after the ask would let an
    encryption's wait find nothing while a drain is about to start."""
    held_at_ask: list = []

    def ask():
        held_at_ask.append(corpus_lease.active_leases())
        return len(held_at_ask) > 1  # the first ask finds the machine free; the second, under the lease, finds it owned

    monkeypatch.setattr(runner, "owns_the_machine", ask)
    g = _pinned_guard([])
    g.drain_if_due()
    assert held_at_ask == [[], ["storage-guard-drain"]], held_at_ask
