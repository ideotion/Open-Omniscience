"""A law document whose processing RAISES after a good fetch is backed off like a failed request (R294).

``track_document`` stamps ``last_checked_at`` before it fetches and commits only on its own return paths. An
exception that escaped it after the fetch (a locked commit, an extractor crash) was met by the batch trackers
with ``session.rollback()``, which discarded that stamp: the document kept its old time, stayed at the head of
``auto_track_due``'s least-recently-checked order, and was fetched AGAIN on every pass with no 24 h back-off.
Measured on main and on the R293 branch alike: 3 requests over 3 passes for one such document, and with a batch
of two, two such documents at the head meant a healthy one behind them was never fetched in 3 passes.

What stays: a deferral is not a check (R293), and a pass is never aborted by the back-off failing. The back-off
applies only when the fetch RETURNED a result: an exception from anywhere else (the document's own read, the commit
of a deferral or of a kill-switch refusal) made no request, and stamping it would be the lie R293 removed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument
from src.ingest import CrawlDelayDeferred, FetchFailed, FetchResult, clear_kill_switch
from src.law import track as track_mod
from src.law.track import auto_track_due, track_watched

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
    crasher = _doc(db, "crash1", days_ago=None)
    healthy = _doc(db, "healthy", days_ago=None)
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
    assert crasher.last_checked_at is None, "the back-off did not land, and the pass went on"
    assert healthy.last_status == "baseline captured"
