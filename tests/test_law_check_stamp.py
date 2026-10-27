"""
A law document's ``last_checked_at`` says a check HAPPENED (R293).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``track_document`` stamped ``last_checked_at = now`` before it fetched, so an attempt that made NO request
-- the kill switch refused it, or the host's own ``Crawl-delay`` put the fetch off -- still read as a check
on every surface that shows the time (the law status line, the Living sources freshness, the coverage ages,
the ingest report's "never checked"), and the 24 h gate in ``auto_track_due`` then kept the document away for
a day. Measured before the fix with the real fetcher and the switch engaged: ``last_checked_at`` = now, the
status overwritten, and ``due: 0`` as soon as the switch cleared, with zero requests made.

What stays: a REAL failed request still stamps (a back-off), a robots disallow is a real answer about the
document and still stamps, and the status still names the kill switch (``tests/test_law_lane_offline.py``).
A deferral is not a failure (S04-13 S2, Q1013 = a): it has its own tally key and is not an error.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument, LawRevision
from src.ingest import (
    CrawlDelayDeferred,
    FetchFailed,
    FetchResult,
    RobotsDisallowed,
    activate_kill_switch,
    clear_kill_switch,
)
from src.ingest.airplane import AirplaneModeError
from src.law.track import auto_track_due, track_document, track_watched

_BODY = " ".join(
    f"Section {i}: every person shall have the right to liberty and security." for i in range(40)
)
_PAGE = f"<html><head><title>Act</title></head><body><main>{_BODY}</main></body></html>"
_SWITCH_TEXT = "network kill switch is active -- collection stopped by operator"


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


def _doc(db, n: int = 1, *, host: str = "gazette.test", days_ago: float | None = 3, status: str | None = "unchanged"):
    doc = LawDocument(
        jurisdiction="uk",
        title=f"Act {host} {n}",
        url=f"https://{host}/act{n}",
        watched=True,
        last_status=status,
        last_checked_at=(datetime.now(UTC) - timedelta(days=days_ago)) if days_ago is not None else None,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


class _Serves:
    """A fetcher that serves one page for every URL and counts the calls."""

    def __init__(self):
        self.calls = 0

    def fetch(self, url, *, require_html=True, **_kw):
        self.calls += 1
        return FetchResult(
            requested_url=url, final_url=url, status_code=200, content=_PAGE,
            content_type="text/html", fetched_at=datetime.now(UTC),
        )


class _Raises:
    def __init__(self, exc):
        self.exc = exc

    def fetch(self, url, **_kw):
        raise self.exc


# --------------------------------------------------------------------------- #
#  The kill switch
# --------------------------------------------------------------------------- #
def test_a_REAL_fetcher_refused_by_the_kill_switch_does_not_stamp_a_check(db):
    from src.safety.fetcher import make_fetcher

    doc = _doc(db)
    before = doc.last_checked_at
    activate_kill_switch()
    out = track_document(db, make_fetcher(), doc)
    db.refresh(doc)
    assert out["status"] == "error"
    assert doc.last_checked_at == before, "no request was made, so no check happened"
    # the status still names the refusal (invariant #14e's corollary; tests/test_law_lane_offline.py pins it too)
    assert "kill switch" in doc.last_status.lower()


def test_a_never_checked_document_stays_never_checked_after_a_refusal(db):
    doc = _doc(db, days_ago=None, status=None)
    activate_kill_switch()
    track_document(db, _Raises(FetchFailed(_SWITCH_TEXT)), doc)
    db.refresh(doc)
    assert doc.last_checked_at is None


def test_the_document_is_due_again_the_moment_the_switch_clears(db):
    """The consequence that mattered: the 24 h gate read a refusal as a check."""
    doc = _doc(db)
    activate_kill_switch()
    refused = auto_track_due(db, _Raises(FetchFailed(_SWITCH_TEXT)), batch=5)
    assert refused["due"] == 1 and refused["errors"] == 1
    clear_kill_switch()
    served = _Serves()
    again = auto_track_due(db, served, batch=5)
    assert again["due"] == 1, "the refused document is still due"
    assert again["baselines"] == 1 and served.calls == 1
    db.refresh(doc)
    assert doc.last_status == "baseline captured"


def test_a_failure_in_flight_when_stop_is_pressed_is_judged_by_the_switch_not_by_its_text(db):
    """The FetchError branch asks the SWITCH. A request already in flight when Stop is pressed fails with
    its own wording (a reset connection, a timeout), which does not name the switch."""
    doc = _doc(db)
    before = doc.last_checked_at
    activate_kill_switch()
    track_document(db, _Raises(FetchFailed("request error for https://gazette.test/act1: connection reset")), doc)
    db.refresh(doc)
    assert doc.last_checked_at == before
    assert "kill switch" not in doc.last_status.lower()  # the text is the failure's own: it is the switch that decided


def test_a_refusal_naming_the_switch_is_restored_even_after_the_switch_was_cleared(db):
    """The text names the switch, so the request was refused whatever the switch says by the time we look."""
    doc = _doc(db)
    before = doc.last_checked_at
    out = track_document(db, _Raises(FetchFailed(_SWITCH_TEXT)), doc)  # the switch is CLEAR here
    db.refresh(doc)
    assert out["status"] == "error" and out["offline"] is True
    assert doc.last_checked_at == before


def test_the_socket_level_guard_error_is_judged_by_the_switch_not_by_its_type(db):
    """``AirplaneModeError`` is an OSError, so it lands in the generic branch; the SWITCH decides."""
    doc = _doc(db)
    before = doc.last_checked_at
    activate_kill_switch()
    track_document(db, _Raises(AirplaneModeError("blocked")), doc)
    db.refresh(doc)
    assert doc.last_checked_at == before
    # control: the same error with the switch CLEAR is an ordinary failure and stamps
    clear_kill_switch()
    track_document(db, _Raises(AirplaneModeError("blocked")), doc)
    db.refresh(doc)
    assert doc.last_checked_at > before


def test_a_stop_pressed_mid_pass_stamps_only_the_documents_it_let_through(db):
    """The Stop button trips the switch while ``auto_track_due`` still has a batch to go."""
    for n in range(3):
        _doc(db, n, days_ago=None, status=None)

    class _StopAfterFirst(_Serves):
        def fetch(self, url, **kw):
            if self.calls >= 1:
                activate_kill_switch()
                raise FetchFailed(_SWITCH_TEXT)
            return super().fetch(url, **kw)

    out = auto_track_due(db, _StopAfterFirst(), batch=3)
    assert out["baselines"] == 1 and out["errors"] == 2, out
    assert out["skipped_offline"] == 2, "the refusals are also counted apart (OSM C1), composed with the restore"
    checked = [d for d in db.query(LawDocument).all() if d.last_checked_at is not None]
    assert len(checked) == 1, "only the document that was really fetched counts as checked"
    clear_kill_switch()
    resumed = auto_track_due(db, _Serves(), batch=3)
    assert resumed["due"] == 2 and resumed["baselines"] == 2


# --------------------------------------------------------------------------- #
#  The host's own Crawl-delay
# --------------------------------------------------------------------------- #
def _deferral():
    return CrawlDelayDeferred("Crawl-delay 3600 s: not before later", netloc="gazette.test", delay_s=3600.0, not_before=0.0)


def test_a_crawl_delay_deferral_is_not_a_check_and_not_an_error(db):
    doc = _doc(db)
    before = doc.last_checked_at
    out = track_document(db, _Raises(_deferral()), doc)
    db.refresh(doc)
    assert out["status"] == "deferred"
    assert doc.last_checked_at == before
    # The status text stays main's ("fetch error: Crawl-delay ..."), so the Law table pill keeps its verdict:
    # a "deferred: ..." text would badge as "other" until a ``deferred`` verdict and its label are ruled.
    from src.api.law import _verdict_of

    assert "Crawl-delay" in doc.last_status
    assert _verdict_of(doc.last_status) == "error"


def test_the_tally_counts_a_deferral_under_its_own_key_in_both_trackers(db):
    _doc(db)
    watched = track_watched(db, _Raises(_deferral()))
    # "documents" counts documents ATTEMPTED: a deferral made no attempt, so it is not in it (the Activity
    # Ledger prints "N document(s) read" from it, and a pass where every law was deferred must not read as a
    # success)
    assert watched["deferred"] == 1 and watched["errors"] == 0 and watched["documents"] == 0
    auto = auto_track_due(db, _Raises(_deferral()), batch=5)
    assert auto["deferred"] == 1 and auto["errors"] == 0 and auto["documents"] == 0
    # every deferral is counted, not only the first
    _doc(db, 2)
    assert track_watched(db, _Raises(_deferral()))["deferred"] == 2
    # additive, and present only when it happened (the convention of ``skipped_offline``): a pass with
    # nothing deferred keeps the old shape
    assert "deferred" not in track_watched(db, _Serves())
    assert "deferred" not in auto_track_due(db, _Serves(), batch=5)


def test_deferred_documents_do_not_use_up_the_batch_that_other_hosts_are_waiting_for(db):
    """Restoring the time leaves a deferred document at the head of the least-recently-checked order. If
    deferrals also spent the batch, slow hosts (the oldest) would fill every pass and the host behind them
    would never be reached. Two slow hosts, so that BOTH halves are needed: a host is asked once per pass
    (its second document is passed over, not asked again), and a deferral does not count against ``batch``
    (two slow hosts fill a batch of two)."""
    _doc(db, 1, host="a.test", days_ago=6)
    _doc(db, 2, host="a.test", days_ago=6)
    _doc(db, 3, host="b.test", days_ago=5)
    fast = _doc(db, 9, host="fast.test", days_ago=2)

    class _SlowHostsDefer(_Serves):
        def fetch(self, url, **kw):
            if "fast.test" not in url:
                raise CrawlDelayDeferred("host asked us to wait", netloc="slow", delay_s=3600.0, not_before=0.0)
            return super().fetch(url, **kw)

    out = auto_track_due(db, _SlowHostsDefer(), batch=2)
    assert out["baselines"] == 1, out
    assert db.query(LawRevision).filter_by(document_id=fast.id).count() == 1
    assert out["deferred"] == 2, out  # a.test once, b.test once; a.test's second document was not asked
    assert out["documents"] == 1 <= 2, out  # read: the one that was served; never more than the batch


def test_a_document_that_crashes_after_the_fetch_still_spends_the_batch(db, monkeypatch):
    """An exception that escapes ``track_document`` (a locked commit, an extractor crash) was asked all the
    same: without it counting against the batch, one pass would fetch every due document."""
    from src.law import track as track_mod

    for n in range(5):
        _doc(db, n, host=f"h{n}.test", days_ago=None, status=None)
    fetcher = _Serves()

    def crash_after_fetching(session, f, doc, **_kw):
        f.fetch(doc.url)
        raise RuntimeError("extractor crashed")

    monkeypatch.setattr(track_mod, "track_document", crash_after_fetching)
    out = auto_track_due(db, fetcher, batch=2)
    assert fetcher.calls == 2, "the batch bounds the requests even when every document crashes"
    assert out["errors"] == 2 and out["due"] == 5
    assert out["documents"] == 0, "a crash read nothing, as on main"


def test_a_document_with_an_unparseable_url_is_one_error_not_a_dead_pass(db):
    """The walk reads each URL's host BEFORE the per-document guard. ``urlsplit`` raises ``ValueError`` on an
    unbalanced bracket and the add-a-document API only checks the ``http(s)://`` prefix, so one such row, which
    sorts first while it has no check time, stopped the whole lane on every pass (measured)."""
    bad = _doc(db, 1, host="[gazette.test", days_ago=None, status=None)
    good = _doc(db, 2, host="good.test", days_ago=2)

    class _ParsesTheUrl(_Serves):
        def fetch(self, url, **kw):
            urlsplit(url)  # what EthicalFetcher.fetch does first
            return super().fetch(url, **kw)

    out = auto_track_due(db, _ParsesTheUrl(), batch=5)
    assert out["errors"] == 1 and out["baselines"] == 1, out
    db.refresh(bad)
    db.refresh(good)
    assert bad.last_status.startswith("error: ")
    assert good.last_status == "baseline captured"


def test_a_database_error_reading_one_document_is_one_error_not_a_dead_pass(db, monkeypatch):
    first = _doc(db, 1, host="a.test", days_ago=None, status=None)
    second = _doc(db, 2, host="b.test", days_ago=None, status=None)
    real_get = db.get

    def get(model, ident, *a, **kw):
        if ident == first.id:
            raise RuntimeError("database is locked")
        return real_get(model, ident, *a, **kw)

    monkeypatch.setattr(db, "get", get)
    out = auto_track_due(db, _Serves(), batch=5)
    assert out["errors"] == 1 and out["baselines"] == 1, out
    db.refresh(second)
    assert second.last_status == "baseline captured"


def test_the_walk_takes_the_never_checked_first_and_then_the_least_recently_checked(db):
    """The order that makes giving a time back matter (rule 3): no test pinned it, on main either."""
    _doc(db, 1, host="a.test", days_ago=3)
    _doc(db, 2, host="b.test", days_ago=6)
    _doc(db, 3, host="c.test", days_ago=None, status=None)
    seen: list[str] = []

    class _Records(_Serves):
        def fetch(self, url, **kw):
            seen.append(urlsplit(url).netloc)
            return super().fetch(url, **kw)

    auto_track_due(db, _Records(), batch=5)
    assert seen == ["c.test", "b.test", "a.test"]


# --------------------------------------------------------------------------- #
#  Controls: what must keep stamping
# --------------------------------------------------------------------------- #
def test_a_real_failed_request_still_stamps_its_back_off(db):
    doc = _doc(db)
    before = doc.last_checked_at
    out = track_document(db, _Raises(FetchFailed("connection refused")), doc)
    db.refresh(doc)
    assert out["status"] == "error"
    assert doc.last_checked_at > before
    assert doc.last_status.startswith("fetch error: ")


def test_a_robots_disallow_is_a_real_answer_and_still_stamps(db):
    doc = _doc(db)
    before = doc.last_checked_at
    track_document(db, _Raises(RobotsDisallowed("robots.txt disallows this URL")), doc)
    db.refresh(doc)
    assert doc.last_checked_at > before


@pytest.mark.parametrize(
    "text",
    [
        "HTTP 503 for https://gazette.test/acts/Internet Kill Switch Act",
        "redirect to unsupported URL: 'ftp://archive.test/Kill Switch Act.pdf'",
        # the fetcher's own sentence, but INSIDE a real failure's text (a server echoing it back, a path naming it)
        f"HTTP 502 for https://gazette.test/{_SWITCH_TEXT.replace(' ', '-')} (upstream said: {_SWITCH_TEXT})",
        "request error for https://gazette.test/a: ('Connection aborted.', BadStatusLine('HTTP/1.1 kill switch\\r\\n'))",
    ],
)
def test_a_real_failure_whose_words_merely_contain_the_phrase_still_stamps(db, text):
    """The refusal is recognised by the fetcher's own sentence at the START of the text, never by a substring:
    a real failure carries a URL, a redirect target or a server's status line (R293 read 2, S1)."""
    doc = _doc(db)
    before = doc.last_checked_at
    out = track_document(db, _Raises(FetchFailed(text)), doc)
    db.refresh(doc)
    assert doc.last_checked_at > before, "a request was made and failed: its back-off must stand"
    assert out["status"] == "error" and "offline" not in out
    tally = track_watched(db, _Raises(FetchFailed(text)))
    assert "skipped_offline" not in tally and tally["errors"] == 1


def test_a_robots_disallow_on_an_address_that_says_kill_switch_still_stamps(db):
    doc = _doc(db, host="kill-switch.test")
    before = doc.last_checked_at
    track_document(db, _Raises(RobotsDisallowed("robots.txt disallows https://kill-switch.test/Kill Switch Act")), doc)
    db.refresh(doc)
    assert doc.last_checked_at > before
