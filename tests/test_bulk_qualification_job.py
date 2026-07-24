"""
Tests for the BULK source-qualification background job (src/catalog/qualify_job.py).

In-memory SQLite + injected session_factory/fetcher/now_fn — no network, runs in CI.
Covers: draining a backlog across several batches, honest completion when the backlog
empties, cooperative cancel, the clean airplane pause, the memory-guard pause, the
no-progress breaker (candidates that can never be evaluated), and a wiring guard that
COMPOSES the real routes (router prefix + decorator) against the frontend caller — the
slice-1c 404 lesson.
"""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.qualification import STATUS_QUALIFIED, STATUS_UNQUALIFIED
from src.catalog.qualify_job import initial_backlog_estimate, run_bulk_qualification
from src.database.models import Article, Base, Source
from src.ingest import activate_kill_switch, clear_kill_switch

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


@pytest.fixture()
def scope(db):
    """A session factory that yields the SAME test session (never closes it)."""

    @contextmanager
    def _scope():
        yield db
        db.commit()

    return _scope


class _Ctx:
    """A stand-in JobContext: cooperative stop + recorded progress."""

    def __init__(self, stop_after: int | None = None):
        self.progress: list[dict] = []
        self._stop_after = stop_after
        self._stopped = False

    @property
    def stopping(self) -> bool:
        return self._stopped

    def set_progress(self, **kw):
        self.progress.append(kw)
        if self._stop_after is not None and len(self.progress) > self._stop_after:
            self._stopped = True


def _add_unqualified(db, n: int, *, rss=True):
    for i in range(n):
        db.add(Source(
            name=f"s{i}", domain=f"bulk-{i}.example",
            rss_url=(f"https://bulk-{i}.example/rss" if rss else None),
            enabled=True, status=STATUS_UNQUALIFIED,
        ))
    db.commit()


def _always_no_evidence_pass(db, fetcher, per_pass, now):
    """A fake qualification_pass that always reports zero evidence — models the
    permanently-unresolvable-candidates case without touching real source_audit
    machinery (kept a pure unit test of the DRIVER loop, not the judging)."""
    from src.catalog.qualification import select_due_disqualified, select_unqualified

    candidates = select_unqualified(db, limit=per_pass)
    remaining = per_pass - len(candidates)
    if remaining > 0:
        candidates += select_due_disqualified(db, now=now, limit=remaining)
    if not candidates:
        return {"enabled": True, "evaluated": 0}
    return {"enabled": True, "evaluated": len(candidates), "qualified": 0,
            "disqualified": 0, "no_evidence": len(candidates), "trial_fetch_errors": 0}


def test_the_real_pass_never_livelocks_on_permanently_stuck_candidates(db, scope, monkeypatch):
    """End-to-end proof through run_bulk_qualification itself (not a stub), using the
    REAL qualification.run_qualification_pass -- the adversarial-review finding,
    reproduced live before the fix: 30 feed-less, forever-zero-evidence sources ahead
    of one genuinely resolvable source in id order must not starve the resolvable one.
    trial_fetch is stubbed to a no-op (no network in a unit test); the "good" source
    carries a REAL pre-existing article so it has genuine evidence from the start."""
    import src.catalog.qualification as qmod

    monkeypatch.setattr(qmod, "trial_fetch", lambda session, source, fetcher, **kw: {})

    for i in range(30):
        db.add(Source(name=f"stuck{i}", domain=f"stuck{i}.example", rss_url=None,
                      enabled=True, status=STATUS_UNQUALIFIED))
    db.commit()
    good = Source(name="good", domain="good.example", rss_url="https://good.example/rss",
                  enabled=True, status=STATUS_UNQUALIFIED)
    db.add(good)
    db.commit()
    db.add(Article(
        url=f"https://good.example/{uuid.uuid4().hex}",
        canonical_url=f"https://good.example/{uuid.uuid4().hex}",
        source_id=good.id, title="Real article", content="x " * 200,
        language="en", hash=uuid.uuid4().hex + uuid.uuid4().hex, word_count=200,
    ))
    db.commit()

    ctx = _Ctx()
    out = run_bulk_qualification(
        ctx, batch_size=10, fetcher=object(), session_factory=scope, sleep_s=0.0
    )
    db.refresh(good)
    assert good.status == STATUS_QUALIFIED, (
        "a resolvable candidate must not be starved by permanently-stuck ones "
        f"(bulk job result: {out})"
    )
    stuck_statuses = {
        s.status for s in db.query(Source).filter(Source.domain.like("stuck%")).all()
    }
    assert stuck_statuses == {STATUS_UNQUALIFIED}  # never silently qualified either


