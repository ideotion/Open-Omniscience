"""The time-driven backstop for pre-restore-*.db safety-net snapshots.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-07-26 hardware diagnostics W5: src.backup.merge._prune_snapshots (the
existing count-based "keep newest 3" policy) only ever fires as a SIDE EFFECT
of a LATER restore -- a long-lived instance where restores happened in a
burst and then stopped keeps all of them forever (the diagnosed 97.8 GB: 3
restores within 36 hours, then none). prune_pre_restore_snapshots_by_age is
the time-driven complement: age is read from the file's OWN embedded
timestamp (never filesystem mtime), and a snapshot currently registered as
"active" (an in-flight restore's own, still-running commit tail) is NEVER
touched regardless of age -- the structural double-guard that makes it
impossible, not merely unlikely, for the sweep to race a still-running
restore.

Pure filesystem unit tests -- data_dir() is already process-wide isolated
per tests/conftest.py, so no app boot / DB session is needed here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.backup.merge import prune_pre_restore_snapshots_by_age
from src.backup.stream_backup import active_staging
from src.paths import data_dir


def _make_snapshot(age_hours: float):
    ts = (datetime.now(UTC) - timedelta(hours=age_hours)).strftime("%Y%m%dT%H%M%SZ")
    p = data_dir() / f"pre-restore-{ts}.db"
    p.write_bytes(b"fake corpus bytes")
    return p


def test_an_active_in_progress_restores_own_snapshot_is_never_swept_even_far_past_the_age_cutoff():
    """The REQUIRED negative case: an old-but-active snapshot is never removed
    regardless of how aggressive the configured threshold is -- proves the
    structural double-guard, not just the age arithmetic."""
    stale_but_active = _make_snapshot(age_hours=24 * 10)  # 10 days old
    with active_staging(stale_but_active):
        removed = prune_pre_restore_snapshots_by_age(max_age_hours=1)  # aggressive threshold
        assert stale_but_active.name not in removed
        assert stale_but_active.exists()
    # Once the guard is released (the commit tail finished), the SAME
    # still-aged file is fair game on its own merits.
    removed_after = prune_pre_restore_snapshots_by_age(max_age_hours=1)
    assert stale_but_active.name in removed_after
    assert not stale_but_active.exists()


def test_age_sweep_only_removes_snapshots_past_the_threshold_and_ignores_unrecognized_names():
    old = _make_snapshot(age_hours=200)  # past a 168h default
    borderline = _make_snapshot(age_hours=1)  # well within the window
    garbage = data_dir() / "pre-restore-not-a-real-timestamp.db"
    garbage.write_bytes(b"junk")

    removed = prune_pre_restore_snapshots_by_age(max_age_hours=168)

    assert old.name in removed
    assert not old.exists()
    assert borderline.exists()
    assert garbage.exists()  # unrecognized shape -- never guessed, never touched


def test_default_threshold_is_168_hours_when_unspecified(monkeypatch):
    """The 7-day default (a judgment call, operator-tunable) applies when the
    caller doesn't pass an explicit max_age_hours."""
    just_under = _make_snapshot(age_hours=167)
    just_over = _make_snapshot(age_hours=169)

    removed = prune_pre_restore_snapshots_by_age()  # no explicit threshold

    assert just_under.exists()
    assert just_over.name in removed
    assert not just_over.exists()


def test_env_var_override_is_honoured(monkeypatch):
    """OO_PRE_RESTORE_SNAPSHOT_MAX_AGE_HOURS -- the same env-var idiom as
    _incremental_vacuum_hours()/_maint_interval_s() elsewhere in this
    codebase."""
    snap = _make_snapshot(age_hours=2)
    monkeypatch.setenv("OO_PRE_RESTORE_SNAPSHOT_MAX_AGE_HOURS", "1")

    removed = prune_pre_restore_snapshots_by_age()  # reads the env override

    assert snap.name in removed
    assert not snap.exists()


def test_a_malformed_env_value_degrades_to_the_default_rather_than_raising(monkeypatch):
    fresh = _make_snapshot(age_hours=1)  # well within the 168h default
    monkeypatch.setenv("OO_PRE_RESTORE_SNAPSHOT_MAX_AGE_HOURS", "not-a-number")

    removed = prune_pre_restore_snapshots_by_age()  # must not raise

    assert fresh.exists()
    assert removed == []


