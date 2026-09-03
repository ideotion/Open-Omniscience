"""S2.1 — a deadlined block must never interrupt another thread's statement.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE FIELD DEFECT, reproduced against the shipped code before it was fixed:
``statement_deadline`` arms SQLite's progress handler, which is state on the
DBAPI CONNECTION. A block that commits (or simply ends) while its deadline is
still running hands an ARMED connection back to the pool, and the next thread to
check it out is interrupted on the FIRST thread's clock. With ``pool_size=1``
thread B's own statement raised ``interrupted`` while thread A sat in its block.

Every test here drives the REAL ``statement_deadline`` over a REAL pooled engine.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from src.database.maintenance import StatementTimeout, statement_deadline

# ~400k iterations: comfortably past the 20,000-opcode granularity at which the
# progress handler fires, so an armed connection WILL be interrupted.
_LONG = sa.text(
    "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x<400000)"
    " SELECT count(*) FROM c"
)
_SHORT = sa.text("SELECT 1")


def _engine(tmp_path, **kw):
    """A REAL pooled engine on a file DB, with the app's own reset listener attached.

    The listener is registered on ``src.database.session.engine`` at import; this
    fixture attaches the same function to its own engine so the test exercises the
    shipped code rather than a re-typed copy of it.
    """
    from src.database.session import _disarm_progress_handler

    eng = sa.create_engine(
        f"sqlite:///{tmp_path / 'd.db'}",
        connect_args={"check_same_thread": False},
        poolclass=QueuePool,
        pool_size=kw.pop("pool_size", 1),
        max_overflow=kw.pop("max_overflow", 0),
    )
    event.listen(eng, "reset", _disarm_progress_handler)
    return eng


def test_a_committed_deadline_cannot_interrupt_another_thread(tmp_path):
    """T1: the defect itself. A returns its connection mid-deadline; B checks out
    THE SAME object and must not be interrupted by A's clock."""
    eng = _engine(tmp_path)
    SL = sessionmaker(bind=eng)

    checkouts: list[int] = []

    @event.listens_for(eng, "checkout")
    def _co(dbapi_connection, _rec, _proxy):
        checkouts.append(id(dbapi_connection))

    a_error: list[str] = []

    def thread_a():
        s = SL()
        try:
            with statement_deadline(s, seconds=0.3):
                s.execute(_SHORT)
                s.commit()          # returns the connection, deadline still live
                time.sleep(0.8)     # let it elapse while B is working
        except Exception as exc:  # noqa: BLE001
            a_error.append(f"{type(exc).__name__}: {exc}")
        finally:
            s.close()

    t = threading.Thread(target=thread_a)
    t.start()
    time.sleep(0.45)                # A has committed AND the deadline has elapsed
    s2 = SL()
    try:
        assert s2.execute(_LONG).scalar() == 400000
    finally:
        s2.close()
        t.join()

    # ANTI-VACUITY: with a larger pool B could get a fresh connection and pass for
    # free. pool_size=1 forces reuse — prove it rather than assume it.
    assert len(set(checkouts)) == 1, (
        f"B must reuse A's connection for this test to mean anything (saw {set(checkouts)})"
    )
    assert not a_error, f"thread A should not have failed: {a_error}"


def test_the_blocks_own_statement_is_still_deadlined_after_it_commits(tmp_path):
    """T1b, the mandatory twin: disarming on checkin must not cost the block its
    OWN deadline. A fix that only stops the cross-thread interrupt would silently
    delete the positive half of the guarantee, and every T1-shaped test would pass.
    """
    eng = _engine(tmp_path)
    s = sessionmaker(bind=eng)()
    try:
        with pytest.raises(StatementTimeout):
            with statement_deadline(s, seconds=0.2):
                s.execute(_SHORT)
                s.commit()          # the connection goes back and is disarmed
                time.sleep(0.25)    # the deadline elapses
                s.execute(_LONG)    # re-armed on after_begin -> must be interrupted
    finally:
        s.rollback()
        s.close()