def test_drains_the_backlog_across_several_batches(db, scope, monkeypatch):
    _add_unqualified(db, 25)

    # Stub the pass to instantly qualify everything (no real trial fetch/source_audit).
    def _pass(session, fetcher, batch_size, now):
        from src.catalog.qualification import select_unqualified

        cands = select_unqualified(session, limit=batch_size)
        for c in cands:
            c.status = STATUS_QUALIFIED
        session.commit()
        return {"enabled": True, "evaluated": len(cands), "qualified": len(cands),
                "disqualified": 0, "no_evidence": 0, "trial_fetch_errors": 0}

    monkeypatch.setattr("src.catalog.qualify_job.qualification_pass", _pass)

    ctx = _Ctx()
    out = run_bulk_qualification(
        ctx, batch_size=10, fetcher=object(), session_factory=scope, sleep_s=0.0
    )
    assert out["complete"] is True
    assert out["evaluated"] == 25
    assert out["qualified"] == 25
    assert out["batches_run"] == 4  # 10 + 10 + 5, then a 4th call finds 0 -> complete
    remaining = db.query(Source).filter_by(status=STATUS_UNQUALIFIED).count()
    assert remaining == 0


def test_reports_initial_backlog_estimate(db):
    _add_unqualified(db, 7)
    est = initial_backlog_estimate(db)
    assert est == {"unqualified": 7, "due_disqualified": 0}


def test_cooperative_cancel_stops_and_reports_progress_is_saved(db, scope, monkeypatch):
    _add_unqualified(db, 20)

    def _pass(session, fetcher, batch_size, now):
        from src.catalog.qualification import select_unqualified

        cands = select_unqualified(session, limit=batch_size)
        for c in cands:
            c.status = STATUS_QUALIFIED
        session.commit()
        return {"enabled": True, "evaluated": len(cands), "qualified": len(cands),
                "disqualified": 0, "no_evidence": 0, "trial_fetch_errors": 0}

    monkeypatch.setattr("src.catalog.qualify_job.qualification_pass", _pass)

    ctx = _Ctx(stop_after=1)  # stop after the first progress report
    out = run_bulk_qualification(
        ctx, batch_size=5, fetcher=object(), session_factory=scope, sleep_s=0.0
    )
    assert out["complete"] is False
    assert "cancelled" in out["paused_reason"]
    assert out["batches_run"] < 4  # did not finish draining 20 sources at batch_size=5
    remaining = db.query(Source).filter_by(status=STATUS_UNQUALIFIED).count()
    assert remaining > 0  # genuinely stopped partway, not silently finished


def test_pauses_cleanly_under_airplane_mode(db, scope, monkeypatch):
    _add_unqualified(db, 5)
    monkeypatch.setattr("src.catalog.qualify_job.qualification_pass", _always_no_evidence_pass)
    activate_kill_switch()
    try:
        ctx = _Ctx()
        out = run_bulk_qualification(
            ctx, batch_size=5, fetcher=object(), session_factory=scope, sleep_s=0.0
        )
    finally:
        clear_kill_switch()
    assert out["complete"] is False
    assert "airplane" in out["paused_reason"]
    assert out["batches_run"] == 0  # never even attempted a batch


def test_pauses_under_the_memory_guard(db, scope, monkeypatch):
    _add_unqualified(db, 5)
    monkeypatch.setattr("src.catalog.qualify_job.qualification_pass", _always_no_evidence_pass)
    from src.scheduler import memguard

    monkeypatch.setattr(memguard.memory_guard, "poll", lambda: True)
    monkeypatch.setattr(memguard.memory_guard, "state", lambda: {"reason": "test pressure"})
    ctx = _Ctx()
    out = run_bulk_qualification(
        ctx, batch_size=5, fetcher=object(), session_factory=scope, sleep_s=0.0
    )
    assert out["complete"] is False
    assert "test pressure" in out["paused_reason"]
    assert out["batches_run"] == 0


