"""A rollup build that runs on across a corpus swap without raising is refused at its next stage boundary (the follow-on to #1547, R303).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT (measured by the Opus read of #1547). The build commits between batches, which hands its connection back to the pool. The generation
guard refuses a stale connection at CHECKOUT with a ``DisconnectionError``, and the pool answers that by opening a fresh connection on the NEW
file, silently: select, commit, swap, select on one ORM session returns the new file's row. So a swap that lands between two batches (or in the
DuckDB-only aggregate stage, where no SQLite connection is held at all) raised nothing, the build went on reading the new corpus's keywords against
mentions staged from the old one, and the mixed rollup was swapped in.

THE FIX. ``_build_inmemory_and_swap`` reads ``library_generation.current()`` before its session reads a row; the build's per-batch hook compares it
with the guard's own ``valid`` first thing, at every stage boundary the build crosses (after each batch of mentions, when the aggregate begins and
after each shard of it, when the keywords stage begins and ends), and once more before the finished rollup is swapped in. A mismatch raises
``StaleLibraryError``, which #1547's branch already turns into "no hold, the next request rebuilds".

WHAT THIS FILE HOLDS. Each test uses a REAL swap through ``swap_window`` and ``os.replace`` on a guarded engine, and fails with the comparison removed
(``_require_library_unchanged`` made a no-op: run once that way, see the PR body).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.analytics import rollup_marker, rollup_serve
from src.database import library_generation as gen


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    # a real swap moves the process-wide generation: put it back, so the tests after this file meet the generation they began with
    for name in ("_GENERATION", "_VALID", "_WINDOW_STAMP", "_DISK_CHANGED"):
        monkeypatch.setattr(gen, name, getattr(gen, name))
    monkeypatch.setattr(rollup_serve, "_progress_note", lambda *a, **k: None)
    monkeypatch.setattr(rollup_marker, "progress", lambda *a, **k: None)
    monkeypatch.setattr(rollup_serve, "_readings", lambda: {"rss_mb": None, "avail_mb": None})


def _store(path: Path, body: str) -> None:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    con.execute("INSERT INTO notes (body) VALUES (?)", (body,))
    con.commit()
    con.close()


class _World:
    """A live corpus file under a guarded engine (as the app's is), a build's session on it, and the swap."""

    def __init__(self, tmp_path: Path):
        self.dir = tmp_path
        self.live = tmp_path / "live.db"
        _store(self.live, "OLD")
        self.engine = create_engine(
            f"sqlite:///{self.live}",
            creator=gen.guarded_creator(lambda: sqlite3.connect(str(self.live), check_same_thread=False)),
        )
        gen.attach(self.engine)
        self.session = Session(self.engine)

    def batch(self) -> str:
        """One batch the way the build reads it: a statement, its result closed, then the commit that hands the connection back."""
        result = self.session.execute(text("select body from notes"))
        body = result.fetchall()[0][0]
        result.close()
        self.session.commit()
        return body

    def swap(self) -> None:
        new = self.dir / "new.db"
        _store(new, "NEW")
        with gen.swap_window(new):
            gen.disk_changing()
            for suffix in ("-wal", "-shm"):
                Path(str(self.live) + suffix).unlink(missing_ok=True)
            os.replace(new, self.live)

    def close(self) -> None:
        self.session.close()
        self.engine.dispose()


@pytest.fixture()
def world(tmp_path):
    w = _World(tmp_path)
    yield w
    w.close()


def _raised(hook, stage: str, rows: int = 0) -> BaseException | None:
    try:
        hook(stage, rows)
    except BaseException as exc:  # noqa: BLE001 - this IS what is under test
        return exc
    return None


def test_a_swap_between_two_batches_raises_nothing_in_the_session_and_is_refused_by_the_hook(world):
    hook = rollup_serve._make_on_batch(gen.current())
    assert world.batch() == "OLD"
    assert _raised(hook, "mentions", 1) is None, "nothing has moved yet: the first batch's boundary passes"

    world.swap()

    # the gap the Opus read measured: the pool answers the guard's checkout refusal with a fresh connection on the NEW file, silently
    assert world.batch() == "NEW", "the session no longer meets the guard between batches: this test's premise is gone"

    exc = _raised(hook, "mentions", 2)
    assert isinstance(exc, gen.StaleLibraryError), f"the boundary after the swap raised {exc!r}"
    assert rollup_serve._library_replaced(exc)


def test_a_swap_in_the_aggregate_stage_is_refused_when_the_aggregate_and_the_keywords_stage_begin(world):
    hook = rollup_serve._make_on_batch(gen.current())
    assert world.batch() == "OLD"
    assert _raised(hook, "mentions", 1) is None

    world.swap()  # the DuckDB-only stage holds no SQLite connection: nothing in the session is even asked

    assert isinstance(_raised(hook, "aggregate", 0), gen.StaleLibraryError)
    assert isinstance(_raised(hook, "aggregate", 5000), gen.StaleLibraryError), "after each shard"
    assert isinstance(_raised(hook, "keywords", 0), gen.StaleLibraryError), "before the keywords are read from the new file"


def test_a_swap_during_the_final_checks_is_refused_before_the_rollup_is_swapped_in(world):
    stamp = gen.current()
    rollup_serve._require_library_unchanged(stamp)  # the last keywords batch passed; the compact and the serve check run now
    world.swap()
    with pytest.raises(gen.StaleLibraryError):
        rollup_serve._require_library_unchanged(stamp)


def test_no_swap_means_every_boundary_passes_and_a_swap_that_changed_nothing_gives_the_build_its_generation_back(world, tmp_path):
    hook = rollup_serve._make_on_batch(gen.current())
    for stage, rows in (("mentions", 1), ("mentions", 2), ("aggregate", 0), ("aggregate", 5000), ("keywords", 0), ("keywords", 9)):
        assert _raised(hook, stage, rows) is None, stage

    # a swap refused before it touched anything (the repair's data-version check): the file is the one the build began on
    _store(tmp_path / "never-moved.db", "NEW")
    with pytest.raises(RuntimeError, match="refused"), gen.swap_window(tmp_path / "never-moved.db"):
        raise RuntimeError("refused before anything changed")
    assert _raised(hook, "mentions", 3) is None, "the build was stopped for a swap that did not happen"


def test_a_build_with_no_stamp_is_not_checked(world):
    assert _raised(rollup_serve._make_on_batch(), "mentions", 1) is None
    world.swap()
    assert _raised(rollup_serve._make_on_batch(), "mentions", 2) is None  # a caller that passes no stamp (the benchmark's own hook) keeps its old behaviour


class _Con:
    def __init__(self):
        self.closed = False

    def execute(self, *_a, **_k):
        return self

    def fetchone(self):
        return (3,)

    def close(self):
        self.closed = True


def _stub_the_build(monkeypatch, world, *, swap_in: str):
    """The real ``_build_inmemory_and_swap`` with the engine, the marker and the session stubbed; the real swap lands at ``swap_in``."""
    from contextlib import contextmanager

    from src.analytics import columnar, serve_gate
    from src.database import session as app_session

    con = _Con()

    class _S:
        def get_bind(self):
            return "bind"

    @contextmanager
    def scope():
        yield _S()

    def build(con_, s, *, on_batch, snapshot):
        on_batch("mentions", 1)
        if swap_in == "between-batches":
            world.batch()
            world.swap()
            on_batch("mentions", 2)
        elif swap_in == "aggregate":
            world.swap()
            on_batch("aggregate", 0)
        return {"streamed_mentions": 2}

    def canary(_con):
        if swap_in == "final-checks":
            world.swap()
        return {"outcome": "ok"}

    monkeypatch.setattr(columnar, "budget_snapshot", lambda: {"duckdb_limit_mb": 1004.0, "duckdb_threads": 1, "total_mb": 4000.0, "read_at": 0.0})
    monkeypatch.setattr(columnar, "connect", lambda **_k: con)
    monkeypatch.setattr(columnar, "build_keyword_daily", build)
    monkeypatch.setattr(columnar, "compact", lambda _c: {"outcome": "ok"})
    monkeypatch.setattr(columnar, "serve_canary", canary)
    monkeypatch.setattr(rollup_marker, "begin", lambda **_k: True)
    monkeypatch.setattr(rollup_marker, "clear", lambda: None)
    monkeypatch.setattr(serve_gate, "change_token", lambda _s: (7, 1000))
    monkeypatch.setattr(app_session, "session_scope", scope)
    monkeypatch.setattr(rollup_serve, "_spill_setting", lambda: None)
    monkeypatch.setattr(rollup_serve, "_remove_spill", lambda _p: None)
    monkeypatch.setattr(rollup_serve, "_progress_begin", lambda: None)
    monkeypatch.setattr(rollup_serve, "_progress_end", lambda: None)
    monkeypatch.setattr(rollup_serve, "_remember_stage", lambda: None)
    monkeypatch.setattr(rollup_serve, "_count_in", lambda _s: 1000)
    monkeypatch.setitem(rollup_serve._STATE, "con", None)
    return con


@pytest.mark.parametrize("swap_in", ["between-batches", "aggregate", "final-checks"])
def test_the_build_is_stopped_and_nothing_is_swapped_in_when_the_swap_lands_at_each_boundary(monkeypatch, world, swap_in):
    con = _stub_the_build(monkeypatch, world, swap_in=swap_in)
    with pytest.raises(gen.StaleLibraryError):
        rollup_serve._build_inmemory_and_swap()
    assert rollup_serve._STATE["con"] is None, "a rollup no corpus produced was swapped in"
    assert con.closed, "the connection of a build that was stopped leaked"


def test_a_build_with_no_swap_is_swapped_in(monkeypatch, world):
    con = _stub_the_build(monkeypatch, world, swap_in="none")
    assert rollup_serve._build_inmemory_and_swap() is None
    assert rollup_serve._STATE["con"] is con and not con.closed


@pytest.mark.skipif(not __import__("src.analytics.columnar", fromlist=["x"]).duckdb_available(), reason="duckdb not installed (optional [columnar] extra)")
@pytest.mark.parametrize("stop_at", [("mentions", 2), ("aggregate", 0), ("keywords", 0)])
def test_the_real_build_stops_with_the_guards_refusal_at_the_boundary_the_swap_landed_before(world, stop_at):
    """The hook through the REAL ``build_keyword_daily``: whatever the build does around a hook call, the refusal comes out unchanged."""
    from sqlalchemy.orm import sessionmaker

    from src.analytics import columnar
    from src.database.models import Base
    from tests.test_rollup_build_streaming import _seed

    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with engine.connect() as c:
        c.execute(text("PRAGMA foreign_keys=OFF"))
    s = sessionmaker(bind=engine, future=True)()
    try:
        _seed(s, keywords=6, mentions_per=40)
        hook = rollup_serve._make_on_batch(gen.current())
        seen: list[tuple[str, int]] = []
        want_stage, want_n = stop_at

        def swapping_hook(stage: str, rows: int) -> None:
            seen.append((stage, rows))
            if (stage, len(seen)) == (want_stage, want_n) or (stage == want_stage and want_stage != "mentions"):
                world.swap()  # the real swap lands just before this boundary's check
            hook(stage, rows)

        con = columnar.connect(passphrase=None)
        assert con is not None
        with pytest.raises(gen.StaleLibraryError):
            columnar.build_keyword_daily(con, s, batch_size=50, on_batch=swapping_hook)
        assert seen[-1][0] == want_stage, f"the build went on past the boundary: {seen[-3:]}"
    finally:
        s.close()