def test_a_short_statement_on_a_poisoned_connection_would_still_pass(tmp_path):
    """T2: pins the 20,000-opcode granularity, so T1 cannot pass through a
    statement that never reaches the handler at all."""
    eng = _engine(tmp_path)
    SL = sessionmaker(bind=eng)
    s = SL()
    try:
        raw = s.connection().connection.dbapi_connection
        raw.set_progress_handler(lambda: 1, 20_000)   # hostile: always interrupt
        try:
            assert s.execute(_SHORT).scalar() == 1, (
                "a short statement must not reach the handler — otherwise T1 proves nothing"
            )
        finally:
            raw.set_progress_handler(None, 0)
    finally:
        s.rollback()
        s.close()


def test_one_blocks_exit_never_disarms_another_blocks_live_deadline(tmp_path):
    """Edit 3: the teardown must disarm only what THIS session still holds.

    The hazard needs the two blocks to SHARE a connection, and that only happens
    when the first one RELEASES it and the second picks it up — with ``pool_size=1``
    that is forced. A version of this test on a 2-connection pool passed with the
    old historical-list disarm restored, because the two sessions never touched the
    same object and the mutation had nothing to strip.

    Sequence: X arms C and commits (C returns to the pool); Y checks C out and arms
    it with ITS OWN, much shorter deadline; X's block exits. The old code walked its
    ``armed`` list and disarmed C — Y's live deadline, gone — and Y's runaway query
    then ran unbounded.
    """
    eng = _engine(tmp_path, pool_size=1, max_overflow=0)
    SL = sessionmaker(bind=eng)

    y_armed = threading.Event()
    x_may_exit = threading.Event()
    y_result: list[str] = []

    def thread_y():
        s = SL()
        try:
            with statement_deadline(s, seconds=0.3):
                s.execute(_SHORT)       # checks out C and arms it on Y's clock
                y_armed.set()
                x_may_exit.wait(5.0)    # X's block exits HERE, mid-Y
                time.sleep(0.35)        # Y's own deadline elapses
                s.execute(_LONG)        # must still be interrupted
                y_result.append("NOT-INTERRUPTED")
        except StatementTimeout:
            y_result.append("timeout")
        except Exception as exc:  # noqa: BLE001
            y_result.append(type(exc).__name__)
        finally:
            s.rollback()
            s.close()

    sx = SL()
    t = threading.Thread(target=thread_y)
    try:
        with statement_deadline(sx, seconds=30.0):
            sx.execute(_SHORT)
            sx.commit()                 # C goes back to the pool
            t.start()
            assert y_armed.wait(5.0), "Y never armed — the test proves nothing"
    finally:
        sx.close()
        x_may_exit.set()                # X has now left its block
        t.join(30.0)

    assert y_result == ["timeout"], f"Y lost its own deadline: {y_result}"


def test_an_escaped_handler_can_only_interrupt_the_thread_that_armed_it(tmp_path):
    """Edit 4, the belt: even if a connection escapes still armed, the check is a
    no-op on any other thread. Tested directly against the real handler."""
    eng = _engine(tmp_path)
    SL = sessionmaker(bind=eng)
    s = SL()
    raw = s.connection().connection.dbapi_connection
    try:
        with statement_deadline(s, seconds=0.05):
            s.execute(_SHORT)
            time.sleep(0.1)               # the deadline has elapsed
            out: list[object] = []

            def other():
                try:
                    cur = raw.cursor()     # same connection, different thread
                    cur.execute(str(_LONG))
                    out.append(cur.fetchone()[0])
                    cur.close()
                except Exception as exc:  # noqa: BLE001
                    out.append(f"{type(exc).__name__}: {exc}")

            th = threading.Thread(target=other)
            th.start()
            th.join(30.0)
            assert out == [400000], f"a foreign thread was interrupted: {out}"
    finally:
        s.rollback()
        s.close()