def test_stops_honestly_after_consecutive_no_progress_batches(db, scope, monkeypatch):
    # Enough sources that a naive loop would otherwise run forever re-selecting them
    # (each batch reports evaluated>0 but qualified+disqualified==0 every time).
    _add_unqualified(db, 50, rss=False)  # no rss_url -> zero evidence every batch
    monkeypatch.setattr("src.catalog.qualify_job.qualification_pass", _always_no_evidence_pass)

    ctx = _Ctx()
    out = run_bulk_qualification(
        ctx, batch_size=5, fetcher=object(), session_factory=scope, sleep_s=0.0
    )
    assert out["complete"] is False
    assert "no evidence to judge" in out["paused_reason"]
    assert out["no_evidence"] > 0
    assert out["qualified"] == 0 and out["disqualified"] == 0
    # Every candidate stayed unqualified — nothing silently stamped.
    remaining = db.query(Source).filter_by(status=STATUS_UNQUALIFIED).count()
    assert remaining == 50


def test_resume_after_cancel_finishes_the_backlog_with_no_double_stamps(db, scope, monkeypatch):
    """No persisted cursor by design -- Source.status IS the durable progress marker.
    A cancelled run resumed by simply calling run_bulk_qualification again must finish
    the WHOLE backlog with each source stamped EXACTLY once (no double-counted
    SourceQualificationAttempt rows, no re-judging an already-qualified source)."""
    from src.database.models import SourceQualificationAttempt

    _add_unqualified(db, 12)

    calls = {"n": 0}

    def _pass(session, fetcher, batch_size, now):
        from src.catalog.qualification import select_unqualified

        calls["n"] += 1
        cands = select_unqualified(session, limit=batch_size)
        for c in cands:
            c.status = STATUS_QUALIFIED
            session.add(SourceQualificationAttempt(
                source_id=c.id, attempted_at=now, verdict=STATUS_QUALIFIED,
                criteria_version="test",
            ))
        session.commit()
        return {"enabled": True, "evaluated": len(cands), "qualified": len(cands),
                "disqualified": 0, "no_evidence": 0, "trial_fetch_errors": 0}

    monkeypatch.setattr("src.catalog.qualify_job.qualification_pass", _pass)

    # First run: cancel after the very first progress report (partial drain).
    out1 = run_bulk_qualification(
        _Ctx(stop_after=1), batch_size=3, fetcher=object(), session_factory=scope, sleep_s=0.0
    )
    assert out1["complete"] is False
    partially_qualified = db.query(Source).filter_by(status=STATUS_QUALIFIED).count()
    assert 0 < partially_qualified < 12

    # "Resume" is just calling it again -- no cursor file, no special resume flag.
    out2 = run_bulk_qualification(
        _Ctx(), batch_size=3, fetcher=object(), session_factory=scope, sleep_s=0.0
    )
    assert out2["complete"] is True
    assert db.query(Source).filter_by(status=STATUS_UNQUALIFIED).count() == 0
    assert db.query(Source).filter_by(status=STATUS_QUALIFIED).count() == 12
    # Exactly one attempt row per source -- the resumed run never re-selected an
    # already-qualified source (select_unqualified excludes it by construction).
    assert db.query(SourceQualificationAttempt).count() == 12


def test_never_a_score_key_anywhere_in_the_payload(db, scope, monkeypatch):
    _add_unqualified(db, 3)
    monkeypatch.setattr("src.catalog.qualify_job.qualification_pass", _always_no_evidence_pass)
    ctx = _Ctx()
    out = run_bulk_qualification(
        ctx, batch_size=5, fetcher=object(), session_factory=scope, sleep_s=0.0
    )
    banned = ("score", "ranking", "rating", "grade")

    def _walk(o, path=""):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(b in k.lower() for b in banned), f"{path}.{k}"
                _walk(v, f"{path}.{k}")

    _walk(out)


def test_empty_backlog_is_a_clean_immediate_complete(db, scope, monkeypatch):
    monkeypatch.setattr("src.catalog.qualify_job.qualification_pass", _always_no_evidence_pass)
    ctx = _Ctx()
    out = run_bulk_qualification(
        ctx, batch_size=5, fetcher=object(), session_factory=scope, sleep_s=0.0
    )
    assert out == {
        "complete": True, "batches_run": 1, "evaluated": 0, "qualified": 0,
        "disqualified": 0, "no_evidence": 0, "trial_fetch_errors": 0,
        "initial_backlog": {"unqualified": 0, "due_disqualified": 0},
    }


