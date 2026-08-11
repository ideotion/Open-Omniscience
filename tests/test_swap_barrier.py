"""The atomic swap waits for in-flight corpus work instead of replacing the file under it.

MAINTAINER, 2026-08-11: "fix the single writer issue gate that doesn't cover the
restore's raw os.replace so we can do both importing and reindexing, whatever the
sequence (import first or indexing first). if a queue is sufficient, let's go for that."

THE HOLE. A restore commits with ``dispose_engine(); os.replace(working, target)``. A
thread holding a checked-out connection across that keeps writing to the OLD, now-unlinked
inode — silently lost, and a job with a durable cursor has already advanced past those
articles, so nothing goes back for them. ``pause_for_exclusive_operation``'s own docstring
names the gap: the pause "narrows, but does not eliminate, that pre-existing
swap-concurrency window".

THE SINGLE-WRITER GATE CANNOT CLOSE IT, which is why this is a second mechanism rather
than a wider use of the first: the gate is taken on FLUSH, and a re-index batch holds a
connection through its whole read-and-extract phase holding no gate at all.

THE PAIR THAT DOES: the exclusive window stops a new batch from STARTING, and the lease
proves none is IN FLIGHT. Both halves are asserted here, in both directions — an
over-eager barrier that refused a healthy import would be its own kind of damage.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

import threading
import time

import pytest

from src.database.corpus_lease import active_leases, corpus_lease, wait_for_quiescence


# --------------------------------------------------------------------------- #
#  the lease itself
# --------------------------------------------------------------------------- #
def test_a_lease_is_visible_while_held_and_gone_after() -> None:
    assert active_leases() == []
    with corpus_lease("reindex"):
        assert active_leases() == ["reindex"]
    assert active_leases() == []


def test_a_raising_holder_still_releases() -> None:
    """A lease that outlived its holder would wedge every future import."""
    with pytest.raises(RuntimeError), corpus_lease("reindex"):
        raise RuntimeError("batch blew up")
    assert active_leases() == []


def test_nested_leases_release_only_at_the_outermost() -> None:
    with corpus_lease("reindex"):
        with corpus_lease("reindex"):
            assert active_leases() == ["reindex"]
        assert active_leases() == ["reindex"], "the inner exit must not free the outer"
    assert active_leases() == []


# --------------------------------------------------------------------------- #
#  the wait: both directions
# --------------------------------------------------------------------------- #
def test_quiescence_is_immediate_when_nothing_holds() -> None:
    t0 = time.monotonic()
    assert wait_for_quiescence(timeout=5.0) == []
    assert time.monotonic() - t0 < 1.0, "an idle machine must not be made to wait"


def test_it_waits_out_a_batch_that_had_already_begun() -> None:
    """The whole point: a batch in flight when the import starts is waited for, not
    replaced out from under."""
    released = threading.Event()

    def worker():
        with corpus_lease("reindex"):
            time.sleep(0.3)
        released.set()

    threading.Thread(target=worker, daemon=True).start()
    time.sleep(0.05)
    assert active_leases() == ["reindex"]
    assert wait_for_quiescence(timeout=5.0) == [], "it must wait, then proceed"
    assert released.is_set()


def test_the_wait_returns_early_when_the_operator_stops() -> None:
    """This wait sits PAST the restore's last abort point, so a Stop pressed during it
    would otherwise be ignored for the whole 180s and the swap would commit anyway --
    an inert Stop button on the one control the operator is watching."""
    stop = threading.Event()
    held = threading.Event()

    def worker():
        with corpus_lease("reindex"):
            stop.wait(10)

    threading.Thread(target=worker, daemon=True).start()
    time.sleep(0.05)
    held.set()

    t0 = time.monotonic()
    # A generous timeout it must NOT sit out, and a stop that is already true.
    out = wait_for_quiescence(timeout=30.0, should_stop=lambda: True)
    elapsed = time.monotonic() - t0
    stop.set()
    assert out == ["reindex"], "it reports who was holding, so the caller can say so"
    assert elapsed < 1.0, f"it must not wait out the timeout after a stop (took {elapsed:.1f}s)"


def test_a_stop_never_shortens_a_healthy_wait() -> None:
    """The negative-space twin: should_stop returning False must leave the wait exactly as
    it was, or 'honour the stop' would quietly become 'give up early'."""
    released = threading.Event()

    def worker():
        with corpus_lease("reindex"):
            time.sleep(0.3)
        released.set()

    threading.Thread(target=worker, daemon=True).start()
    time.sleep(0.05)
    assert wait_for_quiescence(timeout=5.0, should_stop=lambda: False) == []
    assert released.is_set(), "it waited the batch out rather than returning early"


def test_a_stop_during_the_wait_is_reported_as_a_stop_not_as_a_busy_writer() -> None:
    """Order matters at the swap: the abort point is re-checked BEFORE the still_held
    refusal, so a user who pressed Stop is told they stopped -- not told 'another job is
    writing to your corpus', which names the wrong cause and sends them hunting a job."""
    import inspect

    import src.backup.merge as merge

    src = inspect.getsource(merge.run_restore)
    wait = src.index("wait_for_quiescence(_SWAP_QUIESCE_S")
    recheck = src.index('_abort_point("swap")', wait)  # the SECOND one, after the wait
    refusal = src.index("still writing to your corpus", wait)
    assert wait < recheck < refusal, (
        "the post-wait abort re-check must sit between the wait and the busy-writer refusal"
    )
    assert "should_stop=should_stop" in src[wait - 200 : wait + 200], (
        "the wait must be given the stop callable, or it sits out the full timeout"
    )


