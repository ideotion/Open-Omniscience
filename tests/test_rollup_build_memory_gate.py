"""
S3.5 (2026-09-02 crash analysis): the auto-on rollup build declines under pressure.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A whole-corpus rollup build is one of the largest transient allocations the app
makes, and it was kicked by a background timer with no reference to the machine.

Three directions, because two of them are ways a "fix" reads as conservative
while being wrong: refusing a build on a machine that never measured anything
(every core install, where psutil is absent), and refusing an OPERATOR who asked
for a build explicitly.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean_skip():
    from src.analytics import rollup_serve

    rollup_serve._STATE["last_skip"] = None
    yield
    rollup_serve._STATE["last_skip"] = None


class _Guard:
    """Stands in for memory_guard. `engaged` is a PROPERTY on the real object, and
    getting that wrong is how the first version of a sibling section published a
    quiet all-clear for a TypeError, so the double mirrors it exactly."""

    def __init__(self, engaged: bool, *, readings=True, reason="available 94 MB"):
        self._engaged = engaged
        self._readings = readings
        self._reason = reason

    @property
    def engaged(self) -> bool:
        return self._engaged

    def reset(self, *, reason: str = "user action") -> None:
        # conftest's isolation fixture calls this on the live object; a double that
        # omits it errors at teardown, which is the recorded double-drift trap.
        self._engaged = False

    def state(self) -> dict:
        return {
            "engaged": self._engaged,
            "reason": self._reason,
            "last_reading": {"mem_avail_mb": 94.0, "rss_frac_pct": 71.2},
            "readings_available": self._readings,
        }


def _patch(monkeypatch, guard):
    import src.scheduler.memguard as mg

    monkeypatch.setattr(mg, "memory_guard", guard)


def test_an_engaged_guard_stops_the_background_build_and_says_so(monkeypatch):
    from src.analytics import rollup_serve

    _patch(monkeypatch, _Guard(True))
    built: list[int] = []
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setattr(
        rollup_serve, "_build_inmemory_and_swap", lambda: built.append(1)
    )

    rollup_serve._BUILD_LOCK.acquire()
    rollup_serve._build_and_swap()  # releases the lock in its finally

    assert built == [], "the whole-corpus build ran while the guard was engaged"
    skip = rollup_serve._STATE["last_skip"]
    assert skip is not None, "it declined silently — a skip nobody can see is a no-op"
    assert skip["reason"] == "mem-low"
    # The guard's OWN readings, never a number this module measured for itself.
    assert skip["last_reading"]["mem_avail_mb"] == 94.0
    assert skip["guard_reason"] == "available 94 MB"
    assert not rollup_serve._BUILD_LOCK.locked(), "the build lock was not released"


def test_a_healthy_machine_still_builds(monkeypatch):
    """The twin. A gate that declined always would pass the test above."""
    from src.analytics import rollup_serve

    _patch(monkeypatch, _Guard(False))
    built: list[int] = []
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setattr(
        rollup_serve, "_build_inmemory_and_swap", lambda: built.append(1)
    )

    rollup_serve._BUILD_LOCK.acquire()
    rollup_serve._build_and_swap()

    assert built == [1], "a healthy machine was refused its rollup"
    assert rollup_serve._STATE["last_skip"] is None


def test_a_guard_with_no_readings_is_blind_and_is_not_treated_as_pressure(monkeypatch):
    """The honest direction on an absent measurement. psutil is an optional extra,
    so on a core install the guard reports engaged=False with no readings at all —
    declining there would refuse the build on every such install forever."""
    from src.analytics import rollup_serve

    _patch(monkeypatch, _Guard(False, readings=False))
    built: list[int] = []
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setattr(
        rollup_serve, "_build_inmemory_and_swap", lambda: built.append(1)
    )

    rollup_serve._BUILD_LOCK.acquire()
    rollup_serve._build_and_swap()

    assert built == [1]
    assert rollup_serve._STATE["last_skip"] is None


def test_an_unreadable_guard_never_blocks_the_build(monkeypatch):
    """`engaged` is a property; a version that called it raised TypeError. The gate
    must fall through to building rather than turning its own bug into a permanent
    refusal — and this is exactly the case a bare `except` would have hidden."""
    from src.analytics import rollup_serve

    class _Broken:
        @property
        def engaged(self):
            raise RuntimeError("cannot read the guard")

        def reset(self, *, reason: str = "user action") -> None:
            return None

    _patch(monkeypatch, _Broken())
    built: list[int] = []
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setattr(
        rollup_serve, "_build_inmemory_and_swap", lambda: built.append(1)
    )

    rollup_serve._BUILD_LOCK.acquire()
    rollup_serve._build_and_swap()
    assert built == [1]


def test_the_skip_rides_the_columnar_diagnostics_member(monkeypatch):
    """A disclosure nothing publishes is not a disclosure."""
    from src.analytics import rollup_serve

    assert rollup_serve.status()["last_skip"] is None
    rollup_serve._STATE["last_skip"] = {"reason": "mem-low", "at": 1.0}
    assert rollup_serve.status()["last_skip"]["reason"] == "mem-low"


def test_the_double_matches_the_real_guards_surface():
    """A double that drifts from the class it stands in for describes a guard that
    could not exist, and then passes for a reason unrelated to its claim."""
    import inspect

    from src.scheduler.memguard import MemoryGuard

    real = MemoryGuard
    assert isinstance(inspect.getattr_static(real, "engaged"), property), (
        "`engaged` stopped being a property — the double, and the gate's own comment "
        "about why a bare except would hide a TypeError, are both now wrong"
    )
    for name in ("state", "reset"):
        assert inspect.signature(getattr(real, name)) == inspect.signature(
            getattr(_Guard, name)
        ), f"the double's {name}() no longer matches the real guard's"


def test_an_explicit_operator_build_is_never_refused():
    """The gate is on the AUTO path only. The rollup benchmark calls the builder
    directly, and an operator who asked for a build must get one — a deliberate
    action is not something to second-guess on a memory reading."""
    import inspect

    from src.analytics import columnar
    from src.monitoring import rollup_benchmark

    assert "_memory_verdict" not in inspect.getsource(columnar.build_keyword_daily)
    assert "build_keyword_daily" in inspect.getsource(rollup_benchmark)
