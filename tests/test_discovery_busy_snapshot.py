"""The pass tail must survive a concurrent commit (S2.4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE MOST FREQUENT ERROR IN THE FLEET (2026-09-02): 234 / 144 / 82 lifetime
``database is locked`` records on the three field machines, every one carrying the
same src.discovery.channels traceback.

THE MECHANISM, reproduced rather than reasoned about. SQLite treats a SAVEPOINT
opened outside a transaction as ``BEGIN DEFERRED``, so ``run_discovery``'s reads take
a read snapshot. When anything else commits before the block's flush -- the
housekeeping lane, kicked one step earlier and committing through the gate, or the
briefing thread committing between producers -- the flush's promotion to a write
transaction returns SQLITE_BUSY_SNAPSHOT. The busy handler is NOT consulted while a
read transaction is open, so the 30 s busy_timeout never applies and the failure is
INSTANT. SQLAlchemy then issues ROLLBACK TO SAVEPOINT without RELEASE, the stale outer
transaction survives, and the pass session's final commit raises PendingRollbackError
-- which is how a four-hour pass came to be recorded ok:false.

This race was CREATED by moving the ride-alongs onto a concurrent lane thread.

Ruling 6 makes the fix targeted: gate the two failing call sites, do not change the
engine's transaction mode (that is strictly stronger, strictly riskier, and its own
measured slice).
"""

from __future__ import annotations

import sqlite3
import threading

import pytest


def _wal_store(tmp_path):
    """A real WAL-mode store, because this defect exists only in WAL."""
    path = tmp_path / "snap.db"
    con = sqlite3.connect(path, isolation_level=None, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("CREATE TABLE t(x INTEGER)")
    con.execute("INSERT INTO t VALUES(1)")
    return path, con


def _second(path):
    con = sqlite3.connect(path, isolation_level=None, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def test_the_mechanism_a_read_snapshot_plus_a_commit_fails_instantly(tmp_path):
    """The premise, MEASURED. If this ever stops holding the fix has no subject —
    and the 0-second failure is why the busy_timeout in the connection string is
    irrelevant here, which is the part that misleads a reader."""
    import time

    path, a = _wal_store(tmp_path)
    b = _second(path)

    a.execute("BEGIN DEFERRED")  # what a SAVEPOINT outside a transaction is
    a.execute("SELECT count(*) FROM t").fetchone()  # takes the read snapshot
    b.execute("BEGIN IMMEDIATE")
    b.execute("INSERT INTO t VALUES(2)")
    b.execute("COMMIT")

    t0 = time.monotonic()
    with pytest.raises(sqlite3.OperationalError) as exc:
        a.execute("INSERT INTO t VALUES(3)")
    elapsed = time.monotonic() - t0
    assert "locked" in str(exc.value).lower()
    assert elapsed < 1.0, (
        f"the busy handler is not consulted while a read transaction is open, so this "
        f"must fail instantly despite busy_timeout=30000; took {elapsed:.3f}s"
    )


def test_the_fix_shape_no_commit_can_land_inside_the_window(tmp_path):
    """What holding the gate from before the scan buys: with every in-process commit
    serialised behind it, nothing can land between the snapshot and the write."""
    path, a = _wal_store(tmp_path)
    b = _second(path)
    gate = threading.Lock()

    with gate:  # the writer gate, held from BEFORE the read
        a.execute("BEGIN DEFERRED")
        a.execute("SELECT count(*) FROM t").fetchone()
        # the other writer would have to take the same gate, so it cannot commit here
        assert gate.locked()
        a.execute("INSERT INTO t VALUES(3)")
        a.execute("COMMIT")

    with gate:
        b.execute("BEGIN IMMEDIATE")
        b.execute("INSERT INTO t VALUES(4)")
        b.execute("COMMIT")
    # 1 from setup + the two serialised writes: both landed, neither raised.
    assert a.execute("SELECT count(*) FROM t").fetchone()[0] == 3


def test_run_discovery_holds_the_gate_from_before_the_scan():
    """MUTATION TARGET, structural. Anchored on the parse tree, so a comment quoting
    write_lock cannot satisfy it, and scoped to run_discovery's own body.

    The ORDER is the whole fix: the gate must be entered in the same `with` as (or
    before) begin_nested, because rolling back before begin_nested does NOT help --
    the snapshot is taken by the reads INSIDE the savepoint."""
    import ast

    src = open("src/discovery/channels.py", encoding="utf-8").read()
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "run_discovery"
    )
    for node in ast.walk(fn):
        if not isinstance(node, ast.With):
            continue
        names = [
            (getattr(i.context_expr.func, "id", None) or getattr(i.context_expr.func, "attr", None))
            for i in node.items
            if isinstance(i.context_expr, ast.Call)
        ]
        if "begin_nested" in names:
            assert "write_lock" in names, (
                "the savepoint must be entered with the write gate already held; "
                f"got {names}"
            )
            assert names.index("write_lock") < names.index("begin_nested")
            return
    raise AssertionError("run_discovery no longer opens a savepoint")


def test_apply_source_topics_reads_inside_the_gate():
    """The sibling call site: its write_lock used to be taken AFTER derive_source_topics
    scanned the corpus, leaving the identical window."""
    import ast

    src = open("src/analytics/source_topics.py", encoding="utf-8").read()
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "apply_source_topics"
    )
    gate_line = derive_line = None
    for node in ast.walk(fn):
        if isinstance(node, ast.With):
            for item in node.items:
                call = item.context_expr
                if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "write_lock":
                    gate_line = call.lineno
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "derive_source_topics":
            derive_line = node.lineno
    assert gate_line is not None, "apply_source_topics must take the write gate"
    assert derive_line is not None, "apply_source_topics must derive the topics"
    assert gate_line < derive_line, (
        "the gate must be held BEFORE the scan that takes the read snapshot"
    )