def test_a_holder_that_never_finishes_is_reported_not_waited_on_forever() -> None:
    """Refusing is the safe answer; hanging is not, and swapping anyway would BE the
    data loss. The names come back so the operator learns who to stop."""
    stop = threading.Event()

    def worker():
        with corpus_lease("newsletter-import"):
            stop.wait(10)

    threading.Thread(target=worker, daemon=True).start()
    time.sleep(0.05)
    try:
        assert wait_for_quiescence(timeout=0.3) == ["newsletter-import"]
    finally:
        stop.set()


# --------------------------------------------------------------------------- #
#  the swap consumes it, and aborts where aborting is still free
# --------------------------------------------------------------------------- #
def test_the_swap_waits_and_refuses_rather_than_replacing_under_a_writer() -> None:
    import inspect

    import src.backup.merge as merge

    src = inspect.getsource(merge.run_restore)
    # Anchored on the CALL and on the swap's OWN replace: run_restore has several
    # os.replace calls (side files) and names wait_for_quiescence twice (import + call),
    # so a bare substring would compare the wrong pair of positions.
    # No closing paren in the anchor: the call gained a `should_stop=` argument once
    # already, and a guard that pins the argument list breaks on the next one while
    # saying nothing about the property it is named for.
    CALL, SWAP = "wait_for_quiescence(_SWAP_QUIESCE_S", "os.replace(working, target)"
    assert src.count(CALL) == 1 and src.count(SWAP) == 1
    # The barrier is INSIDE the timed swap stage (the wait is real time that stage
    # spends) but before the commit point. That ordering is the whole property: waiting
    # after the replace would protect nothing.
    assert src.index(CALL) < src.index(SWAP)
    # And it refuses through the PRE-SWAP abort, where the live corpus is byte-identical
    # -- not through a raise that lands past the commit point, where there is no undo.
    between = src[src.index(CALL) : src.index(SWAP)]
    assert "RestoreAborted" in between, "a timeout must abort, never fall through to the swap"


def test_every_heavy_corpus_writer_takes_a_lease() -> None:
    """An enumeration is exactly what the recorded lesson says will be wrong, so it is
    asserted rather than remembered: a writer added later without a lease is a writer
    the swap cannot see."""
    import ast
    from pathlib import Path

    def bound_where(tree):
        """Scopes (module, or a function's own body) that BIND the name."""
        out = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "src.database.corpus_lease"
                and any(a.name == "corpus_lease" for a in node.names)
            ):
                out.add(_enclosing(tree, node))
        return out

    def _enclosing(tree, target):
        best = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for child in ast.walk(node):
                    if child is target and (best is None or node.col_offset >= best.col_offset):
                        best = node
        return best.name if best is not None else "<module>"

    for mod in (
        "src/analytics/reindex_job.py",      # the whole-corpus re-index
        "src/api/backup_v2.py",              # the post-import drain
        "src/analytics/quarantine_job.py",   # the quarantine scan
        "src/ingest/import_job.py",          # the standalone .eml folder import
    ):
        tree = ast.parse(Path(mod).read_text(encoding="utf-8"))
        uses = [
            _enclosing(tree, n)
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "corpus_lease"
        ]
        assert uses, f"{mod} writes to the corpus and takes no lease"
        # SCOPE, not presence. The first cut asserted the import string was somewhere in
        # the file, and a scripted edit duly put it in the wrong function -- the guard
        # passed while the use site raised NameError. Only ruff's F821 caught it.
        binds = bound_where(tree)
        for scope in uses:
            assert scope in binds or "<module>" in binds, (
                f"{mod}: corpus_lease is used in {scope}() but imported nowhere it can see"
            )


