"""
C12 (2026-07-24 throughput brief, A2): the in-memory dedup front WIRED into
``src.ingest.pipeline._exists``/``store_fetched`` and ``src.ingest.batch``'s
two store-success paths (batched flush + the per-article redo fallback).

THE MANDATORY NEGATIVE-SPACE PROPERTY (never a false negative — no lost dedup,
no article stored twice): ``_exists()`` can return ``False`` ONLY via the real
authoritative DB query (the front's own MISS never short-circuits it) — so
this file proves the property STRUCTURALLY, by exercising the front in states
where a naive/buggy implementation could plausibly get it wrong (a cold front,
an evicted front, a front warmed by an UNRELATED key) and confirming the
combined system still correctly reports "exists" for anything genuinely
stored, and correctly reports "does not exist" for anything genuinely new
(never a false positive that would silently drop a new article either).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.ingest.batch import ArticleBatch
from src.ingest.dedup_front import seen_canonical_url, seen_content_hash
from src.ingest.pipeline import IngestResult, _exists, store_fetched


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 't.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    s = Sess()
    yield s
    s.close()


@pytest.fixture()
def source(session):
    src = Source(name="Test Source", domain="test.example")
    session.add(src)
    session.commit()
    return src


def _article_html(title: str, body_sentence: str) -> str:
    body = (body_sentence + " ") * 30  # well over the extractor's min length
    return (
        f"<html><head><title>{title}</title>"
        f"<meta property='og:title' content='{title}'></head>"
        f"<body><article><h1>{title}</h1><p>{body}</p></article></body></html>"
    )


class _Fetched:
    def __init__(self, url: str, content: str):
        self.requested_url = url
        self.final_url = url
        self.content = content
        self.server_ip = None
        self.server_ip_reason = None
        self.fetched_at = datetime.now(UTC)


# --------------------------------------------------------------------------- #
# _exists(): the front short-circuits a HIT; a MISS always falls through to
# the real (authoritative) query -- so a False can only ever come from a real
# "not found" DB result.
# --------------------------------------------------------------------------- #


def test_a_genuine_db_row_is_found_even_on_a_cold_front(session, source):
    """No front warmth at all (a fresh process / just-restarted app): the
    check must still fall through to the DB and find a genuinely stored row."""
    a = Article(
        url="https://test.example/a", canonical_url="https://test.example/a",
        source_id=source.id, title="A", content="x" * 200, hash="hash-a",
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    session.add(a)
    session.commit()
    assert len(seen_canonical_url()) == 0 and len(seen_content_hash()) == 0  # cold front
    assert _exists(session, canonical_url="https://test.example/a") is True
    assert _exists(session, hash="hash-a") is True


def test_a_genuinely_new_key_never_false_positives(session, source):
    """The other direction (equally critical): a key that is NOT in the DB
    and NOT in the front must report False -- never silently treated as an
    existing duplicate (which would drop a genuinely new article)."""
    assert _exists(session, canonical_url="https://test.example/never-stored") is False
    assert _exists(session, hash="never-stored-hash") is False


def test_a_confirmed_db_hit_warms_the_front_for_the_next_check(session, source):
    a = Article(
        url="https://test.example/b", canonical_url="https://test.example/b",
        source_id=source.id, title="B", content="x" * 200, hash="hash-b",
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    session.add(a)
    session.commit()
    assert _exists(session, canonical_url="https://test.example/b") is True  # first check: DB
    assert "https://test.example/b" in seen_canonical_url()  # now warmed
    assert "hash-b" not in seen_content_hash()  # ONLY the checked keyspace warms

    assert _exists(session, hash="hash-b") is True  # warms the hash front too
    assert "hash-b" in seen_content_hash()


def test_a_front_hit_skips_the_db_query_entirely(session, source, monkeypatch):
    seen_canonical_url().add("https://test.example/c")  # pretend already warmed

    def _boom(*a, **k):
        raise AssertionError("the DB must never be queried on a front HIT")

    monkeypatch.setattr(session, "query", _boom)
    assert _exists(session, canonical_url="https://test.example/c") is True


def test_eviction_never_causes_a_false_negative_end_to_end(session, source, monkeypatch):
    """The property that matters most: even if the front's bounded LRU evicts
    a key that genuinely exists in the DB, the combined system STILL correctly
    reports "exists" -- because a front MISS always falls through to the real
    query. Simulated here by forcing __contains__ to always miss (the same
    observable effect as an evicted key)."""
    a = Article(
        url="https://test.example/d", canonical_url="https://test.example/d",
        source_id=source.id, title="D", content="x" * 200, hash="hash-d",
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    session.add(a)
    session.commit()
    from src.ingest.dedup_front import BoundedSeenSet

    monkeypatch.setattr(BoundedSeenSet, "__contains__", lambda self, key: False)  # force-evicted
    assert _exists(session, canonical_url="https://test.example/d") is True  # still found via DB
    assert _exists(session, hash="hash-d") is True


def test_an_unrecognised_filter_shape_bypasses_the_front_and_is_unaffected(session, source):
    """A filter that is not exactly one of the two known dedup keyspaces (e.g.
    a hypothetical future caller, or more than one kwarg) must behave EXACTLY
    as the pre-C12 code did -- straight to the real query, no front lookup."""
    a = Article(
        url="https://test.example/e", canonical_url="https://test.example/e",
        source_id=source.id, title="E", content="x" * 200, hash="hash-e",
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    session.add(a)
    session.commit()
    assert _exists(session, id=a.id) is True
    assert _exists(session, id=99999) is False


# --------------------------------------------------------------------------- #
# store_fetched: the direct (non-batched) commit path populates the front.
# --------------------------------------------------------------------------- #


def test_store_fetched_populates_the_front_on_a_confirmed_store(session, source):
    fetched = _Fetched("https://test.example/f", _article_html("F", "Fresh content sentence."))
    outcome = store_fetched(session, source, fetched)
    assert outcome.result == IngestResult.STORED
    article = session.query(Article).filter_by(id=outcome.article_id).first()
    assert article.canonical_url in seen_canonical_url()
    assert article.hash in seen_content_hash()


def test_a_stored_article_is_never_lost_to_a_stale_front_on_the_next_ingest(session, source):
    """Simulates the whole point of C12: fetch/store the same URL TWICE (the
    field-measured re-served-feed-item case). The second attempt must be
    correctly reported as a DUPLICATE (via the front, no DB round-trip
    needed) -- never silently re-stored, never silently treated as new."""
    html = _article_html("G", "Same content every time.")
    fetched1 = _Fetched("https://test.example/g", html)
    out1 = store_fetched(session, source, fetched1)
    assert out1.result == IngestResult.STORED

    fetched2 = _Fetched("https://test.example/g", html)  # identical content -> same hash
    out2 = store_fetched(session, source, fetched2)
    assert out2.result == IngestResult.DUPLICATE
    assert session.query(Article).count() == 1  # never stored twice


# --------------------------------------------------------------------------- #
# ArticleBatch: both store-success paths (flush + the per-article redo
# fallback) also populate the front.
# --------------------------------------------------------------------------- #


def test_batch_flush_populates_the_front_for_every_stored_article(session, source):
    batch = ArticleBatch(session, source, size=10)  # large size -- flush() called explicitly
    from src.ingest.extract import extract_article

    for i in range(3):
        html = _article_html(f"H{i}", f"Batch content number {i} distinct.")
        doc = extract_article(html, url=f"https://test.example/h{i}")
        from src.ingest.pipeline import canonicalize_url, generate_content_hash

        canonical = canonicalize_url(f"https://test.example/h{i}")
        content_hash = generate_content_hash(doc.text)
        fetched = _Fetched(f"https://test.example/h{i}", html)
        batch.stage(fetched, doc, canonical, content_hash)
    batch.flush()
    assert batch.tally["stored"] == 3
    assert session.query(Article).count() == 3
    for i in range(3):
        a = session.query(Article).filter_by(url=f"https://test.example/h{i}").first()
        assert a is not None
        assert a.canonical_url in seen_canonical_url()
        assert a.hash in seen_content_hash()


def test_batch_redo_path_populates_the_front(session, source):
    """Directly exercises the per-article redo fallback (_store_one), the
    path used when a batched commit fails and is redone one article at a
    time."""
    batch = ArticleBatch(session, source, size=10)
    from src.ingest.pipeline import canonicalize_url, generate_content_hash
    from src.ingest.extract import extract_article

    html = _article_html("I", "Redo path content sentence unique.")
    doc = extract_article(html, url="https://test.example/i")
    canonical = canonicalize_url("https://test.example/i")
    content_hash = generate_content_hash(doc.text)
    fetched = _Fetched("https://test.example/i", html)
    from src.ingest.batch import _StagedArticle

    staged = _StagedArticle(
        requested_url=fetched.requested_url, canonical_url=canonical, content_hash=content_hash,
        title=doc.title, text=doc.text, published_at=doc.published_at, language=doc.language,
        author=doc.author, server_ip=None, server_ip_reason=None, fetched_at=fetched.fetched_at,
    )
    batch._store_one(staged)
    assert batch.tally["stored"] == 1
    assert canonical in seen_canonical_url()
    assert content_hash in seen_content_hash()