# --------------------------------------------------------------------------- #
# C5 (2026-07-24 throughput brief): the worker resolves a HARDWARE-AWARE default
# batch size when the caller omits one, but an explicit value always wins over
# the power profile — the admission logic itself (qualification_pass) is
# untouched by any of this (proven by every test above staying green unchanged).
# --------------------------------------------------------------------------- #


def test_worker_resolves_a_hardware_aware_default_when_batch_size_is_omitted(monkeypatch):
    from src.api.source_management import _bulk_qualification_worker

    captured: dict = {}

    def _fake_run_bulk_qualification(ctx, *, batch_size):
        captured["batch_size"] = batch_size
        return {"complete": True}

    monkeypatch.setattr(
        "src.catalog.qualify_job.run_bulk_qualification", _fake_run_bulk_qualification
    )
    monkeypatch.delenv("OO_QUALIFICATION_BATCH_SIZE", raising=False)
    monkeypatch.delenv("OO_POWER_PROFILE", raising=False)

    _bulk_qualification_worker(object(), batch_size=None)
    assert captured["batch_size"] == 20  # Optimized == the prior hard-coded default

    monkeypatch.setenv("OO_POWER_PROFILE", "max")
    _bulk_qualification_worker(object(), batch_size=None)
    assert captured["batch_size"] == 100  # a capable box digests far more per batch


def test_an_explicit_batch_size_always_wins_over_the_power_profile(monkeypatch):
    from src.api.source_management import _bulk_qualification_worker

    captured: dict = {}

    def _fake_run_bulk_qualification(ctx, *, batch_size):
        captured["batch_size"] = batch_size
        return {"complete": True}

    monkeypatch.setattr(
        "src.catalog.qualify_job.run_bulk_qualification", _fake_run_bulk_qualification
    )
    monkeypatch.setenv("OO_POWER_PROFILE", "max")  # would resolve to 100 if consulted
    _bulk_qualification_worker(object(), batch_size=7)
    assert captured["batch_size"] == 7


# --------------------------------------------------------------------------- #
# Wiring guard (the slice-1c 404 lesson): COMPOSE the backend routes from the
# router prefix + decorators and require the frontend to call exactly those.
# --------------------------------------------------------------------------- #

def test_bulk_qualification_wiring_composes_end_to_end():
    api_src = (_ROOT / "src" / "api" / "source_management.py").read_text("utf-8")
    js_src = (_ROOT / "src" / "static" / "app.js").read_text("utf-8")
    html_src = (_ROOT / "src" / "static" / "index.html").read_text("utf-8")

    prefix = re.search(r'APIRouter\(prefix="([^"]+)"', api_src).group(1)
    # source_management.py decorators carry a trailing ``, response_model=dict)`` (unlike
    # diagnostics.py's bare form) -- match up to the closing quote only, not the paren.
    decorated = set(re.findall(r'@router\.(?:get|post)\("(/qualify-bulk[^"]*)"', api_src))
    backend_routes = {prefix + d for d in decorated}
    assert backend_routes == {
        "/api/sources/qualify-bulk",
        "/api/sources/qualify-bulk/status",
        "/api/sources/qualify-bulk/cancel",
    }

    frontend_routes = set(re.findall(r'"(/api/sources/qualify-bulk[^"?]*)"', js_src))
    assert frontend_routes, "the frontend must call the bulk-qualification endpoints"
    assert frontend_routes - backend_routes == set()  # every JS call hits a real route

    # the Settings -> Sources panel wires the button + status line, consent-gated
    assert 'onclick="qualifyBulkStart(this)"' in html_src
    assert 'id="qualify-bulk-status"' in html_src
    assert "ensureOnline" in js_src.split("async function qualifyBulkStart", 1)[1][:1000]

    # the worker is a cooperatively-cancellable, WRITER background job
    assert '"qualify-sources-bulk"' in api_src
    assert "cancellable=True" in api_src.split('"qualify-sources-bulk"', 1)[1][:400]
