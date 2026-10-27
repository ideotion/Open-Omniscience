"""A refusal by the kill switch is NAMED, not read as a quiet success (invariant #14e's corollary; coordinator ruling R292, item C1).

Pressed in airplane mode, four buttons answered with a clean zero and the success toast of a quiet feed: "Ingest this feed"
and "Ingest the selected feeds" (``ingest_source`` swallowed the feed's ``FetchError`` into an empty tally), law "Track changes
now" (every document counted as an ``errors``) and Wikipedia "Track now" (``track_watched`` swallowed each page's refusal and
reported ``pages: 0``). The sweep that found them is ``osm-lane/consent-coverage-sweep-2026-10-27.md``.

The fix is ADDITIVE: ``skipped_offline`` appears in a tally ONLY when the kill switch caused it, and every pre-existing key keeps
its value. The scheduler sums integer keys and reads ``fetch_failed``/``ff:*``; none of them moves. The tests below run the REAL
refusal (kill switch engaged, a transport that raises if a socket is ever reached), then pin the other direction too: a failure
that is not airplane mode never carries the key, so the new word is not a catch-all for "something went wrong".

The four JS handlers are driven in ``skipped_offline_node_test.js``; this file is its pytest driver and keys the new strings.
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import subprocess

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument, Source
from src.ingest import (
    EthicalFetcher,
    FetchFailed,
    activate_kill_switch,
    clear_kill_switch,
    kill_switch_active,
)
from src.ingest import pipeline as P
from src.ingest.fetch_verdict import fetch_failed_reasons
from src.law.track import auto_track_due, track_document
from src.law.track import track_watched as law_track_watched
from src.wiki.track import ensure_page
from src.wiki.track import track_watched as wiki_track_watched

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_KILL_SWITCH_TEXT = "network kill switch is active -- collection stopped by operator"
# The pipeline's keys when NOTHING was refused: the "old fields" this change must leave exactly as they were.
_QUIET = {
    "stored",
    "duplicate",
    "blocked_robots",
    "robots_unavailable",
    "fetch_failed",
    "crawl_delay_deferred",
    "extract_failed",
    "non_article",
    "entries",
    "not_modified",
}


class _NoSocket:
    """A transport that fails the test if the code ever reaches the network."""

    def get(self, *a, **kw):
        raise AssertionError("a socket was reached while the kill switch was engaged")

    head = post = request = get

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}


@contextlib.contextmanager
def airplane_mode():
    was = kill_switch_active()
    activate_kill_switch()
    try:
        yield
    finally:
        (activate_kill_switch if was else clear_kill_switch)()


@pytest.fixture()
def sessions(tmp_path):
    # A FILE database, not :memory:, so the route's threadpool thread sees the same schema and rows.
    engine = create_engine(
        f"sqlite:///{tmp_path / 'skipped.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, future=True)
    engine.dispose()


@pytest.fixture()
def db(sessions):
    session = sessions()
    try:
        yield session
    finally:
        session.close()


def _fetcher() -> EthicalFetcher:
    return EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=_NoSocket())


def _source(db, n: int = 1) -> Source:
    s = Source(name=f"Feed {n}", domain=f"feed{n}.test", rss_url=f"https://feed{n}.test/rss")
    db.add(s)
    db.commit()
    return s


class _Refusing:
    """A fetcher whose feed fetch fails with the given message (no kill switch involved)."""

    def __init__(self, message: str) -> None:
        self.message = message

    def fetch(self, url, **_kw):
        raise FetchFailed(self.message)


# --------------------------------------------------------------------------- #
# ingest_source: the feed fetch                                               #
# --------------------------------------------------------------------------- #


def test_a_feed_the_kill_switch_refused_says_so_and_changes_no_other_key(db):
    src = _source(db)
    with airplane_mode():
        refused = P.ingest_source(db, src, fetcher=_fetcher())
    quiet = P.ingest_source(db, src, fetcher=_Refusing("HTTP 503 for https://feed1.test/rss"))
    assert refused["skipped_offline"] == 1
    assert {k: v for k, v in refused.items() if k != "skipped_offline"} == quiet, (
        "every pre-existing key keeps its value"
    )
    assert set(quiet) == _QUIET and "skipped_offline" not in quiet, (
        "absent unless the kill switch caused it (no permanent zero line)"
    )
    assert not any(quiet.values()) and not any(
        v for k, v in refused.items() if k != "skipped_offline"
    )


@pytest.mark.parametrize(
    "message",
    [
        "HTTP 403 for https://feed1.test/rss",
        "cannot resolve host 'feed1.test': boom",
        "request error for https://feed1.test/rss: timeout",
        "robots.txt could not be read",
        "HTTP 503 for https://feed1.test/rss (server said: network kill switch is active)",
    ],
)
def test_a_failure_that_is_not_airplane_mode_never_carries_the_key(db, message):
    assert "skipped_offline" not in P.ingest_source(db, _source(db), fetcher=_Refusing(message))


def test_the_scheduler_readers_do_not_see_the_new_key():
    """``fetch_failed_reasons`` reads only ``ff:*``; the pass sums every int key like any other (``_add`` in the runner)."""
    last = {"tally": {"fetch_failed": 3, "ff:offline": 3, "skipped_offline": 2}}
    assert fetch_failed_reasons(last) == {"offline": 3}


def test_the_batch_endpoint_carries_it_in_the_aggregate_and_each_row(db, sessions):
    from fastapi.testclient import TestClient

    from src.api.ingestion import get_fetcher
    from src.api.main import app
    from src.database.session import get_db

    a, b = _source(db, 1), _source(db, 2)

    def _db():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_fetcher] = _fetcher
    try:
        with airplane_mode(), TestClient(app, base_url="http://127.0.0.1") as c:
            body = c.post("/api/sources/ingest-batch", json={"source_ids": [a.id, b.id]}).json()
            single = c.post(f"/api/sources/{a.id}/ingest").json()
    finally:
        app.dependency_overrides.clear()
    assert body["requested"] == 2 and body["ingested"] == 2, (
        "the old fields are unchanged: a refused feed still ran the pipeline"
    )
    assert body["aggregate"]["skipped_offline"] == 2 and body["aggregate"]["stored"] == 0
    assert [r["tally"]["skipped_offline"] for r in body["results"]] == [1, 1]
    assert single["tally"]["skipped_offline"] == 1


# --------------------------------------------------------------------------- #
# Wikipedia: track_watched                                                    #
# --------------------------------------------------------------------------- #


def test_wikipedia_tracking_counts_refused_pages_apart_with_the_real_client(db):
    from src.wiki.client import WikiClient

    ensure_page(db, "enwiki", "Probe_one")
    ensure_page(db, "enwiki", "Probe_two")
    with airplane_mode():
        out = wiki_track_watched(db, WikiClient())
    assert out == {"pages": 0, "new_revisions": 0, "flagged": 0, "skipped_offline": 2}


def test_wikipedia_tracking_without_a_refusal_has_the_old_shape(db):
    class _Broken:
        def fetch_current_text(self, wiki, title):
            raise RuntimeError("the server is on fire")

    ensure_page(db, "enwiki", "Probe_one")
    assert wiki_track_watched(db, _Broken()) == {"pages": 0, "new_revisions": 0, "flagged": 0}, (
        "an ordinary failure is not airplane mode"
    )
    assert wiki_track_watched(db, _Broken(), limit_pages=1).keys() == {
        "pages",
        "new_revisions",
        "flagged",
    }


# --------------------------------------------------------------------------- #
# Law: track_document, track_watched, auto_track_due                          #
# --------------------------------------------------------------------------- #


def _laws(db, n: int = 2) -> list[LawDocument]:
    docs = [
        LawDocument(
            jurisdiction="kh", title=f"Code {i}", url=f"https://law.example/{i}", watched=True
        )
        for i in range(n)
    ]
    db.add_all(docs)
    db.commit()
    return docs


def test_law_tracking_names_the_refusal_and_keeps_every_old_field(db):
    _laws(db)
    with airplane_mode():
        out = law_track_watched(db, _fetcher())
    assert out == {
        "documents": 2,
        "baselines": 0,
        "changed": 0,
        "flagged": 0,
        "errors": 2,
        "unchanged": 0,
        "skipped_offline": 2,
    }


def test_law_tracking_of_one_document_flags_only_the_kill_switch(db):
    first, second = _laws(db)
    with airplane_mode():
        refused = track_document(db, _fetcher(), first)
    other = track_document(db, _Refusing("HTTP 404 for https://law.example/1"), second)
    assert refused["status"] == "error" and refused["offline"] is True
    assert other["status"] == "error" and "offline" not in other


def test_law_tracking_without_a_refusal_has_the_old_shape(db):
    _laws(db)
    out = law_track_watched(db, _Refusing("HTTP 404 for https://law.example/x"))
    assert out == {
        "documents": 2,
        "baselines": 0,
        "changed": 0,
        "flagged": 0,
        "errors": 2,
        "unchanged": 0,
    }


def test_the_scheduler_s_law_tally_counts_it_the_same_way(db):
    _laws(db, 3)
    with airplane_mode():
        out = auto_track_due(db, _fetcher(), batch=3)
    assert (
        out["skipped_offline"] == 3
        and out["errors"] == 3
        and out["documents"] == 3
        and out["due"] == 3
    )


# --------------------------------------------------------------------------- #
# The JS half and the strings                                                 #
# --------------------------------------------------------------------------- #

_S1 = "Airplane mode is on: nothing was fetched. Click the plane in the top bar to go online, then try again."
_STRINGS = (_S1, "{n} not fetched (airplane mode)", "Not fetched (airplane mode)")


def test_the_four_handlers_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "skipped_offline_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "skipped_offline_node_test.js: OK" in proc.stdout


def test_the_new_strings_are_keyed_and_translated_in_all_twelve_locales():
    english = json.loads((_ROOT / "src/static/locales/en.json").read_text(encoding="utf-8"))
    for path in sorted((_ROOT / "src/static/locales").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in _STRINGS:
            assert key in data, f"{path.name} lacks {key!r}"
            if path.name != "en.json":
                assert data[key] != english[key], f"{path.name} carries {key!r} untranslated"
        assert "{n}" in data[_STRINGS[1]], f"{path.name} lost the {{n}} slot of the count frame"
