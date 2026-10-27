"""A rollup build that dies because the corpus file was replaced under it keeps no hold (R172's hold is for a build that failed on its own corpus).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT (item 1 of the 0.5.1 follow-ons; reproduced 2026-10-27 with ``/mnt/project-files/keyword-lane/swap-midbuild-repro.py``). A restore, a
repair or an encryption in place swaps the corpus file under the generation guard (``library_generation.swap_window``), which refuses every
connection made before it. A rollup build holds one session for its whole run and takes no corpus lease, so the swap does not wait for it: the
swap returned in 0.00 s with the build in flight, the build's next statement raised ``StaleLibraryError`` and the dispatcher kept a
``build-failed`` hold. The hold read the epoch and the mention count AFTER the swap, so they were the NEW corpus's, and the wall-branch release
(a larger limit, offload newly allowed, a materially smaller corpus) cannot fire for a restored corpus of the same size: the keyword rollup stayed
off until the app was restarted, for a reason that was not about the corpus it would read now.

WHAT THIS FILE HOLDS. (1) A REAL swap through the generation guard raises something ``_library_replaced`` accepts, so the recogniser is tied to the
exception the guard raises and not to a copy of its name. (2) The dispatcher, handed that same real exception, keeps no hold for it, says why in ``last_decline``, and the next
request builds. (3) Any other error still holds (the R172 tests stay the authority on that; one case is repeated here so a recogniser that
accepts everything fails in this file).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from src.analytics import rollup_hold, rollup_serve
from src.database import library_generation as gen


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rollup_serve, "_affordability_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_memory_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_last_build_verdict", lambda: None)
    monkeypatch.setattr(rollup_serve, "_persisted_serve_active", lambda: False)
    monkeypatch.setattr(rollup_serve, "_current_epoch", lambda: 7)
    monkeypatch.setattr(rollup_serve, "_current_mention_count", lambda: 1000)
    monkeypatch.setattr(rollup_serve, "_duckdb_limit_mb", lambda: 1004.0)
    monkeypatch.setattr(
        rollup_serve, "_build_budget", lambda: {"duckdb_limit_mb": 1004.0, "offload_allowed": False}
    )
    keep = {
        k: rollup_serve._STATE.get(k)
        for k in (
            "stopped",
            "failures",
            "failure_class",
            "last_outcome",
            "last_decline",
            "last_skip",
        )
    }
    rollup_serve._STATE.update(
        stopped=None,
        failures=0,
        failure_class=None,
        last_outcome=None,
        last_decline=None,
        last_skip=None,
    )
    rollup_serve._STATE.pop("last_outcome_restored", None)
    monkeypatch.setattr(rollup_serve, "_HOLD_LOOKED", False)
    yield
    rollup_serve._STATE.update(keep)
    rollup_serve._STATE.pop("last_outcome_restored", None)


def _run(monkeypatch, builds, *, raises=None, stage="aggregate"):
    def build():
        builds.append(1)
        rollup_serve._LAST_STAGE["value"] = stage
        if raises is not None:
            raise raises
        return None

    monkeypatch.setattr(rollup_serve, "_build_inmemory_and_swap", build)
    assert rollup_serve._BUILD_LOCK.acquire(blocking=False)
    return rollup_serve._build_and_swap()


def _store(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    con.execute("INSERT INTO notes (body) VALUES ('before')")
    con.commit()
    con.close()


def _the_exception_a_real_swap_raises(tmp_path: Path) -> BaseException:
    """What a build's session meets: a connection opened before the swap, used after it."""
    live = tmp_path / "live.db"
    _store(live)
    engine = create_engine(
        f"sqlite:///{live}",
        creator=gen.guarded_creator(lambda: sqlite3.connect(str(live), check_same_thread=False)),
    )
    gen.attach(engine)
    try:
        with engine.connect() as conn:
            # the build's first read: on the file that is about to be set aside
            conn.execute(text("select count(*) from notes")).scalar()
            new = tmp_path / "new.db"
            _store(new)
            with gen.swap_window(new):
                gen.disk_changing()
                for suffix in ("-wal", "-shm"):
                    Path(str(live) + suffix).unlink(missing_ok=True)
                os.replace(new, live)
            try:
                # its next read, after the swap
                conn.execute(text("select count(*) from notes")).scalar()
            except Exception as exc:  # noqa: BLE001 - this IS the exception under test
                return exc
        raise AssertionError("a statement on a connection from before the swap ran")
    finally:
        engine.dispose()


def test_a_real_swap_raises_what_the_recogniser_accepts(tmp_path):
    exc = _the_exception_a_real_swap_raises(tmp_path)
    assert rollup_serve._library_replaced(exc), (
        f"{type(exc).__name__} from a real swap is not recognised"
    )


def test_a_cause_chain_is_followed_and_other_errors_are_not_accepted():
    inner = gen.StaleLibraryError("x")
    try:
        try:
            raise inner
        except gen.StaleLibraryError as e:
            raise ValueError("wrapped") from e
    except ValueError as wrapped:
        assert rollup_serve._library_replaced(wrapped)
    assert not rollup_serve._library_replaced(RuntimeError("the build ran out of something"))
    assert not rollup_serve._library_replaced(ValueError("x"))


def test_a_build_the_swap_killed_keeps_no_hold_and_the_next_request_builds(monkeypatch, tmp_path):
    builds: list[int] = []
    # The exception is the one a REAL swap through the generation guard raised on a connection that predates it, not one built by hand.
    assert _run(monkeypatch, builds, raises=_the_exception_a_real_swap_raises(tmp_path)) == "failed"

    assert rollup_serve._STATE["stopped"] is None, (
        "a hold was kept for a build that never read the new corpus"
    )
    assert rollup_hold.read() is None
    last = rollup_serve._STATE["last_decline"]
    assert (
        last["reason"] == "library-replaced"
        and last["kind"] == "failed"
        and last["stage"] == "aggregate"
    )
    assert rollup_serve.decline_detail()["reason"] == "library-replaced", (
        "the boot step's row would not say why"
    )
    st = rollup_serve.status()
    assert st["last_decline"]["reason"] == "library-replaced"
    assert "consecutive_failures" not in st, (
        "a swap is not a failure of the build's own: the run of failures stays at 0"
    )

    assert _run(monkeypatch, builds) == "built"
    assert len(builds) == 2, "the next request did not start a build"


def test_any_other_error_still_holds(monkeypatch):
    builds: list[int] = []
    assert _run(monkeypatch, builds, raises=RuntimeError("something about the corpus")) == "failed"
    assert rollup_serve._STATE["stopped"]["reason"] == "build-failed"
    assert _run(monkeypatch, builds) == "declined"
    assert len(builds) == 1
