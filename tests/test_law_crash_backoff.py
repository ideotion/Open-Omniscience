"""A law document whose processing RAISES after a good fetch is backed off like a failed request (R294).

``track_document`` stamps ``last_checked_at`` before it fetches and commits only on its own return paths. An
exception that escaped it after the fetch (a locked commit, an extractor crash) was met by the batch trackers
with ``session.rollback()``, which discarded that stamp: the document kept its old time, stayed at the head of
``auto_track_due``'s least-recently-checked order, and was fetched AGAIN on every pass with no 24 h back-off.
Measured on main and on the R293 branch alike: 3 requests over 3 passes for one such document, and with a batch
of two, two such documents at the head meant a healthy one behind them was never fetched in 3 passes.

What stays: a deferral is not a check (R293), and a pass is never aborted by the back-off failing. The back-off
applies only when the fetch RETURNED a result: an exception from anywhere else (the document's own read, the commit
of a deferral or of a kill-switch refusal) made no request, and stamping it would be the lie R293 removed. And only
when the attempt left nothing committed: a crash after its own commit (the corpus indexing, the lane row) keeps the
outcome it recorded.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument, LawRevision
from src.ingest import CrawlDelayDeferred, FetchFailed, FetchResult, clear_kill_switch
from src.law import track as track_mod
from src.law.model import mint_lane_key
from src.law.track import _FETCHED_KEY, _back_off_after_crash, auto_track_due, track_watched

_BODY = " ".join(
    f"Section {i}: every person shall have the right to liberty and security." for i in range(40)
)
_GOOD = f"<html><head><title>Act</title></head><body><main>{_BODY}</main></body></html>"
_BOOM = "<html><body>BOOM</body></html>"


@pytest.fixture(autouse=True)
def _switch_clear():
    clear_kill_switch()
    yield
    clear_kill_switch()


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


@pytest.fixture(autouse=True)
def _boom_crashes_after_the_fetch(monkeypatch):
    """The REAL shape: ``track_document`` has stamped, fetched, and then its text extraction raises."""
    real = track_mod._document_text

    def document_text(result, **kw):
        if "BOOM" in result.content:
            raise RuntimeError("extractor crashed")
        return real(result, **kw)

    monkeypatch.setattr(track_mod, "_document_text", document_text)


def _doc(db, name: str, *, days_ago: float | None):
    doc = LawDocument(
        jurisdiction="uk",
        title=f"Act {name}",
        url=f"https://{name}.test/act",
        watched=True,
        last_status="unchanged" if days_ago is not None else None,
        last_checked_at=(datetime.now(UTC) - timedelta(days=days_ago)) if days_ago is not None else None,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


class _Serves:
    """Serves a page that crashes the extractor for ``crash*`` hosts and a good one otherwise; counts per host."""

    def __init__(self):
        self.requests: list[str] = []

    def fetch(self, url, *, require_html=True, **_kw):
        host = url.split("/")[2]
        self.requests.append(host)
        return FetchResult(
            requested_url=url, final_url=url, status_code=200,
            content=_BOOM if host.startswith("crash") else _GOOD,
            content_type="text/html", fetched_at=datetime.now(UTC),
        )


def test_a_post_fetch_crash_is_stamped_like_a_failed_request_and_not_fetched_again(db):
    doc = _doc(db, "crash1", days_ago=3)
    db.refresh(doc)
    before = doc.last_checked_at
    fetcher = _Serves()
    first = auto_track_due(db, fetcher, batch=5)
    assert first["errors"] == 1 and first["due"] == 1
    db.refresh(doc)
    assert doc.last_checked_at > before, "a fetched document is a real check, even when its processing failed"
    assert doc.last_status.startswith("error: ")
    again = auto_track_due(db, fetcher, batch=5)
    assert again["due"] == 0 and fetcher.requests == ["crash1.test"], "the 24 h back-off applies"


def test_two_crashing_documents_at_the_head_do_not_starve_a_healthy_one(db):
    """Measured before the fix: batch 2, two crashers sorted first (never checked), a healthy one behind them:
    the healthy one was NOT fetched in 3 passes. A crash made a request, so it spends the batch (politeness):
    the healthy one is reached on the next pass, not the same one."""
    _doc(db, "crash1", days_ago=None)
    _doc(db, "crash2", days_ago=None)
    healthy = _doc(db, "healthy", days_ago=3)
    fetcher = _Serves()

    first = auto_track_due(db, fetcher, batch=2)
    assert sorted(fetcher.requests) == ["crash1.test", "crash2.test"] and first["errors"] == 2
    second = auto_track_due(db, fetcher, batch=2)
    assert second["baselines"] == 1 and second["errors"] == 0, second
    db.refresh(healthy)
    assert healthy.last_status == "baseline captured"
    assert fetcher.requests.count("crash1.test") == 1 and fetcher.requests.count("crash2.test") == 1


def test_the_manual_tracker_stamps_a_post_fetch_crash_too(db):
    doc = _doc(db, "crash1", days_ago=3)
    db.refresh(doc)
    before = doc.last_checked_at
    out = track_watched(db, _Serves())
    assert out["errors"] == 1 and out["documents"] == 0
    db.refresh(doc)
    assert doc.last_checked_at > before
    assert doc.last_status.startswith("error: ")


def test_a_crash_before_any_request_is_not_stamped_as_a_check(db, monkeypatch):
    """A one-off database error reading the document is an error, not a check: the document is asked next pass."""
    doc = _doc(db, "healthy1", days_ago=3)
    before = doc.last_checked_at
    real_get, calls = db.get, {"n": 0}

    def get(model, ident, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database is locked")  # the first read only: a back-off could read it again
        return real_get(model, ident, *a, **kw)

    monkeypatch.setattr(db, "get", get)
    fetcher = _Serves()
    out = auto_track_due(db, fetcher, batch=5)
    assert out["errors"] == 1 and fetcher.requests == [], "no request was made"
    db.refresh(doc)
    assert doc.last_checked_at == before and doc.last_status == "unchanged"
    assert auto_track_due(db, fetcher, batch=5)["due"] == 1, "still due"


class _Defers:
    def fetch(self, url, **_kw):
        raise CrawlDelayDeferred("Crawl-delay 3600 s: not before later", netloc="slow.test", delay_s=3600.0, not_before=0.0)


class _Refused:
    def fetch(self, url, **_kw):
        raise FetchFailed("network kill switch is active -- collection stopped by operator")


@pytest.mark.parametrize("fetcher", [_Defers(), _Refused()], ids=["deferral", "kill_switch_refusal"])
def test_a_failed_commit_of_a_non_check_is_not_stamped_as_a_check(db, monkeypatch, fetcher):
    """The commit that records a deferral or a refusal can fail too. Neither made a request, so the back-off for
    a crash AFTER a fetch must not turn the failed commit into a check."""
    doc = _doc(db, "slow", days_ago=3)
    before = doc.last_checked_at
    real_commit, calls = db.commit, {"n": 0}

    def commit():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database is locked")  # the first commit only: a back-off could commit again
        return real_commit()

    monkeypatch.setattr(db, "commit", commit)
    out = auto_track_due(db, fetcher, batch=5)
    assert out["errors"] == 1
    db.refresh(doc)
    assert doc.last_checked_at == before and doc.last_status == "unchanged"


def test_an_earlier_fetch_of_the_same_document_cannot_vouch_for_a_later_non_check(db, monkeypatch):
    """The fetched marker belongs to ONE attempt: a document fetched fine in this session earlier, then deferred
    with a failing commit, is not a check on the second attempt."""
    doc = _doc(db, "slow", days_ago=3)
    track_watched(db, _Serves())  # a good fetch of this very document: the marker would still name it
    db.refresh(doc)
    checked = doc.last_checked_at
    real_commit, calls = db.commit, {"n": 0}

    def commit():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database is locked")
        return real_commit()

    monkeypatch.setattr(db, "commit", commit)
    out = track_watched(db, _Defers())
    assert out["errors"] == 1
    db.refresh(doc)
    assert doc.last_checked_at == checked


def test_a_back_off_that_fails_does_not_abort_the_pass(db, monkeypatch):
    """The back-off is best effort: the database that failed the document may fail the back-off too."""
    crasher = _doc(db, "crash1", days_ago=5)  # the older check time puts it first: the order is the query's, not a tie's
    healthy = _doc(db, "healthy", days_ago=3)
    before = crasher.last_checked_at
    real_commit, calls = db.commit, {"n": 0}

    def commit():
        calls["n"] += 1
        if calls["n"] == 1:  # the back-off's own commit (the crash happens before track_document commits)
            raise RuntimeError("database is locked")
        return real_commit()

    monkeypatch.setattr(db, "commit", commit)
    out = auto_track_due(db, _Serves(), batch=5)
    assert out["errors"] == 1 and out["baselines"] == 1, out
    db.refresh(crasher)
    db.refresh(healthy)
    assert crasher.last_checked_at == before, "the back-off did not land, and the pass went on"
    assert healthy.last_status == "baseline captured"


@pytest.mark.parametrize("attr", ["_record_lane", "_ingest_to_corpus"])
def test_a_crash_after_the_attempts_own_commit_keeps_the_outcome_it_recorded(db, monkeypatch, attr):
    """The baseline is committed, then the lane row (or the corpus indexing) raises. The document WAS baselined and its
    stamp is in the database: the back-off must not overwrite "baseline captured" with an error."""
    doc = _doc(db, "healthy1", days_ago=None)

    def boom(*a, **kw):
        raise RuntimeError("lane db unavailable")

    monkeypatch.setattr(track_mod, attr, boom)
    out = track_watched(db, _Serves())
    assert out["errors"] == 1, out
    db.refresh(doc)
    assert doc.last_status == "baseline captured", doc.last_status
    assert doc.last_checked_at is not None and doc.last_hash is not None
    assert auto_track_due(db, _Serves(), batch=5)["due"] == 0, "the stamp is in the database: not asked again for 24 h"


@pytest.mark.parametrize(
    "run", [lambda db: track_watched(db, _Serves()), lambda db: auto_track_due(db, _Serves(), batch=5)],
    ids=["track_watched", "auto_track_due"],
)
def test_the_back_off_is_made_after_the_rollback_not_before(db, monkeypatch, run):
    """A crash with half-finished attributes pending (the baseline text set, its revision about to be flushed): committing
    the back-off before the rollback would persist that half-finished attempt. After the rollback it is gone."""
    doc = _doc(db, "healthy1", days_ago=None)
    real_flush = db.flush

    def flush(*a, **kw):
        if any(isinstance(o, LawRevision) for o in db.new):
            raise RuntimeError("database is locked")  # the flush that would write the baseline revision
        return real_flush(*a, **kw)

    monkeypatch.setattr(db, "flush", flush)
    out = run(db)
    assert out["errors"] == 1, out
    db.refresh(doc)
    assert doc.baseline_text is None and doc.last_hash is None and doc.latest_text is None, "no half-finished attempt"
    assert doc.last_status.startswith("error: ") and doc.last_checked_at is not None
    assert db.query(LawRevision).count() == 0


def test_a_marker_naming_another_document_does_not_vouch(db):
    """Unit-level pin of the id check: a marker left by another document's attempt cannot stamp this one."""
    doc = _doc(db, "healthy1", days_ago=3)
    before = doc.last_checked_at
    db.info[_FETCHED_KEY] = (doc.id + 100, datetime.now(UTC))
    _back_off_after_crash(db, doc.id, RuntimeError("database is locked"))
    db.refresh(doc)
    assert doc.last_checked_at == before and doc.last_status == "unchanged"
    assert _FETCHED_KEY not in db.info, "the marker is spent either way"