def test_the_newsletter_import_leases_but_never_parks() -> None:
    """It runs as an ITEM of the import queue, INSIDE the window its own run opened, so
    parking on that window would deadlock it against itself. The lease is observed by the
    swap and never waited on by the holder, so it cannot."""
    from pathlib import Path

    body = Path("src/ingest/import_job.py").read_text(encoding="utf-8")
    assert "corpus_lease(" in body
    assert "exclusive_window_open" not in body and "holds_exclusive" not in body, (
        "yielding here would park a queue item on its own run's window"
    )


def test_the_task_manager_says_parked_rather_than_showing_a_frozen_counter(monkeypatch) -> None:
    """``parked_for_exclusive`` was published FOR this row -- the manager's own comment
    says a frozen counter "is exactly the signature of the stall this yielding was added
    to avoid" -- and the row never read it, so a deliberate pause and a hang looked the
    same. Both directions, because a job that is genuinely running must not be labelled
    paused."""
    import src.analytics.reindex_job as rj
    from src.api.jobs import _reindex_jobs

    def _mgr(**over):
        base = {"state": "running", "running": True, "articles_total": 100,
                "articles_done": 3, "percent": 3.0, "prune_after": True,
                "eta_seconds": None, "tally": {}, "error": None,
                "parked_for_exclusive": False}
        base.update(over)
        return type("M", (), {"status": staticmethod(lambda: base)})()

    monkeypatch.setattr(rj, "get_reindex_manager", lambda: _mgr(parked_for_exclusive=True))
    assert _reindex_jobs()[0]["label"].startswith("Paused for an import")

    monkeypatch.setattr(rj, "get_reindex_manager", lambda: _mgr())
    label = _reindex_jobs()[0]["label"]
    assert not label.startswith("Paused"), "a working job must not be labelled paused"
    assert label.startswith("Re-indexing the corpus")


def test_the_import_asks_before_piling_onto_a_running_writer() -> None:
    """The Collect button has always asked; the import never did, so a re-index quietly
    parked with no word about why its counter stopped."""
    from pathlib import Path

    from tests.js_source_helper import function_body, strip_comments

    app = Path("src/static/app.js").read_text(encoding="utf-8")
    run = strip_comments(function_body(app, "_uxImRun"))
    assert "arbitrate(" in run, "the import must consult the arbitration ask"
    assert "import-queue/start" in run
    assert run.index("arbitrate(") < run.index("import-queue/start"), (
        "asking after starting would be theatre"
    )
    # The ask names the honest answer: parking loses nothing. Keyed, so it ships x12.
    assert "resumes afterwards" in run


def test_the_arbitration_no_longer_calls_a_db_collision_a_network_task() -> None:
    """It fires ONLY on db_writers_busy, and a re-index is not a network task. Re-keyed
    rather than reworded around, so the twelve reviewed translations carry the new claim
    instead of one being orphaned."""
    import json
    from pathlib import Path

    from tests.js_source_helper import function_body, strip_comments

    app = Path("src/static/app.js").read_text(encoding="utf-8")
    arb = strip_comments(function_body(app, "arbitrate"))
    assert "Another network task is running:" not in arb
    assert "Another job is writing to the database:" in arb
    for loc in sorted(Path("src/static/locales").glob("*.json")):
        d = json.loads(loc.read_text(encoding="utf-8"))
        assert "Another network task is running:" not in d, f"{loc.name} still carries the old key"
        assert d.get("Another job is writing to the database:"), f"{loc.name} is missing the new one"


def test_the_quarantine_scan_now_stands_aside_for_an_import() -> None:
    """It had no awareness of the window at all — another entry point added after the
    'gate every entry point' ruling, and so the one it missed."""
    from pathlib import Path

    from tests.js_source_helper import python_function_source

    body = Path("src/analytics/quarantine_job.py").read_text(encoding="utf-8")
    # Scoped to the LOOP, not the file: asserting the helper merely exists is satisfied
    # by its own definition, so deleting the park and keeping the function would pass.
    run = python_function_source(body, "_run")
    assert "_import_owns_the_machine()" in run, "the scan loop must consult the window"
    assert "self._stop.wait(" in run, "and wait on the stop event, so cancel stays instant"