def test_a_returned_connection_is_disarmed_before_the_same_thread_reuses_it(tmp_path):
    """Edit 1, isolated — and it needs isolating.

    The obvious cross-thread test can no longer see this: edit 4's owner belt makes
    ``_check`` a no-op off-thread, so a stale handler on a foreign thread is inert
    whether or not the listener disarmed it. Neutering the listener reddened NOTHING
    until this test existed. Same thread, therefore no belt: the connection goes back
    to the pool armed, and the next checkout — by the same thread, outside any
    deadline — must not be interrupted.
    """
    eng = _engine(tmp_path)
    SL = sessionmaker(bind=eng)

    s1 = SL()
    try:
        with statement_deadline(s1, seconds=0.2):
            s1.execute(_SHORT)
            s1.commit()          # the connection returns to the pool
    finally:
        s1.close()               # the block's finally holds nothing to disarm
    time.sleep(0.25)             # the deadline has now elapsed

    s2 = SL()                    # same thread, same pooled connection, no deadline
    try:
        assert s2.execute(_LONG).scalar() == 400000, (
            "a connection came back from the pool still armed"
        )
    finally:
        s2.close()


def test_the_disarm_listener_is_wired_to_the_apps_own_engine():
    """The fixture above attaches the listener to its OWN engine, which is right for
    testing the function in isolation and says NOTHING about whether the app's engine
    carries it. Removing the decorator reddened not one test until this existed — the
    "a double injected by the test bypasses the production path" trap, wearing a
    fixture's clothes.
    """
    from sqlalchemy import event

    from src.database.session import _disarm_progress_handler, engine

    assert event.contains(engine, "reset", _disarm_progress_handler), (
        "the app's engine must disarm on checkin — otherwise the fix exists and is "
        "never reached in production"
    )


# --------------------------------------------------------------------------- #
# S2.2 — an expired deadline must STOP a loop, and the member must KEEP its payload.
# --------------------------------------------------------------------------- #
def test_the_expiry_is_queryable_and_restores_an_enclosing_one(tmp_path):
    """A loop can only stop on its own terms if it can ASK. And the expiry must
    nest: clearing the key on exit would tell an OUTER block it has no deadline."""
    from src.database.maintenance import deadline_expired

    eng = _engine(tmp_path)
    s = sessionmaker(bind=eng)()
    try:
        assert deadline_expired(s) is False, "no deadline must not read as expired"

        # The outer deadline is the SHORT one, deliberately. With a long outer and a
        # short inner, "restored the outer" and "cleared the key entirely" both read
        # False after the inner block and the assertion cannot tell them apart —
        # verified: that shape passed with the restore replaced by an unconditional
        # pop. Making the OUTER the expired one is what discriminates.
        with statement_deadline(s, seconds=0.05):
            time.sleep(0.1)
            assert deadline_expired(s) is True, "the outer deadline has elapsed"
            with statement_deadline(s, seconds=30.0):
                assert deadline_expired(s) is False, "the inner deadline is what applies"
            assert deadline_expired(s) is True, (
                "exiting a nested block must RESTORE the outer deadline, not erase it"
            )
    finally:
        s.rollback()
        s.close()


def test_an_expired_deadline_stops_the_producer_loop_instead_of_being_eaten(tmp_path):
    """The 69-minute member: the deadline raised once per producer and the loop's
    own per-producer ``except`` caught it every time, so it ran the whole list.

    Drives the REAL ``run_all_bounded`` with real registered producers.
    """
    from src.briefing import registry

    eng = _engine(tmp_path)
    s = sessionmaker(bind=eng)()
    calls: list[str] = []

    def _mk(n):
        def _p(_session):
            calls.append(n)
            time.sleep(0.05)
            return []
        return _p

    saved = list(registry._REGISTRY)
    registry._REGISTRY[:] = [(f"p{i}", _mk(f"p{i}")) for i in range(8)]
    try:
        with statement_deadline(s, seconds=0.12):
            _cards, out = registry.run_all_bounded(s)
    finally:
        registry._REGISTRY[:] = saved
        s.rollback()
        s.close()

    assert out["truncated"] is True, "the loop must report that it stopped early"
    assert len(calls) < 8, f"the loop ran every producer despite the deadline ({len(calls)})"
    assert calls, "the loop must run at least one producer — otherwise this proves nothing"