def test_a_fetch_that_went_well_does_not_vouch_for_the_next_documents_unread_row(db, monkeypatch):
    """The likeliest sequence in one pass: document A is fetched fine, then document B's row cannot be read. No request
    was made for B, so B is not a check, whatever marker A's attempt left on the session."""
    a = _doc(db, "healthy-a", days_ago=5)  # the older check time puts it first
    b = _doc(db, "healthy-b", days_ago=3)
    before = b.last_checked_at
    real_get, calls = db.get, {"b": 0}

    def get(model, ident, *args, **kw):
        if ident == b.id:
            calls["b"] += 1
            if calls["b"] == 1:
                raise RuntimeError("database is locked")  # the walk's read only: a back-off could read it again
        return real_get(model, ident, *args, **kw)

    monkeypatch.setattr(db, "get", get)
    fetcher = _Serves()
    out = auto_track_due(db, fetcher, batch=5)
    assert fetcher.requests == ["healthy-a.test"], "B was never asked"
    assert out["errors"] == 1 and out["baselines"] == 1, out
    db.refresh(b)
    assert b.last_checked_at == before and b.last_status == "unchanged"
    db.refresh(a)
    assert a.last_status == "baseline captured"


def test_with_a_batch_of_three_the_healthy_document_behind_two_crashers_is_reached_on_the_same_pass(db):
    """The other half of "a crash spends its slot": the batch is the number of requests, so a third slot reaches it."""
    _doc(db, "crash1", days_ago=None)
    _doc(db, "crash2", days_ago=None)
    healthy = _doc(db, "healthy", days_ago=3)
    fetcher = _Serves()
    out = auto_track_due(db, fetcher, batch=3)
    assert out["errors"] == 2 and out["baselines"] == 1, out
    db.refresh(healthy)
    assert healthy.last_status == "baseline captured"
    assert sorted(fetcher.requests) == ["crash1.test", "crash2.test", "healthy.test"]


