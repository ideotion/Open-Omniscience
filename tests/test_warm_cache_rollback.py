"""Regression test for the mandatory 4-lens adversarial skeptic matrix's
write-gate/autoflush finding (MEDIUM), PR-D / W1.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DIAGNOSED BUG: ``warm_cache()`` (src/api/insights.py) runs FOUR sequential
steps that all share ONE ``db`` session, each wrapped in its own
``try/except Exception: _LOG.warning(...)`` that logs a failure and moves on --
but never called ``db.rollback()``. A FAILED ``db.commit()`` (e.g. a genuine
"database is locked" collision under the single-writer gate, or any other real
SQLAlchemy write error) leaves the Session's transaction marked "must rollback";
SQLAlchemy does NOT reset that state automatically. Empirically confirmed (three
standalone probes, ``/tmp/.../scratchpad/probe_{commit_failure_cascade,
bare_commit_on_poisoned,read_failure_poison}.py``): on a poisoned session, EVERY
later operation -- a bare ``commit()`` with nothing pending, or a plain read --
ALSO raises ``sqlalchemy.exc.PendingRollbackError`` until an explicit
``rollback()`` runs. So one early, real commit failure in warm_cache's step 1
silently defeats every later step (2, 3, 4) for the rest of that call, each one
independently logged as if IT had its own unrelated problem -- hiding the true,
single root cause behind a wall of misleading noise.

This test forces a GENUINE SQLAlchemy poisoning (a real ``IntegrityError`` from a
real unique-constraint violation, flushed via warm_cache's own ``db.commit()`` --
never a mocked exception that bypasses the ORM's real transactional bookkeeping),
then proves step 2's own DB work either fails (pre-fix: cascades) or succeeds
(post-fix: ``db.rollback()`` between steps clears the poison) purely as a
function of whether the fix is present.
"""

from __future__ import annotations

from sqlalchemy import Column, Integer, String, create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

import src.api.insights as ins


class _PoisonBase(DeclarativeBase):
    pass


class _Dup(_PoisonBase):
    """A tiny standalone table with a UNIQUE column -- used ONLY to force a REAL
    SQLAlchemy flush-time IntegrityError (never a mocked/fake exception), so the
    session's poisoned-transaction state is the genuine ORM mechanism, not a
    hand-waved stand-in for it."""

    __tablename__ = "warm_cache_poison_probe"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)


def _real_session():
    eng = create_engine("sqlite:///:memory:", future=True)
    _PoisonBase.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, future=True)
    session = Session()
    session.add(_Dup(id=1, name="dup"))
    session.commit()
    return session, eng


def test_a_poisoned_session_from_one_step_never_cascades_into_the_next(monkeypatch):
    """MUST FAIL (step 2's real DB work raises PendingRollbackError) if
    warm_cache's step-1 except block does NOT call db.rollback(). PASSES once it
    does: step 1's genuine commit failure is contained to step 1 alone."""
    ins._read_cache._cache.clear()
    db, eng = _real_session()

    step2_result: dict = {"ok": None}

    def _poison_columnar(*a, **kw):
        # Mirrors the REAL defect condition: this step's own DB work leaves a
        # pending, doomed-to-fail row -- warm_cache's OWN db.commit() line right
        # after this call is what actually raises (a real IntegrityError -> a
        # genuinely SQLAlchemy-poisoned session, never a mocked exception).
        db.add(_Dup(id=2, name="dup"))  # UNIQUE(name) collision with id=1

    def _step2_real_read(*a, **kw):
        # Stands in for rollup_serve.refresh/map_serve.refresh -- both do real
        # reads against `db`. On a POISONED session even a bare read raises
        # PendingRollbackError before this step ever reaches its own commit().
        try:
            db.execute(text("SELECT 1")).scalar()
            step2_result["ok"] = True
        except Exception as exc:
            step2_result["ok"] = False
            step2_result["exc"] = type(exc).__name__
            raise

    monkeypatch.setattr(
        "src.analytics.columnar.refresh_persisted_read_model", _poison_columnar
    )
    monkeypatch.setattr("src.analytics.rollup_serve.refresh", _step2_real_read)
    monkeypatch.setattr("src.analytics.map_serve.refresh", lambda *a, **kw: None)
    monkeypatch.setattr("src.analytics.poll_cache.refresh", lambda *a, **kw: None)
    monkeypatch.setattr(ins, "_CACHE_TTL_S", 0)  # short-circuit before the specs loop

    # warm_cache is best-effort by design -- it must never raise, whatever happens
    # inside its steps (each step's own except swallows its failure).
    ins.warm_cache(db)

    assert step2_result["ok"] is True, (
        f"step 2's real DB read failed with {step2_result.get('exc')} on a "
        f"session poisoned by step 1's genuine commit failure -- warm_cache must "
        f"db.rollback() between steps so an early real failure never silently "
        f"defeats every later step (each misreported as its own independent bug)"
    )

    db.close()
    eng.dispose()


def test_warm_cache_still_tolerates_a_bogus_non_session_db():
    """The rollback fix must not regress the existing bogus-`db` unit-test double
    (tests/test_insights_cache.py): db.rollback() on an object() with no such
    method must be swallowed exactly like db.commit() already is."""
    ins._read_cache._cache.clear()
    # No monkeypatching -- every real internal call (refresh_persisted_read_model,
    # rollup_serve.refresh, etc.) will itself raise on a non-Session `db`, and each
    # except's new db.rollback() call must ALSO fail silently (AttributeError),
    # never propagating past warm_cache().
    res = ins.warm_cache(db=object())
    assert isinstance(res, dict) and "warmed" in res
