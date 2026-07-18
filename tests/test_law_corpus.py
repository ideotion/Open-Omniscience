"""
Slice 3 (the law-vertical BODY) — laws become first-class corpus Articles.

The versioned-sources ruling: a law is an Article + a linked revision/audit trail.
This pins that (3.2) the tracker materialises the full fetched text onto the
document (``latest_text``/``latest_text_revid``) and the revision (``full_text``),
and (3.3) that text is ingested into the corpus through the ONE ``index_article``
hook as a filterable per-jurisdiction provenance class — mirroring wiki/corpus.py.

Includes the mandatory negative-space lens: a fail-to-extract document stores NO
body and NO corpus row; a re-fetch of unchanged text never duplicates the Article;
a corpus-sync failure never blocks or corrupts tracking.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import (
    Article,
    Base,
    KeywordMention,
    LawDocument,
    LawRevision,
    Source,
)
from src.ingest import FetchResult
from src.ingest.pdf import pdf_available
from src.law.corpus import ensure_law_source, law_canonical_url, sync_watched_laws
from src.law.track import track_document

_PDF_FIX = Path(__file__).parent / "fixtures" / "pdf"
needs_pypdf = pytest.mark.skipif(not pdf_available(), reason="pypdf ([pdf] extra) not installed")

# A realistic full text (well over the 200-char extraction floor).
_BODY = " ".join(
    f"Section {i}: every person shall have the right to liberty and security of person."
    for i in range(40)
)
_BIGGER = _BODY + " " + " ".join(
    f"Amendment {i}: this provision is hereby substituted and extended across the realm."
    for i in range(60)
)


def _html(body: str) -> str:
    return f"<html><head><title>Act</title></head><body><main>{body}</main></body></html>"


class StubFetcher:
    """A deterministic fetcher: serves a programmable HTML page per URL (no network)."""

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


def _doc(db, **kw) -> LawDocument:
    doc = LawDocument(jurisdiction="uk", title="Test Act", url="https://law.example/act", **kw)
    db.add(doc)
    db.commit()
    return doc


# --------------------------------------------------------------------------- #
#  3.2 — the tracker materialises the full text (document + revision)
# --------------------------------------------------------------------------- #
def test_baseline_stores_latest_text_and_revision_full_text(db):
    doc = _doc(db)
    fetcher = StubFetcher()
    fetcher.page = _html(_BODY)

    assert track_document(db, fetcher, doc)["status"] == "baseline"
    db.refresh(doc)
    # The materialised NEWEST text lives on the document, anchored to its revision.
    assert doc.latest_text is not None and "liberty and security" in doc.latest_text
    rev = db.query(LawRevision).filter_by(document_id=doc.id).one()
    assert doc.latest_text_revid == rev.id
    # The FULL baseline text is stored on the revision (not just a lossy diff).
    assert rev.full_text == doc.latest_text == doc.baseline_text


def test_change_stores_new_full_text_and_advances_latest(db):
    doc = _doc(db)
    fetcher = StubFetcher()
    fetcher.page = _html(_BODY)
    track_document(db, fetcher, doc)  # baseline

    fetcher.page = _html(_BIGGER)
    assert track_document(db, fetcher, doc)["status"] == "changed"
    db.refresh(doc)
    revs = db.query(LawRevision).filter_by(document_id=doc.id).order_by(LawRevision.id).all()
    assert len(revs) == 2  # baseline + the change
    change = revs[-1]
    # The new version's FULL text is stored + is the document's newest text.
    assert "Amendment 5" in change.full_text
    assert doc.latest_text == change.full_text
    assert doc.latest_text_revid == change.id


def test_revert_points_latest_at_the_seen_revision(db):
    doc = _doc(db)
    fetcher = StubFetcher()
    fetcher.page = _html(_BODY)
    track_document(db, fetcher, doc)  # baseline (rev A)
    baseline_rev_id = db.query(LawRevision).filter_by(document_id=doc.id).one().id

    fetcher.page = _html(_BIGGER)
    track_document(db, fetcher, doc)  # change (rev B) — latest now B

    fetcher.page = _html(_BODY)  # back to the baseline text
    assert track_document(db, fetcher, doc)["status"] == "reverted"
    db.refresh(doc)
    # latest_text reflects the reverted (baseline) text, anchored to the seen revision.
    assert doc.latest_text == doc.baseline_text
    assert doc.latest_text_revid == baseline_rev_id
    assert db.query(LawRevision).filter_by(document_id=doc.id).count() == 2  # no new rev


# --------------------------------------------------------------------------- #
#  3.3 — laws ingest into the corpus through the one index_article hook
# --------------------------------------------------------------------------- #
def test_baseline_creates_a_corpus_article_under_a_law_source(db):
    doc = LawDocument(
        jurisdiction="uk",
        title="Human Rights Act",
        url="https://law.example/act",
        official_url="https://www.legislation.gov.uk/ukpga/1998/42",
    )
    db.add(doc)
    db.commit()
    fetcher = StubFetcher()
    fetcher.page = _html(_BODY)
    track_document(db, fetcher, doc)

    # The corpus article is keyed on the OFFICIAL (canonical) url.
    art = db.query(Article).filter_by(canonical_url=law_canonical_url(doc)).one()
    assert art.title == "Human Rights Act"
    assert "liberty and security" in art.content
    assert art.language is None  # the document states no language — never guessed from the jurisdiction
    # Its source is the synthetic, filterable per-jurisdiction law provenance class.
    src = db.get(Source, art.source_id)
    assert src.domain == "law.uk.local"
    assert src.name == "Law (UK)"
    assert src.source_type == "legal"
    # It flowed through the ONE index_article hook: keyword mentions exist.
    assert db.query(KeywordMention).filter_by(article_id=art.id).count() > 0


def test_stated_document_language_threads_onto_the_new_corpus_article(db):
    """S4b (the Cambodia fix): the catalog's own asserted per-document language
    (e.g. a French-language Cambodian code) must reach the corpus Article, so
    the right stoplist/keyword treatment applies — a real, stated fact, not a
    guess from the jurisdiction."""
    doc = LawDocument(
        jurisdiction="kh", title="Code civil (Cambodge)", url="https://law.example/kh-code",
        language="fr",
    )
    db.add(doc)
    db.commit()
    fetcher = StubFetcher()
    fetcher.page = _html(_BODY)
    track_document(db, fetcher, doc)
    art = db.query(Article).filter_by(canonical_url=law_canonical_url(doc)).one()
    assert art.language == "fr"


def test_no_stated_language_stays_honestly_none_never_guessed_from_country(db):
    doc = LawDocument(jurisdiction="uk", title="Undated Act", url="https://law.example/undated",
                      country="gb")  # a country is stated, but NOT a language
    db.add(doc)
    db.commit()
    fetcher = StubFetcher()
    fetcher.page = _html(_BODY)
    track_document(db, fetcher, doc)
    art = db.query(Article).filter_by(canonical_url=law_canonical_url(doc)).one()
    assert art.language is None


def test_existing_article_heals_its_language_on_a_re_ingest(db):
    """S4b acceptance: 'existing docs heal' -- an article created before the
    document had a stated language must pick it up once the document is later
    given one (idempotent re-ingest), even when the fetched text is UNCHANGED.

    Self-review finding 2026-07-17: track_document's OWN steady-state
    "unchanged" fast path skips corpus re-sync entirely once a document
    already has latest_text (a deliberate perf optimisation -- see
    src/law/track.py's ``backfilled`` gate), so two track_document() calls in
    a row do NOT exercise this path. The real healing trigger is
    ``register_documents`` re-reading the catalog (tested in
    tests/test_law.py); this test drives ``upsert_law_corpus_article``
    directly (itself a real, reachable code path -- see the sqlcipher3/
    reraise tests above using the same direct-call pattern) to pin the
    function's own idempotent-re-ingest healing behaviour precisely."""
    from src.law.corpus import upsert_law_corpus_article

    doc = LawDocument(jurisdiction="kh", title="Code civil (Cambodge)", url="https://law.example/kh-code2",
                      latest_text=_BODY)
    db.add(doc)
    db.commit()
    upsert_law_corpus_article(db, doc=doc)
    art = db.query(Article).filter_by(canonical_url=law_canonical_url(doc)).one()
    assert art.language is None

    doc.language = "fr"  # the catalog is later re-read / the document re-registered
    db.commit()
    res = upsert_law_corpus_article(db, doc=doc)  # same text -> "unchanged"
    assert res["status"] == "unchanged"
    db.refresh(art)
    assert art.language == "fr"  # healed even though the text itself never changed


def test_unchanged_refetch_does_not_duplicate_the_article(db):
    doc = _doc(db)
    fetcher = StubFetcher()
    fetcher.page = _html(_BODY)
    track_document(db, fetcher, doc)  # baseline → 1 article
    assert track_document(db, fetcher, doc)["status"] == "unchanged"  # same text again
    assert db.query(Article).filter_by(canonical_url=law_canonical_url(doc)).count() == 1


def test_change_updates_the_same_article_in_place(db):
    doc = _doc(db)
    fetcher = StubFetcher()
    fetcher.page = _html(_BODY)
    track_document(db, fetcher, doc)
    art_id = db.query(Article).filter_by(canonical_url=law_canonical_url(doc)).one().id

    fetcher.page = _html(_BIGGER)
    track_document(db, fetcher, doc)
    arts = db.query(Article).filter_by(canonical_url=law_canonical_url(doc)).all()
    assert len(arts) == 1 and arts[0].id == art_id  # same row, updated in place
    assert "Amendment 5" in arts[0].content


def test_ensure_law_source_is_idempotent_and_never_collides_with_a_scraped_source(db):
    # A real scraped source with an ordinary domain must stay separate.
    db.add(Source(name="Legislation.gov.uk", domain="legislation.gov.uk", source_type="legal"))
    db.commit()
    a = ensure_law_source(db, "uk")
    b = ensure_law_source(db, "uk")
    assert a.id == b.id  # idempotent
    assert a.domain == "law.uk.local"  # synthetic, never the scraped portal domain
    assert db.query(Source).filter_by(domain="legislation.gov.uk").count() == 1


def test_sync_watched_laws_backfills_existing_documents(db):
    # A document that already holds baseline text but was never ingested.
    doc = _doc(db, baseline_text=_BODY, latest_text=_BODY, last_hash="x", watched=True)
    out = sync_watched_laws(db)
    assert out["created"] == 1
    assert db.query(Article).filter_by(canonical_url=law_canonical_url(doc)).count() == 1
    # Idempotent second pass — no duplicate.
    assert sync_watched_laws(db)["unchanged"] == 1
    assert db.query(Article).filter_by(canonical_url=law_canonical_url(doc)).count() == 1


# --------------------------------------------------------------------------- #
#  Negative space — degrade loudly, never fabricate, never block tracking
# --------------------------------------------------------------------------- #
def test_failed_extraction_stores_no_body_and_no_corpus_row(db):
    doc = _doc(db)
    fetcher = StubFetcher()
    fetcher.page = _html("Too short.")  # below the 200-char extraction floor
    res = track_document(db, fetcher, doc)
    assert res["status"] == "empty"
    db.refresh(doc)
    assert doc.baseline_text is None and doc.latest_text is None  # nothing fabricated
    assert db.query(Article).count() == 0
    assert db.query(LawRevision).count() == 0


def test_corpus_sync_failure_never_blocks_tracking(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("index_article exploded")

    monkeypatch.setattr("src.law.corpus.sync_law_to_corpus", boom)
    doc = _doc(db)
    fetcher = StubFetcher()
    fetcher.page = _html(_BODY)
    # Tracking still succeeds and its data persists even though ingest blew up.
    assert track_document(db, fetcher, doc)["status"] == "baseline"
    db.refresh(doc)
    assert doc.latest_text is not None
    assert db.query(LawRevision).filter_by(document_id=doc.id).count() == 1
    # And the session is usable for a further write (not poisoned).
    db.add(LawDocument(jurisdiction="fr", title="Loi", url="https://law.example/loi"))
    db.commit()
    assert db.query(LawDocument).count() == 2


def test_identical_text_in_two_laws_dedups_not_errors(db):
    """Model legislation copied across jurisdictions extracts to IDENTICAL text →
    the globally-unique Article.hash collides. It must DEDUP honestly, never raise
    (a raise would be swallowed as a silent log-only corpus-ingest failure) — and
    tracking of BOTH documents must survive. (Reviewer HIGH finding, pinned.)"""
    fetcher = StubFetcher()
    fetcher.page = _html(_BODY)
    a = LawDocument(jurisdiction="uk", title="Model Act (UK)", url="https://uk.example/x",
                    official_url="https://uk.example/x")
    b = LawDocument(jurisdiction="us", title="Model Act (US)", url="https://us.example/y",
                    official_url="https://us.example/y")
    db.add_all([a, b])
    db.commit()
    assert track_document(db, fetcher, a)["status"] == "baseline"
    assert track_document(db, fetcher, b)["status"] == "baseline"  # tracked, did not raise
    db.refresh(a)
    db.refresh(b)
    assert a.latest_text is not None and b.latest_text is not None  # both fully tracked
    # ONE deduped corpus article for the shared text; each doc keeps its own revision.
    assert db.query(Article).count() == 1
    assert db.query(LawRevision).count() == 2
    # Session not poisoned — a further unrelated write commits cleanly.
    db.add(LawDocument(jurisdiction="fr", title="Loi", url="https://fr.example/z"))
    db.commit()
    assert db.query(LawDocument).count() == 3


def test_upsert_absorbs_a_sqlcipher3_style_hash_collision(db, monkeypatch):
    """Audit finding 2026-07-17: upsert_law_corpus_article's duplicate-content
    dedup caught only sqlalchemy.exc.IntegrityError, but on the ENCRYPTED
    (sqlcipher3) store a UNIQUE Article.hash collision surfaces as the driver's
    OWN unwrapped exception class -- the same cross-driver divergence already
    fixed for is_locked_error/classify_restore_error/src/law/track.py. Simulates
    that exact exception (mirroring tests/test_classify_restore_error_sqlcipher.py's
    fixture technique) to prove the real is_integrity_error-based dispatch handles
    it, rather than letting a genuine (benign) hash collision escape uncaught."""
    import sys
    import types

    from src.database import write as write_mod
    from src.law.corpus import upsert_law_corpus_article

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

    a = LawDocument(jurisdiction="uk", title="Model Act (UK)", url="https://uk.example/x2",
                    official_url="https://uk.example/x2", latest_text=_BODY)
    b = LawDocument(jurisdiction="us", title="Model Act (US)", url="https://us.example/y2",
                    official_url="https://us.example/y2", latest_text=_BODY)
    db.add_all([a, b])
    db.commit()

    assert upsert_law_corpus_article(db, doc=a)["status"] == "created"
    real_commit = db.commit

    def _commit_raise_when_article_pending(*args, **kwargs):
        if any(isinstance(o, Article) for o in db.new):
            raise _FakeSqlcipherIntegrityError("UNIQUE constraint failed: articles.hash")
        return real_commit(*args, **kwargs)

    monkeypatch.setattr(db, "commit", _commit_raise_when_article_pending)
    try:
        res = upsert_law_corpus_article(db, doc=b)  # same latest_text => same hash => would collide
    finally:
        write_mod._db_integrity_error_types.cache_clear()  # never leak the fake into other tests

    assert res["status"] == "duplicate-content"  # absorbed via is_integrity_error, not raised
    assert db.query(Article).count() == 1  # deduped onto the one existing Article


def test_upsert_reraises_a_genuinely_unexpected_exception(db, monkeypatch):
    """A failure that is neither a lock nor an integrity violation must still surface
    loudly -- never be silently swallowed as a duplicate."""
    from src.law.corpus import upsert_law_corpus_article

    doc = LawDocument(jurisdiction="uk", title="Boom Act", url="https://law.example/boom",
                      official_url="https://law.example/boom", latest_text=_BODY)
    db.add(doc)
    db.commit()

    real_commit = db.commit

    def _commit_raise_when_article_pending(*args, **kwargs):
        if any(isinstance(o, Article) for o in db.new):
            raise RuntimeError("disk full")
        return real_commit(*args, **kwargs)

    monkeypatch.setattr(db, "commit", _commit_raise_when_article_pending)
    with pytest.raises(RuntimeError, match="disk full"):
        upsert_law_corpus_article(db, doc=doc)


# --------------------------------------------------------------------------- #
#  PDF laws — the tracker extracts a gazette PDF, and a scan stores nothing
# --------------------------------------------------------------------------- #
class _PdfFetcher:
    """A fetcher double returning a PDF body: raw_content carries the real bytes,
    content is the (mangled) text-decode the real fetcher would produce."""

    def __init__(self, pdf_bytes: bytes):
        self._bytes = pdf_bytes

    def fetch(self, url: str, *, require_html: bool = True, keep_bytes: bool = False, **_kw):
        return FetchResult(
            requested_url=url,
            final_url=url,
            status_code=200,
            content=self._bytes.decode("latin-1", "replace"),  # what a text decode yields
            content_type="application/pdf",
            fetched_at=datetime.now(UTC),
            raw_content=self._bytes if keep_bytes else None,
        )


@needs_pypdf
def test_track_document_ingests_a_pdf_law(db):
    doc = LawDocument(jurisdiction="uk", title="PDF Act", url="https://gazette.example/act.pdf")
    db.add(doc)
    db.commit()
    res = track_document(db, _PdfFetcher((_PDF_FIX / "text_statute.pdf").read_bytes()), doc)
    assert res["status"] == "baseline"
    db.refresh(doc)
    assert doc.latest_text and "liberty and security" in doc.latest_text
    # The PDF law became a first-class corpus article.
    assert db.query(Article).filter_by(canonical_url=doc.url).count() == 1


@needs_pypdf
def test_track_document_scanned_pdf_stores_no_body_no_corpus_row(db):
    # The negative-space case: a scanned/image PDF must not fabricate a law body.
    doc = LawDocument(jurisdiction="uk", title="Scan", url="https://gazette.example/scan.pdf")
    db.add(doc)
    db.commit()
    res = track_document(db, _PdfFetcher((_PDF_FIX / "scanned_image.pdf").read_bytes()), doc)
    assert res["status"] == "empty"
    assert "scanned" in res["detail"] or "no extractable text" in res["detail"]
    db.refresh(doc)
    assert doc.baseline_text is None and doc.latest_text is None
    assert db.query(Article).count() == 0