def test_one_unreadable_row_after_a_commit_is_one_counted_error_not_a_dead_manual_pass(db, monkeypatch):
    """track_watched takes the document's id without a query: after a commit the documents are expired, and an attribute
    read then goes to the database, where a one-off failure would escape the loop (and fail POST /api/law/track). The
    first head of this PR read ``doc.id`` there; main never did."""
    _doc(db, "healthy-a", days_ago=5)
    second = _doc(db, "healthy-b", days_ago=3)
    before = second.last_checked_at
    state = {"armed": False}
    real_td, real_execute = track_mod.track_document, db.execute

    def track_document(session, fetcher, doc, **kw):
        out = real_td(session, fetcher, doc, **kw)
        state["armed"] = True  # the first document is done; its commit expired every other document
        return out

    def execute(*a, **kw):
        if state["armed"]:
            state["armed"] = False
            raise RuntimeError("database is locked")  # the next read of an expired document
        return real_execute(*a, **kw)

    monkeypatch.setattr(track_mod, "track_document", track_document)
    monkeypatch.setattr(db, "execute", execute)
    out = track_watched(db, _Serves())
    assert out["errors"] == 1 and out["baselines"] == 1, out
    db.refresh(second)
    assert second.last_checked_at == before, "no request was made for it: not a check"


