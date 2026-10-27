"""The preflight in airplane mode checks NOTHING, changes NOTHING and says so (invariant #14e's corollary; coordinator ruling R313, G1).

Before, ``preflight_sources`` read the kill switch's refusal as every SOURCE being unreachable: it recorded each one as ``unreachable``, OVERWROTE the
source's learned ``robots_allowed`` with NULL (a previously learned allow or deny erased by the person's own airplane mode), appended the verdicts to
``source_preflight.jsonl`` (the file ``has_run_before()`` reads, so the first-run preflight counted as DONE and never went back) and answered with
the domains under ``unreachable``. ``run_feed_preflight`` did the same with ``feed_preflight.jsonl``. Now a refusal by the kill switch stops the sweep
as ``complete: False`` with ``skipped_offline`` (present only then), writes no log, edits no metadata, and the first-run job's ``pending()`` stays
true. Every other failure keeps its old behaviour; the tests pin that too, including a REMOTE party's text that merely contains the sentence.

The tests run the REAL refusal: the kill switch engaged over a real ``EthicalFetcher`` (a real session: the SSRF guard resolves the target first and
is what meets the kill switch; no request is ever sent).
"""

from __future__ import annotations

import contextlib
import uuid
from typing import Any, cast

import pytest

from src.database.models import Source, SourceMetadata
from src.database.session import SessionLocal, init_db
from src.ingest import (
    EthicalFetcher,
    activate_kill_switch,
    clear_kill_switch,
    kill_switch_active,
)
from src.monitoring import feed_preflight, preflight


@contextlib.contextmanager
def airplane_mode():
    was = kill_switch_active()
    activate_kill_switch()
    try:
        yield
    finally:
        (activate_kill_switch if was else clear_kill_switch)()


@pytest.fixture(autouse=True)
def _isolated_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "_log_path", lambda: tmp_path / "source_preflight.jsonl")
    monkeypatch.setattr(feed_preflight, "_log_path", lambda: tmp_path / "feed_preflight.jsonl")
    return tmp_path


def _fetcher() -> EthicalFetcher:
    return EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0)


@pytest.fixture()
def db():
    """The shared hermetic store, with every other source disabled for the test and NOTHING committed."""
    init_db()
    session = SessionLocal()
    session.query(Source).update({Source.enabled: False})
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _mk(session, learned: bool | None = None) -> Source:
    src = Source(name="Offline probe", domain=f"probe-{uuid.uuid4().hex[:8]}.example", language="en", enabled=True)
    session.add(src)
    session.flush()
    if learned is not None:
        session.add(SourceMetadata(source_id=src.id, robots_allowed=learned))
        session.flush()
    return src


def test_a_refusal_by_the_kill_switch_marks_nothing_unreachable_writes_no_log_and_keeps_the_learned_robots(db):
    src = _mk(db, learned=False)
    with airplane_mode():
        summary = preflight.preflight_sources(db, _fetcher(), limit=5)
    assert summary["complete"] is False
    assert summary["skipped_offline"] == 1
    assert "kill switch" in summary["stopped"] and "airplane mode" in summary["stopped"]
    assert "unreachable" not in summary and "log" not in summary
    assert not preflight.has_run_before(), "an offline sweep must not stamp the first-run preflight as done"
    meta = db.query(SourceMetadata).filter_by(source_id=src.id).one()
    assert meta.robots_allowed is False, "the learned robots verdict was overwritten by the refusal"


def test_the_record_of_a_refused_source_is_skipped_offline_not_unreachable(db):
    src = _mk(db)
    with airplane_mode():
        rec = preflight._check_one(_fetcher(), src)
    assert rec["verdict"] == "skipped_offline" and rec["skipped_offline"] is True
    assert rec["reachable"] is None and rec["robots"] == "skipped_offline"


class _Refusing:
    """A fetcher whose guard raises what the network does when it cannot be reached: an ordinary failure, not our refusal."""

    user_agent = "OpenOmniscienceBot/test"
    session = None
    timeout = 5

    def __init__(self, message: str) -> None:
        self._message = message

    def _guard_target(self, host):
        raise OSError(self._message)

    _guarded_redirect_get = _guard_target


@pytest.mark.parametrize(
    "message",
    [
        "Name or service not known",
        # a REMOTE party's text that contains our sentence is not our refusal (R298: anchored to the start)
        "HTTP 502 from upstream: network kill switch is active -- collection stopped by operator",
    ],
)
def test_an_ordinary_failure_is_still_unreachable_and_still_logged(db, message):
    src = _mk(db, learned=True)
    summary = preflight.preflight_sources(db, _Refusing(message), limit=5)
    assert summary["complete"] is True and "skipped_offline" not in summary
    assert summary["unreachable"] == [src.domain]
    assert preflight.has_run_before()
    assert db.query(SourceMetadata).filter_by(source_id=src.id).one().robots_allowed is None


def test_the_feed_preflight_stops_on_the_refusal_and_logs_nothing():
    with airplane_mode():
        summary = feed_preflight.run_feed_preflight(_fetcher())
    assert summary["complete"] is False and summary["skipped_offline"] >= 1
    assert "kill switch" in summary["stopped"]
    assert not feed_preflight.has_run_before()
    assert "robots_denied" not in summary and "log" not in summary


def test_an_offline_first_run_job_leaves_the_preflight_pending():
    """The headline: neither half stamps, so the next ONLINE pass still runs the first-run preflight. (The job reads through its OWN
    session, so the source it must meet is committed and removed again.)"""
    from src.database.session import session_scope
    from src.monitoring import preflight_job

    init_db()
    with session_scope() as s:
        src = Source(name="Offline job probe", domain=f"job-{uuid.uuid4().hex[:8]}.example", language="en", enabled=True)
        s.add(src)
        s.flush()
        sid = src.id
    try:
        assert preflight_job.pending()

        class _Ctx:
            stopping = False

            def set_progress(self, **_kw):
                return None

        with airplane_mode():
            out = preflight_job._worker(cast(Any, _Ctx()), fetcher=_fetcher())
        assert out["sources"]["complete"] is False and out["sources"]["skipped_offline"] >= 1
        assert out["feeds"]["complete"] is False
        assert preflight_job.pending(), "the offline run stamped the first-run preflight as done"
    finally:
        with session_scope() as s:
            s.query(Source).filter_by(id=sid).delete()


def test_kick_declines_while_the_kill_switch_is_engaged(monkeypatch):
    """The entry point is gated too: no job is started to ask nobody (a declined kick logs nothing, so the next online pass runs it)."""
    from src.monitoring import preflight_job

    started: list[object] = []
    monkeypatch.setattr(preflight_job, "pending", lambda: True)
    monkeypatch.setattr(preflight_job.PREFLIGHT_JOB, "start", lambda **kw: started.append(kw))
    with airplane_mode():
        assert preflight_job.kick() is None
    assert started == []
    clear_kill_switch()
    preflight_job.kick()
    assert started, "kick must still start the job when the switch is clear"
