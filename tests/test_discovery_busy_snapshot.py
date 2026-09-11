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


def test_the_new_fix_shape_read_then_end_snapshot_then_gate_survives_a_concurrent_commit(tmp_path):
    """THE NEW SHAPE (A2 fix, 2026-09-11): rather than holding the gate across the
    whole scan (S2.4's fix -- correct, but it serialised every other writer behind a
    26-minute scan on the field corpus, finding A2), end the read snapshot
    (`ROLLBACK`) BEFORE taking the gate. This is the load-bearing proof: a concurrent
    commit lands WHILE the (now ungated) read snapshot is open -- the exact
    interleaving that produced SQLITE_BUSY_SNAPSHOT under the pre-S2.4 shape -- and
    it must NOT break anything, because by the time the gate is taken and a write is
    attempted, no snapshot survives to be promoted."""
    path, a = _wal_store(tmp_path)
    b = _second(path)
    gate = threading.Lock()

    # DECIDE phase: an UNGATED read. Takes a snapshot.
    a.execute("BEGIN DEFERRED")
    a.execute("SELECT count(*) FROM t").fetchone()
    # A concurrent writer commits WHILE the snapshot is open -- this is fine now,
    # because nothing here is about to promote that same transaction to a write.
    b.execute("BEGIN IMMEDIATE")
    b.execute("INSERT INTO t VALUES(2)")
    b.execute("COMMIT")
    # END the snapshot BEFORE the gate -- this one line is the entire fix.
    a.execute("ROLLBACK")

    # APPLY phase: a FRESH write transaction, opened only once the gate is held --
    # no read snapshot is carried across the gate boundary.
    with gate:
        a.execute("BEGIN DEFERRED")
        a.execute("SELECT count(*) FROM t").fetchone()  # a fresh snapshot, taken UNDER the gate
        a.execute("INSERT INTO t VALUES(3)")
        a.execute("COMMIT")  # must NOT raise SQLITE_BUSY_SNAPSHOT

    # 1 from setup + b's concurrent insert + a's write: all three landed.
    assert a.execute("SELECT count(*) FROM t").fetchone()[0] == 3


def test_without_ending_the_snapshot_the_same_interleaving_still_breaks_it(tmp_path):
    """NEGATIVE CONTROL for the test above -- proves it actually discriminates rather
    than passing vacuously. Same interleaving, but WITHOUT the `ROLLBACK` that ends
    the read snapshot before the gate is taken (i.e. the gate is bolted on around the
    write without first ending the earlier read -- a naive "just add a lock" fix that
    does NOT reproduce S2.4's actual mechanism). The old failure mode reproduces
    exactly, which is what proves the ROLLBACK step above is the operative fix and
    not incidental."""
    path, a = _wal_store(tmp_path)
    b = _second(path)
    gate = threading.Lock()

    a.execute("BEGIN DEFERRED")
    a.execute("SELECT count(*) FROM t").fetchone()
    b.execute("BEGIN IMMEDIATE")
    b.execute("INSERT INTO t VALUES(2)")
    b.execute("COMMIT")
    # NO rollback here -- the snapshot from the ungated read is still open when the
    # gate is (belatedly) taken and a write is attempted on the SAME transaction.
    with gate:
        with pytest.raises(sqlite3.OperationalError) as exc:
            a.execute("INSERT INTO t VALUES(3)")
        assert "locked" in str(exc.value).lower()


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


def test_apply_source_topics_reads_outside_the_gate():
    """The sibling call site, UPDATED for the A2 fix (2026-09-11): the corpus-wide
    scan (derive_source_topics, a GROUP BY, AND the old session.query(Source).all()
    -- 86,470 rows on the field corpus) used to run INSIDE the gate, right after it.
    That fixed SQLITE_BUSY_SNAPSHOT (S2.4) but pinned a pooled connection for the
    whole scan on every writer in the process (finding A2, the source_topics half).

    The NEW shape moves the scan into source_topic_candidates (the decide phase),
    called BEFORE any gate is taken, then ends that read transaction
    (`session.rollback()`) before `apply_source_topics` opens the write gate for the
    mechanical Source.tags updates + commit. This test must fail on the OLD shape
    (gate held across the scan) and pass on the NEW one -- the opposite of what this
    test asserted before the fix, which is the point: a test that would still pass
    against the broken shape proves nothing."""
    import ast

    with open("src/analytics/source_topics.py", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)

    apply_fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "apply_source_topics"
    )
    # The corpus-wide scan must NEVER be called from inside apply_source_topics
    # itself -- it must live entirely in the decide phase.
    for node in ast.walk(apply_fn):
        assert not (
            isinstance(node, ast.Call) and getattr(node.func, "id", "") == "derive_source_topics"
        ), "the corpus-wide scan must not be called from inside apply_source_topics"

    # apply_source_topics must end its read transaction (session.rollback()) BEFORE
    # taking the write gate -- ordered by source line, the same discriminator
    # run_discovery's sibling test uses.
    rollback_line = gate_line = None
    for node in ast.walk(apply_fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "rollback":
            rollback_line = node.lineno
        if getattr(func, "id", "") == "write_lock":
            gate_line = node.lineno
    assert rollback_line is not None, "apply_source_topics must end its read transaction"
    assert gate_line is not None, "apply_source_topics must take the write gate"
    assert rollback_line < gate_line, (
        "the read snapshot must be ended BEFORE the write gate is taken"
    )

    # The decide phase itself must still do the real derivation (never a stub that
    # would make the above vacuously true).
    decide_fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "source_topic_candidates"
    )
    assert any(
        isinstance(n, ast.Call) and getattr(n.func, "id", "") == "derive_source_topics"
        for n in ast.walk(decide_fn)
    ), "source_topic_candidates must derive the topic proposals"


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
