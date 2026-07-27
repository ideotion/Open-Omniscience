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
