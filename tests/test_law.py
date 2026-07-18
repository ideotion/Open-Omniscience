"""
Tests for the world-law change-tracking vertical (§5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Catalog load + seeding, baseline → change → flag tracking (with a stub fetcher), the
model-legislation cross-jurisdiction near-dup card, and the API surface. No network.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument, LawRevision, Source
from src.ingest import FetchResult
from src.law.catalog import load_legal_catalog, register_documents, seed_legal_sources
from src.law.track import page_text, track_document, track_watched

_BODY = " ".join(
    f"Section {i}: every person shall have the right to liberty and security." for i in range(40)
)
_BIGGER = (
    _BODY
    + " "
    + " ".join(
        f"Amendment {i}: this provision is hereby substituted and extended across the realm."
        for i in range(60)
    )
)


def _html(body: str) -> str:
    return f"<html><head><title>Act</title></head><body><main>{body}</main></body></html>"


class StubFetcher:
    """A deterministic fetcher: serves a programmable page per URL (no network)."""

    def __init__(self):
        self.page = ""

    def fetch(self, url: str, *, require_html: bool = True, **_kw) -> FetchResult:
        return FetchResult(
            requested_url=url,
            final_url=url,
            status_code=200,
            content=self.page,
            content_type="text/html",
            fetched_at=datetime.now(UTC),
        )


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


# --------------------------------------------------------------------------- #
#  Catalog + seeding
# --------------------------------------------------------------------------- #
def test_catalog_loads_real_sources_and_documents():
    cat = load_legal_catalog()
    assert len(cat["sources"]) >= 30  # a worldwide set of official portals
    assert len(cat["documents"]) >= 5
    # Spot-check real official domains are present.
    domains = {s["domain"] for s in cat["sources"]}
    assert "legislation.gov.uk" in domains and "eur-lex.europa.eu" in domains
    assert any(s["source_type"] == "ip" for s in cat["sources"])


def test_seed_sources_and_register_documents(db):
    s = seed_legal_sources(db)
    assert s["created"] >= 30
    assert db.query(Source).filter_by(source_type="legal").count() >= 10
    d = register_documents(db)
    assert d["created"] >= 5
    # Idempotent.
    assert seed_legal_sources(db)["created"] == 0
    assert register_documents(db)["created"] == 0


def test_register_documents_populates_language_and_country_from_the_catalog(db, tmp_path):
    """S4b (the Cambodia fix): a NEW registration must carry the catalog's own
    stated language/country onto the LawDocument row."""
    catalog = tmp_path / "cat.yml"
    no_gen = tmp_path / "no-such-generated.yml"  # isolate from the real ~225-source harvest
    catalog.write_text(
        "sources: []\n"
        "documents:\n"
        "- {jurisdiction: kh, title: Code civil, url: 'https://law.example/kh', "
        "language: fr, country: kh}\n",
        encoding="utf-8",
    )
    register_documents(db, path=catalog, generated_path=no_gen)
    doc = db.query(LawDocument).filter_by(jurisdiction="kh").one()
    assert doc.language == "fr"
    assert doc.country == "kh"


def test_register_documents_accepts_a_languages_list_shape_too(db, tmp_path):
    """A harvested/generated catalog entry may state several official-language
    versions as a ``languages:`` LIST rather than the curated schema's singular
    ``language:`` string -- take the first, defensively, never crash or drop it."""
    catalog = tmp_path / "cat.yml"
    no_gen = tmp_path / "no-such-generated.yml"
    catalog.write_text(
        "sources: []\n"
        "documents:\n"
        "- {jurisdiction: kh, title: Code civil, url: 'https://law.example/kh', "
        "languages: [fr, km], country: kh}\n",
        encoding="utf-8",
    )
    register_documents(db, path=catalog, generated_path=no_gen)
    doc = db.query(LawDocument).filter_by(jurisdiction="kh").one()
    assert doc.language == "fr"


def test_register_documents_heals_an_existing_row_missing_language(db, tmp_path):
    """A document registered BEFORE language/country existed (both NULL) must
    heal them in place on the next registration pass -- filled in only while
    still NULL, so a value set some other way is never clobbered."""
    doc = LawDocument(jurisdiction="kh", title="Code civil", url="https://law.example/kh")
    db.add(doc)
    db.commit()
    assert doc.language is None

    catalog = tmp_path / "cat.yml"
    no_gen = tmp_path / "no-such-generated.yml"
    catalog.write_text(
        "sources: []\n"
        "documents:\n"
        "- {jurisdiction: kh, title: Code civil, url: 'https://law.example/kh', "
        "language: fr, country: kh}\n",
        encoding="utf-8",
    )
    out = register_documents(db, path=catalog, generated_path=no_gen)
    assert out["created"] == 0 and out["healed_language"] == 1
    db.refresh(doc)
    assert doc.language == "fr" and doc.country == "kh"


def test_register_documents_heals_the_linked_articles_language_too(db, tmp_path):
    """S4b's real end-to-end acceptance ('existing docs heal'): re-registering
    must heal not just the LawDocument row but the ALREADY-INGESTED corpus
    Article it is linked to -- track_document's own steady-state "unchanged"
    poll skips corpus re-sync entirely once a document has latest_text (see
    src/law/track.py), so register_documents re-reading the catalog is the
    REAL trigger that must reach the Article, not "wait for the next pass"."""
    from src.database.models import Article
    from src.law.corpus import law_canonical_url, upsert_law_corpus_article

    doc = LawDocument(jurisdiction="kh", title="Code civil", url="https://law.example/kh",
                      latest_text="Article premier. " * 30)
    db.add(doc)
    db.commit()
    upsert_law_corpus_article(db, doc=doc)  # ingest once, BEFORE a language is known
    art = db.query(Article).filter_by(canonical_url=law_canonical_url(doc)).one()
    assert art.language is None

    catalog = tmp_path / "cat.yml"
    no_gen = tmp_path / "no-such-generated.yml"
    catalog.write_text(
        "sources: []\n"
        "documents:\n"
        "- {jurisdiction: kh, title: Code civil, url: 'https://law.example/kh', "
        "language: fr, country: kh}\n",
        encoding="utf-8",
    )
    register_documents(db, path=catalog, generated_path=no_gen)
    db.refresh(doc)
    db.refresh(art)
    assert doc.language == "fr"
    assert art.language == "fr"  # the ALREADY-INGESTED article healed too

    # Idempotent: a second pass finds nothing left to heal.
    assert register_documents(db, path=catalog, generated_path=no_gen)["healed_language"] == 0


def test_register_documents_never_overwrites_an_already_stated_language(db, tmp_path):
    doc = LawDocument(jurisdiction="kh", title="Code civil", url="https://law.example/kh", language="en")
    db.add(doc)
    db.commit()
    catalog = tmp_path / "cat.yml"
    no_gen = tmp_path / "no-such-generated.yml"
    catalog.write_text(
        "sources: []\n"
        "documents:\n"
        "- {jurisdiction: kh, title: Code civil, url: 'https://law.example/kh', "
        "language: fr, country: kh}\n",
        encoding="utf-8",
    )
    register_documents(db, path=catalog, generated_path=no_gen)
    db.refresh(doc)
    assert doc.language == "en"  # NEVER clobbered, even though the catalog now says "fr"


def test_auto_track_due_is_freshness_gated_and_bounded(db):
    """#18: a per-pass auto-track that builds baselines over time WITHOUT hammering —
    bounded batch, round-robin by least-recently-checked, freshness-gated."""
    from src.law.track import auto_track_due

    for i in range(5):
        db.add(LawDocument(jurisdiction="uk", title=f"Act {i}",
                           url=f"https://example.test/act{i}", watched=True))
    # an UNWATCHED doc must never be tracked
    db.add(LawDocument(jurisdiction="uk", title="Unwatched",
                       url="https://example.test/x", watched=False))
    db.commit()
    fetcher = StubFetcher()
    fetcher.page = _html(_BODY)

    r1 = auto_track_due(db, fetcher, batch=2)
    assert r1["documents"] == 2 and r1["baselines"] == 2  # bounded to the batch
    assert r1["due"] == 5                                  # 5 watched, none checked yet
    # The just-tracked two are now fresh -> the next pass picks DIFFERENT docs.
    r2 = auto_track_due(db, fetcher, batch=2)
    assert r2["documents"] == 2 and r2["due"] == 3
    r3 = auto_track_due(db, fetcher, batch=2)
    assert r3["documents"] == 1 and r3["due"] == 1        # the 5th + last
    # All five watched docs now have a baseline; the unwatched one was never fetched.
    assert db.query(LawRevision).count() == 5
    assert db.query(LawDocument).filter_by(watched=False).first().last_checked_at is None
    # Everything is fresh now -> nothing due.
    assert auto_track_due(db, fetcher, batch=2)["due"] == 0


# --------------------------------------------------------------------------- #
#  Tracking: baseline → unchanged → change (flagged) → revert
# --------------------------------------------------------------------------- #
def test_page_text_strips_chrome():
    txt = page_text(
        "<html><body><script>x=1</script><nav>menu</nav><p>The law text.</p></body></html>"
    )
    assert "The law text." in txt
    assert "menu" not in txt and "x=1" not in txt


def test_track_baseline_change_flag_revert(db):
    doc = LawDocument(jurisdiction="uk", title="Test Act", url="https://example.test/act")
    db.add(doc)
    db.commit()
    fetcher = StubFetcher()

    fetcher.page = _html(_BODY)
    assert track_document(db, fetcher, doc)["status"] == "baseline"
    assert doc.baseline_text is not None

    assert track_document(db, fetcher, doc)["status"] == "unchanged"

    fetcher.page = _html(_BIGGER)
    res = track_document(db, fetcher, doc)
    assert res["status"] == "changed"
    assert res["delta_bytes"] > 1000 and res["flagged"] is True
    assert "large_addition" in res["flag_reasons"]

    # Reverting to the baseline text is recognised as a known version, not a new change.
    fetcher.page = _html(_BODY)
    assert track_document(db, fetcher, doc)["status"] == "reverted"

    revs = db.query(LawRevision).filter_by(document_id=doc.id).count()
    assert revs == 2  # baseline + the one genuine change


def test_track_document_is_idempotent_on_duplicate_revision(db):
    # Field test 2026-06-24: a ~4-hour scrape pass died with "UNIQUE constraint failed:
    # law_revisions.document_id, law_revisions.content_hash ... transaction has been rolled
    # back" — a duplicate LawRevision insert poisoned the shared pass session, rolling back
    # every article scraped that pass. track_document must ABSORB the duplicate (idempotent),
    # never raise, and leave the session usable.
    doc = LawDocument(jurisdiction="xx", title="Dup Act", url="https://law.test/dup", watched=True)
    db.add(doc)
    db.commit()
    fetcher = StubFetcher()
    fetcher.page = _html(_BODY)
    assert track_document(db, fetcher, doc)["status"] == "baseline"
    assert db.query(LawRevision).filter_by(document_id=doc.id).count() == 1

    # Force the collision condition: the doc "forgot" its baseline (a prior pass rolled back
    # the doc fields but the revision row had landed), so the baseline path re-runs against
    # an already-present (document_id, content_hash) revision.
    doc.baseline_text = None
    doc.baseline_hash = None
    doc.last_hash = None
    db.commit()

    res = track_document(db, fetcher, doc)  # same page => same content_hash => would collide
    assert res["status"] == "duplicate"  # absorbed, not raised
    assert db.query(LawRevision).filter_by(document_id=doc.id).count() == 1  # no duplicate row
    assert doc.baseline_text is not None  # baseline re-cached so the next pass is "unchanged"

    # The session is NOT poisoned: a further unrelated write commits cleanly. This is the
    # exact thing that was failing — the pass's final commit raised "transaction has been
    # rolled back due to a previous exception during flush".
    db.add(LawDocument(jurisdiction="yy", title="Other", url="https://law.test/other"))
    db.commit()
    assert db.query(LawDocument).count() == 2


def test_track_document_absorbs_a_sqlcipher3_style_duplicate_revision(db, monkeypatch):
    """Audit finding 2026-07-17: track_document's duplicate-revision recovery caught
    only sqlalchemy.exc.IntegrityError, but on the ENCRYPTED (sqlcipher3) store a
    unique-constraint collision surfaces as the driver's OWN unwrapped exception
    class -- the same cross-driver divergence already fixed for
    is_locked_error/classify_restore_error/src/ingest/email.py. Simulates that exact
    exception (a distinct class, unrelated to sqlite3's, injected the same way
    tests/test_classify_restore_error_sqlcipher.py does) to prove the real
    is_integrity_error-based dispatch handles it without crashing the pass."""
    import sys
    import types

    from src.database import write as write_mod

    class _FakeSqlcipherIntegrityError(Exception):
        pass

    import sqlite3

    assert not issubclass(_FakeSqlcipherIntegrityError, sqlite3.IntegrityError), (
        "the fixture must be a genuinely UNRELATED class -- the whole point of the bug"
    )
    fake_dbapi2 = types.SimpleNamespace(IntegrityError=_FakeSqlcipherIntegrityError)
    fake_pkg = types.SimpleNamespace(dbapi2=fake_dbapi2)
    monkeypatch.setitem(sys.modules, "sqlcipher3", fake_pkg)
    monkeypatch.setitem(sys.modules, "sqlcipher3.dbapi2", fake_dbapi2)
    write_mod._db_integrity_error_types.cache_clear()

    doc = LawDocument(jurisdiction="xx", title="Dup Act", url="https://law.test/dup2", watched=True)
    db.add(doc)
    db.commit()
    fetcher = StubFetcher()
    fetcher.page = _html(_BODY)
    assert track_document(db, fetcher, doc)["status"] == "baseline"

    # Force the collision condition (same setup as test_track_document_is_idempotent_
    # on_duplicate_revision): the doc "forgot" its baseline so the baseline path
    # re-runs against an already-present (document_id, content_hash) revision.
    doc.baseline_text = None
    doc.baseline_hash = None
    doc.last_hash = None
    db.commit()

    # The real UNIQUE-constraint violation raises at session.flush() (where the
    # actual INSERT is issued), not at the later session.commit() -- match that.
    # Trigger ONLY when a LawRevision is actually pending (i.e. the flush track_
    # document itself issues right after `session.add(rev)`) -- an earlier,
    # UNRELATED autoflush fires first here (SQLAlchemy reloads `doc`'s expired
    # attributes -- expire_on_commit -- the moment track_document's second call
    # reads `doc.url`), so a naive "raise on the first flush call" trigger would
    # hit the wrong flush and never reach the code path under test.
    real_flush = db.flush

    def _flush_raise_when_revision_pending(*a, **kw):
        if any(isinstance(o, LawRevision) for o in db.new):
            raise _FakeSqlcipherIntegrityError(
                "UNIQUE constraint failed: law_revisions.document_id, law_revisions.content_hash"
            )
        return real_flush(*a, **kw)

    monkeypatch.setattr(db, "flush", _flush_raise_when_revision_pending)
    try:
        res = track_document(db, fetcher, doc)  # same page => same content_hash => would collide
    finally:
        write_mod._db_integrity_error_types.cache_clear()  # never leak the fake into other tests

    assert res["status"] == "duplicate"  # absorbed via is_integrity_error, not raised
    assert db.query(LawRevision).filter_by(document_id=doc.id).count() == 1  # no duplicate row


def test_track_document_reraises_a_genuinely_unexpected_exception(db, monkeypatch):
    """A failure that is neither a lock nor an integrity violation must still surface
    loudly -- never be silently swallowed as a duplicate."""
    doc = LawDocument(jurisdiction="xx", title="Boom Act", url="https://law.test/boom", watched=True)
    db.add(doc)
    db.commit()
    fetcher = StubFetcher()
    fetcher.page = _html(_BODY)

    real_flush = db.flush

    def _flush_raise_when_revision_pending(*a, **kw):
        if any(isinstance(o, LawRevision) for o in db.new):
            raise RuntimeError("disk full")
        return real_flush(*a, **kw)

    monkeypatch.setattr(db, "flush", _flush_raise_when_revision_pending)
    with pytest.raises(RuntimeError, match="disk full"):
        track_document(db, fetcher, doc)


def test_track_watched_tally_and_fetch_error(db):
    db.add(LawDocument(jurisdiction="uk", title="A", url="https://ex.test/a"))
    db.commit()

    class BadFetcher:
        def fetch(self, url, *, require_html=True, **_kw):
            from src.ingest import FetchFailed

            raise FetchFailed("boom")

    tally = track_watched(db, BadFetcher())
    assert tally["errors"] == 1 and tally["baselines"] == 0  # loud degradation, no fabrication


# --------------------------------------------------------------------------- #
#  Model-legislation card (cross-jurisdiction near-dup) + law-change card
# --------------------------------------------------------------------------- #
def test_model_legislation_producer(db):
    text = _BODY
    db.add(
        LawDocument(jurisdiction="uk", title="UK Bill", url="https://uk.test/x", baseline_text=text)
    )
    db.add(
        LawDocument(jurisdiction="us", title="US Bill", url="https://us.test/x", baseline_text=text)
    )
    db.add(
        LawDocument(
            jurisdiction="uk",
            title="Other",
            url="https://uk.test/y",
            baseline_text="A wholly different statute about fishing quotas and coastal waters." * 5,
        )
    )
    db.commit()
    from src.briefing.producers import model_legislation

    cards = model_legislation(db)
    assert cards, "expected a cross-jurisdiction model-legislation card"
    c = cards[0]
    assert c.bucket == "investigate"
    assert set(c.signal["jurisdictions"]) == {"uk", "us"}


def test_law_change_card(db):
    doc = LawDocument(
        jurisdiction="eu",
        title="GDPR",
        url="https://eu.test/gdpr",
        official_url="https://eur-lex.europa.eu/x",
    )
    db.add(doc)
    db.commit()
    db.add(
        LawRevision(
            document_id=doc.id,
            observed_at=datetime.now(UTC),
            content_hash="h1",
            size=5000,
            delta_bytes=1500,
            flagged=True,
            flag_reasons="large_addition",
        )
    )
    db.commit()
    from src.briefing.producers import law_change

    cards = law_change(db)
    assert cards and cards[0].bucket == "watch"
    assert cards[0].evidence[0]["url"] == "https://eur-lex.europa.eu/x"


# --------------------------------------------------------------------------- #
#  API smoke
# --------------------------------------------------------------------------- #
def test_verdict_of_classifies_last_status_honestly():
    """Field report 2026-07-17 (law-vertical brief, S2b): the per-document status
    column showed the raw last_status string but nothing surfaced it loudly. The
    classifier is a LABEL over the real message (never a new guess) -- robots
    detection must fire whether the message came from RobotsDisallowed or
    RobotsUnavailable, both of which mention "robots.txt" (src/ingest/__init__.py)."""
    from src.api.law import _verdict_of

    assert _verdict_of(None) == "never_checked"
    assert _verdict_of("fetch error: robots.txt disallows https://x.test/a") == "robots_blocked"
    assert _verdict_of("robots.txt for x.test could not be determined; refusing to fetch") == "robots_blocked"
    assert _verdict_of("fetch error: timed out") == "error"
    assert _verdict_of("error: boom") == "error"
    assert _verdict_of("no usable text extracted") == "empty"
    assert _verdict_of("changed (+120 bytes vs baseline)") == "changed"
    assert _verdict_of("reverted to a previously-seen version") == "reverted"
    assert _verdict_of("baseline captured") == "baselined"
    assert _verdict_of("baseline already recorded") == "baselined"
    assert _verdict_of("unchanged") == "unchanged"
    assert _verdict_of("version already recorded") == "other"


def test_law_status_reports_last_checked_at(db):
    """S2a: the honest empty-state message needs a real "last pass" timestamp to
    distinguish a working-but-quiet tracker from one that never ran."""
    from src.api.law import law_status

    assert law_status(db=db)["last_checked_at"] is None

    doc = LawDocument(jurisdiction="uk", title="Test Act", url="https://example.test/act")
    db.add(doc)
    db.commit()
    fetcher = StubFetcher()
    fetcher.page = _html(_BODY)
    track_document(db, fetcher, doc)

    s = law_status(db=db)
    assert s["last_checked_at"] is not None
    assert s["last_checked_at"] == doc.last_checked_at.isoformat()


def test_law_changes_defaults_to_all_real_changes_not_flagged_only(db):
    """S2a: consolidated statutes rarely trip the flag heuristics, so a real,
    unflagged change must be visible by DEFAULT -- flagged_only is opt-in."""
    from src.api.law import law_changes

    doc = LawDocument(jurisdiction="uk", title="Test Act", url="https://example.test/act")
    db.add(doc)
    db.commit()
    fetcher = StubFetcher()
    fetcher.page = _html(_BODY)
    track_document(db, fetcher, doc)
    # A small, non-large change: real (delta_bytes != 0) but NOT flagged.
    fetcher.page = _html(_BODY + " One more clause here.")
    res = track_document(db, fetcher, doc)
    assert res["status"] == "changed" and res["flagged"] is False

    default = law_changes(limit=50, db=db)
    assert len(default["changes"]) == 1  # visible without asking for flagged_only

    flagged_only = law_changes(flagged_only=True, limit=50, db=db)
    assert len(flagged_only["changes"]) == 0  # the opt-in filter still excludes it


def test_law_api(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    monkeypatch.setenv("OO_AUTOSEED", "0")
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        seeded = c.post("/api/law/seed").json()
        # Assert the idempotent TOTAL (created-or-already-present), so the test is robust
        # to the app DB being shared across TestClient tests in a full run.
        assert seeded["sources"]["total"] >= 30
        assert seeded["documents"]["total"] >= 5
        status = c.get("/api/law/status").json()
        assert status["documents"] >= 5 and "caveat" in status
        docs = c.get("/api/law/documents").json()
        assert len(docs["documents"]) >= 5


# --------------------------------------------------------------------------- #
#  S3 — add-a-document-by-URL (the missing workflow)
# --------------------------------------------------------------------------- #
def _law_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    monkeypatch.setenv("OO_AUTOSEED", "0")
    from fastapi.testclient import TestClient

    from src.api.main import app

    return TestClient(app)


class _StubOkFetcher:
    def fetch(self, url: str, *, require_html: bool = True, **_kw) -> FetchResult:
        return FetchResult(
            requested_url=url, final_url=url, status_code=200,
            content=_html(_BODY), content_type="text/html", fetched_at=datetime.now(UTC),
        )


class _StubRobotsBlockedFetcher:
    def fetch(self, url: str, *, require_html: bool = True, **_kw):
        from src.ingest import RobotsDisallowed

        raise RobotsDisallowed(f"robots.txt disallows {url}")


def test_add_document_tracks_it_immediately_and_returns_the_verdict(monkeypatch, tmp_path):
    c = _law_test_app(monkeypatch, tmp_path)
    monkeypatch.setattr("src.safety.fetcher.make_fetcher", lambda: _StubOkFetcher())
    with c:
        r = c.post("/api/law/documents", json={
            "jurisdiction": "kh", "title": "Code civil", "url": "https://law.example/kh-new",
            "language": "fr",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["jurisdiction"] == "kh" and body["language"] == "fr"
        assert body["track_result"]["status"] == "baseline"
        assert body["has_baseline"] is True


def test_add_document_rejects_a_duplicate_while_watched(monkeypatch, tmp_path):
    c = _law_test_app(monkeypatch, tmp_path)
    monkeypatch.setattr("src.safety.fetcher.make_fetcher", lambda: _StubOkFetcher())
    with c:
        payload = {"jurisdiction": "fr", "title": "Loi", "url": "https://law.example/fr-dup"}
        assert c.post("/api/law/documents", json=payload).status_code == 200
        r2 = c.post("/api/law/documents", json=payload)
        assert r2.status_code == 409


def test_add_document_rejects_a_non_http_url(monkeypatch, tmp_path):
    c = _law_test_app(monkeypatch, tmp_path)
    with c:
        r = c.post("/api/law/documents", json={
            "jurisdiction": "fr", "title": "x", "url": "javascript:alert(1)",
        })
        assert r.status_code == 422  # pydantic validation, never silently accepted


def test_add_document_stores_a_robots_blocked_url_honestly(monkeypatch, tmp_path):
    """S3 negative-space: a robots-blocked add is STORED (so it can be retried
    later) with its honest verdict -- never silently dropped, never fabricated
    as if it had been fetched."""
    c = _law_test_app(monkeypatch, tmp_path)
    monkeypatch.setattr("src.safety.fetcher.make_fetcher", lambda: _StubRobotsBlockedFetcher())
    with c:
        r = c.post("/api/law/documents", json={
            "jurisdiction": "de", "title": "Gesetz", "url": "https://law.example/de-blocked",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["track_result"]["status"] == "error"
        assert "robots" in body["last_status"].lower()
        assert body["has_baseline"] is False  # nothing fabricated


def test_delete_unwatches_never_deletes_the_row_or_history(monkeypatch, tmp_path):
    c = _law_test_app(monkeypatch, tmp_path)
    monkeypatch.setattr("src.safety.fetcher.make_fetcher", lambda: _StubOkFetcher())
    with c:
        added = c.post("/api/law/documents", json={
            "jurisdiction": "uk", "title": "Act", "url": "https://law.example/uk-del",
        }).json()
        doc_id = added["id"]
        r = c.delete(f"/api/law/documents/{doc_id}")
        assert r.status_code == 200 and r.json()["watched"] is False
        # Still readable — the historical record is never deleted.
        got = c.get(f"/api/law/documents/{doc_id}")
        assert got.status_code == 200 and got.json()["watched"] is False


def test_readding_after_unwatch_reactivates_instead_of_erroring(monkeypatch, tmp_path):
    c = _law_test_app(monkeypatch, tmp_path)
    monkeypatch.setattr("src.safety.fetcher.make_fetcher", lambda: _StubOkFetcher())
    with c:
        added = c.post("/api/law/documents", json={
            "jurisdiction": "uk", "title": "Act", "url": "https://law.example/uk-readd",
        }).json()
        doc_id = added["id"]
        c.delete(f"/api/law/documents/{doc_id}")
        r = c.post("/api/law/documents", json={
            "jurisdiction": "uk", "title": "Act (renamed)", "url": "https://law.example/uk-readd",
        })
        assert r.status_code == 200
        assert r.json()["id"] == doc_id  # SAME row reactivated, not a duplicate
        assert r.json()["watched"] is True