def test_a_non_finite_or_absurdly_large_hours_value_degrades_to_the_default_rather_than_crashing():
    """Skeptic-found (config-abuse / negative-space lens, 2026-07-26): float()
    happily parses "inf"/"nan"/"1e300" without raising, so they sail PAST
    _snapshot_max_age_hours()'s bare `except ValueError` -- the crash (if
    any) happens one level down, constructing/subtracting the timedelta. A
    misconfigured env var (or a bad explicit caller) must never permanently
    and silently disable this safety net by crashing it on every call.
    (``-inf`` is covered separately below -- it is caught by the max(0.0, ..)
    clamp BEFORE it ever reaches this except branch, since -inf < 0.)"""
    old = _make_snapshot(age_hours=200)  # past the 168h default
    fresh = _make_snapshot(age_hours=1)  # well within the 168h default

    for bad in (float("inf"), float("nan"), 1e300, 1e10):
        removed = prune_pre_restore_snapshots_by_age(max_age_hours=bad)  # must not raise
        # falls back to the 168h default cutoff, exactly as an unset/malformed
        # env var would -- the old one is swept, the fresh one is untouched.
        assert old.name in removed
        assert fresh.exists()
        old = _make_snapshot(age_hours=200)  # recreate for the next iteration


def test_negative_or_negative_infinite_hours_clamps_to_zero_rather_than_sweeping_the_future():
    """Skeptic-found (config-abuse lens, 2026-07-26): an UNCLAMPED negative
    ``hours`` produces a cutoff in the FUTURE (``now() - timedelta(hours=-5)
    == now() + 5h``), which is MORE aggressive than max_age_hours=0 -- it
    would sweep even a snapshot created moments ago (before the active-staging
    guard has a chance to matter, in principle). Clamped to 0.0, a negative or
    -inf value degrades to exactly max_age_hours=0's already-safe behaviour:
    everything NOT currently active gets swept (nothing is spared by age),
    but nothing from the FUTURE is ever implied."""
    for bad in (-5.0, -0.001, float("-inf")):
        old = _make_snapshot(age_hours=200)
        fresh = _make_snapshot(age_hours=0.5)  # 30 minutes old -- a real backstop would spare it

        removed = prune_pre_restore_snapshots_by_age(max_age_hours=bad)  # must not raise

        assert old.name in removed
        assert fresh.name in removed  # clamped to 0, not "spared" like a real backstop


def test_a_zero_hours_value_is_unchanged_and_still_governed_by_active_staging():
    """max_age_hours=0 was already a defined, tested value (cutoff=now(),
    sweep everything not currently active) -- this pins that the new
    max(0.0, hours) clamp is a genuine no-op for 0 itself (0.0 == max(0.0,
    0.0)), and that the active-staging guard is still what protects an
    in-flight restore's own snapshot even at this most-aggressive setting."""
    from src.backup.stream_backup import active_staging

    stale_but_active = _make_snapshot(age_hours=24 * 10)
    with active_staging(stale_but_active):
        removed = prune_pre_restore_snapshots_by_age(max_age_hours=0)
        assert stale_but_active.name not in removed
        assert stale_but_active.exists()


def test_a_non_finite_env_var_string_degrades_to_the_default_rather_than_crashing(monkeypatch):
    """The SAME failure mode, reached through the env-var path rather than an
    explicit caller -- OO_PRE_RESTORE_SNAPSHOT_MAX_AGE_HOURS="inf"/"nan" are
    valid float() strings, so _snapshot_max_age_hours() returns them as-is."""
    old = _make_snapshot(age_hours=200)
    fresh = _make_snapshot(age_hours=1)
    monkeypatch.setenv("OO_PRE_RESTORE_SNAPSHOT_MAX_AGE_HOURS", "nan")

    removed = prune_pre_restore_snapshots_by_age()  # must not raise

    assert old.name in removed
    assert fresh.exists()


def test_run_idle_maintenance_wires_the_pre_restore_snapshot_sweep(monkeypatch):
    """Closes the 'shipped the function but forgot to wire it' gap this
    project has hit before -- a wiring test, not just a unit test of the
    function in isolation."""
    from src.database.session import init_db
    from src.scheduler import maintenance as maint_mod

    init_db()
    called = {}

    def _fake_sweep(*a, **kw):
        called["ran"] = True
        return ["pre-restore-fake.db"]

    monkeypatch.setattr("src.backup.merge.prune_pre_restore_snapshots_by_age", _fake_sweep)
    out = maint_mod.run_idle_maintenance()
    assert called.get("ran") is True
    assert out["pre_restore_snapshot_sweep"]["removed"] == ["pre-restore-fake.db"]


def test_a_failing_sweep_never_breaks_the_rest_of_the_idle_maintenance_cycle(monkeypatch):
    from src.database.session import init_db
    from src.scheduler import maintenance as maint_mod

    init_db()

    def _boom(*a, **kw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr("src.backup.merge.prune_pre_restore_snapshots_by_age", _boom)
    out = maint_mod.run_idle_maintenance()  # must not raise
    assert out["pre_restore_snapshot_sweep"] == {"skipped": "error"}
    # the sibling steps still ran -- proves the loop continued past the
    # failing sweep rather than aborting the whole idle window.
    assert "cleanup" in out
    assert "country_rollup" in out