class _Fails503:
    def fetch(self, url, **_kw):
        raise FetchFailed("HTTP 503 Service Unavailable")


def test_a_failed_request_between_two_attempts_does_not_let_the_first_ones_marker_vouch(db, monkeypatch):
    """One session, one document: a good fetch (marker), then a real failed request (it commits a NEW check time and
    leaves the marker alone), then a Crawl-delay deferral whose commit fails. No request was made on the third
    attempt, so it is not a check, whatever the first attempt's marker says."""
    doc = _doc(db, "healthy1", days_ago=3)
    track_watched(db, _Serves())
    track_watched(db, _Fails503())
    db.refresh(doc)
    checked, status = doc.last_checked_at, doc.last_status
    assert status.startswith("fetch error: HTTP 503")
    real_commit, calls = db.commit, {"n": 0}

    def commit():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database is locked")
        return real_commit()

    monkeypatch.setattr(db, "commit", commit)
    out = track_watched(db, _Defers())
    assert out["errors"] == 1, out
    db.refresh(doc)
    assert doc.last_checked_at == checked and doc.last_status == status


def test_a_marker_from_an_earlier_attempt_never_vouches_whatever_its_time(db, monkeypatch):
    """The marker belongs to one attempt: track_document clears it first. Seeded with a time LATER than the document's
    committed one but not in the future (an earlier attempt after which the clock stepped back and a failed request
    committed an earlier time), it would otherwise read as "nothing at or after it is committed" and stamp. A helper
    that merely ignored future-dated markers would not be enough, so the seed is a day ago, not a month ahead."""
    doc = _doc(db, "slow", days_ago=3)
    before = doc.last_checked_at
    db.info[_FETCHED_KEY] = (doc.id, datetime.now(UTC) - timedelta(days=1))
    real_commit, calls = db.commit, {"n": 0}

    def commit():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database is locked")
        return real_commit()

    monkeypatch.setattr(db, "commit", commit)
    out = track_watched(db, _Defers())
    assert out["errors"] == 1, out
    db.refresh(doc)
    assert doc.last_checked_at == before and doc.last_status == "unchanged"


def test_a_newer_check_committed_by_another_session_is_not_overwritten(db):
    """The helper stamps only when no check at or after the attempt's start is committed: a manual run (another
    session) that finished while this attempt was crashing keeps its outcome."""
    doc = _doc(db, "healthy1", days_ago=3)
    started = datetime.now(UTC)
    doc.last_checked_at = started + timedelta(minutes=5)  # committed by the other session after this attempt began
    doc.last_status = "changed (+12 bytes)"
    db.commit()
    db.info[_FETCHED_KEY] = (doc.id, started)
    _back_off_after_crash(db, doc.id, RuntimeError("extractor crashed"))
    db.refresh(doc)
    assert doc.last_status == "changed (+12 bytes)"


def test_a_baseline_found_already_recorded_keeps_that_outcome_when_the_indexing_then_crashes(db, monkeypatch):
    """The duplicate-baseline path rolls back and RE-STAMPS the check before it commits ("baseline already recorded");
    the late-crash no-op relies on that committed time, so a crash in the indexing after it must not overwrite it."""
    doc = _doc(db, "healthy1", days_ago=None)
    result = FetchResult(requested_url=doc.url, final_url=doc.url, status_code=200, content=_GOOD,
                         content_type="text/html", fetched_at=datetime.now(UTC))
    text, _reason, _parsed = track_mod._document_text(result, retrieved_on=datetime.now(UTC).date().isoformat())
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    db.add(LawRevision(document_id=doc.id, observed_at=datetime.now(UTC), content_hash=h, size=len(text), delta_bytes=0,
                       full_text=text, flagged=False, diff_basis="first", valid_on_dating="observed", lane_key=mint_lane_key()))
    db.commit()

    def boom(*a, **kw):
        raise RuntimeError("lane db unavailable")

    monkeypatch.setattr(track_mod, "_ingest_to_corpus", boom)
    out = track_watched(db, _Serves())
    assert out["errors"] == 1, out
    db.refresh(doc)
    assert doc.last_status == "baseline already recorded", doc.last_status
    assert doc.last_checked_at is not None