def test_the_tail_ride_alongs_use_their_own_session():
    """A discovery failure must not be able to mark a four-hour pass ok:false. Anchored
    on the parse tree: the call must be inside a `with session_scope()` and must not be
    handed the pass's own session."""
    import ast

    src = open("src/scheduler/runner.py", encoding="utf-8").read()
    tree = ast.parse(src)

    for target in ("run_discovery", "run_auto_source_enrichment"):
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.With):
                continue
            opens_scope = any(
                isinstance(i.context_expr, ast.Call)
                and getattr(i.context_expr.func, "id", "") == "session_scope"
                for i in node.items
            )
            if not opens_scope:
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call) and getattr(inner.func, "id", "") == target:
                    arg = inner.args[0] if inner.args else None
                    assert isinstance(arg, ast.Name) and arg.id != "session", (
                        f"{target} must be given its OWN session, not the pass's; "
                        f"got {getattr(arg, 'id', arg)!r}"
                    )
                    found = True
        assert found, f"{target} must run inside its own session_scope in the pass tail"


def test_discovery_still_creates_candidates_with_no_concurrent_commit(tmp_path):
    """NEGATIVE SPACE, and the one that matters most: the fix must not disable
    discovery. A gate that is never released, or a block that now returns early, would
    pass every failure test above while quietly ending source discovery.

    Its OWN engine, never the shared SessionLocal — rows committed there persist for
    the whole pytest session and pollute every later test that reads it (the recorded
    #577 lesson)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.database.models import Article, ArticleLink, Base, Source
    from src.discovery.channels import run_discovery

    engine = create_engine(f"sqlite:///{tmp_path / 'disc.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        src_row = Source(name="Seed", domain="seed.test")
        session.add(src_row)
        session.flush()
        # several distinct articles citing one external domain, so the citation
        # channel has something real to find
        for i in range(5):
            art = Article(
                title=f"a{i}",
                url=f"https://seed.test/{i}",
                canonical_url=f"https://seed.test/{i}",
                content="x" * 200,
                hash=f"h{i}",
                source_id=src_row.id,
            )
            session.add(art)
            session.flush()
            session.add(
                ArticleLink(
                    article_id=art.id,
                    url="https://cited-example.test/story",
                    normalized_url="https://cited-example.test/story",
                    link_type="external",
                )
            )
        session.commit()

        out = run_discovery(session, per_run=10)
        assert out.get("error") != "discovery_rolled_back", out
        assert out["enabled"] is True
        assert out["created"] >= 1, (
            f"discovery must still find the cited domain; got {out}"
        )
    finally:
        session.close()
        engine.dispose()