def test_a_partial_member_keeps_its_payload(tmp_path, monkeypatch):
    """The correction that matters: ``skipped-deadline`` writes only a marker, so
    recording it for an overrunning member DISCARDS what the member had already
    computed. ``partial-deadline`` keeps the payload and says it is partial."""
    import io
    import zipfile

    from src.api import diagnostics as D

    eng = _engine(tmp_path)
    db = sessionmaker(bind=eng)()

    def _member():
        time.sleep(0.15)                 # overruns the deadline, then returns its work
        return {"cards": [1, 2, 3]}

    monkeypatch.setattr(D, "_member_touches_db", lambda _fn: True)
    monkeypatch.setattr(D, "_all_diag_db_member_deadline_s", lambda: 0.05)

    buf = io.BytesIO()
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            D._write_all_diagnostics_zip([("m.json", _member)], zf, db=db)
    finally:
        db.rollback()
        db.close()

    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
        names = zf.namelist()
        assert "m.json" in names, f"the partial payload was discarded: {names}"
        assert "m.json.skipped-deadline.txt" not in names
        manifest = json.loads(zf.read("manifest.json"))
    entry = next(e for e in manifest["members"] if e["file"] == "m.json")
    assert entry["outcome"] == "partial-deadline", entry
    assert entry["ok"] is False, "a partial run is not a clean one"
    assert entry["bytes"] > 0


# --------------------------------------------------------------------------- #
# S2.3 — a diagnostic must not rewrite the surface it diagnoses.
# --------------------------------------------------------------------------- #
def test_the_card_diagnostic_never_rewrites_the_live_home_cache(tmp_path, monkeypatch):
    """It called ``get_briefing(force=True)``, which runs ``refresh_briefing``, which
    WRITES ``briefing_cache.json`` — so a read-only report on Home's cards replaced
    Home's cards, and under a member deadline with a truncated set."""
    from src.briefing import card_diagnostics, service

    cache = tmp_path / "briefing_cache.json"
    seeded = {"version": service.CACHE_VERSION, "generated_at": "2026-01-01T00:00:00+00:00",
              "article_count": 3, "cards": [{"type": "x", "title": "a"},
                                            {"type": "y", "title": "b"},
                                            {"type": "z", "title": "c"}]}
    cache.write_text(json.dumps(seeded), encoding="utf-8")
    before = cache.read_bytes()
    monkeypatch.setattr(service, "_cache_path", lambda: cache)

    class _Sess:
        def query(self, *a, **k):
            raise RuntimeError("the diagnostic must not need a live corpus here")

    with contextlib.suppress(Exception):
        card_diagnostics.card_click_diagnostics(_Sess())

    assert cache.read_bytes() == before, "the diagnostic rewrote the live Home cache"


def test_a_truncated_empty_run_keeps_the_cached_cards(tmp_path, monkeypatch):
    """Gated STRICTLY on the deadline: a genuinely empty corpus must still be able
    to blank Home, or the feed stops being about the corpus and nothing says so."""
    from src.briefing import registry, service

    cache = tmp_path / "briefing_cache.json"
    seeded = {"version": service.CACHE_VERSION, "generated_at": "2026-01-01T00:00:00+00:00",
              "article_count": 3, "cards": [{"type": "x", "title": "a"}]}
    cache.write_text(json.dumps(seeded), encoding="utf-8")
    monkeypatch.setattr(service, "_cache_path", lambda: cache)
    monkeypatch.setattr(service, "_article_count", lambda _s: 3)
    monkeypatch.setattr(service, "evaluate_watches", lambda _s: None, raising=False)

    # (a) truncated + empty -> the cached cards SURVIVE
    monkeypatch.setattr(registry, "run_all_bounded", lambda *a, **k: ([], {"truncated": True}))
    monkeypatch.setattr(service, "run_all_bounded", lambda *a, **k: ([], {"truncated": True}))
    out = service.refresh_briefing(object())
    assert [c["title"] for c in out["cards"]] == ["a"], "a truncated run blanked Home"
    assert json.loads(cache.read_text(encoding="utf-8"))["cards"], "the cache was blanked on disk"

    # (b) NOT truncated + empty -> the corpus genuinely yields nothing, so Home empties
    monkeypatch.setattr(service, "run_all_bounded", lambda *a, **k: ([], {"truncated": False}))
    out2 = service.refresh_briefing(object())
    assert out2["cards"] == [], (
        "an untruncated empty run must still be able to empty Home — otherwise a stale "
        "feed freezes forever on a corpus that really has no cards"
    )
